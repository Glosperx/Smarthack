"""
# Metrics

Plain-Python scoring of decisions against labels: ROC AUC (with ties), accuracy, confusion
matrix, calibration (ECE and Brier) and consistency across option orders.

The following can be imported from this module:
- `roc_auc`
- `macro_auc`
- `argmax`
- `confusion`
- `ece`
- `brier`
- `consistency`
- `paired_bootstrap`
"""

from collections.abc import Mapping, Sequence


def roc_auc(scores: Sequence[float], positive: Sequence[bool]) -> float | None:
    """
    Area under the ROC curve: the chance that a random positive scores above a random negative,
    ties counting half (Mann-Whitney).

    :param scores: One score per case; higher means more likely positive.
    :param positive: Whether each case is positive.

    :returns auc: Between 0 and 1, or None when one of the classes is empty.
    :raises ValueError: When the lengths differ.
    """
    if len(scores) != len(positive):
        raise ValueError("scores and labels differ in length")
    n_pos = sum(1 for p in positive if p)
    n_neg = len(positive) - n_pos
    if not n_pos or not n_neg:
        return None
    # Rank-sum form: tied scores share the mean of their ranks, which counts ties as half.
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    rank_sum = sum(r for r, p in zip(ranks, positive) if p)
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def paired_bootstrap(
    model_correct: Sequence[bool],
    rule_correct: Sequence[bool],
    model_scores: Sequence[float],
    rule_scores: Sequence[float],
    positive: Sequence[bool],
    resamples: int = 2000,
    seed: int = 0,
) -> dict[str, tuple[float, float] | None]:
    """
    95% intervals for how much a model beats the rule on the same cases, by resampling cases.

    :param model_correct: Whether the model was right on each case.
    :param rule_correct: Whether the rule was right on each case.
    :param model_scores: The model's score for the yes/no question of interest.
    :param rule_scores: The rule's score (0 or 1) for the same question.
    :param positive: Whether each case is positive for that question.
    :param resamples: Bootstrap resamples.
    :param seed: Random seed, fixed so the report is reproducible.

    :returns intervals: {"accuracy_diff": (low, high), "auc_diff": (low, high) or None}.
    """
    import random

    rng = random.Random(seed)
    n = len(model_correct)
    acc, auc = [], []
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        acc.append(sum(model_correct[i] - rule_correct[i] for i in idx) / n)
        a = roc_auc([model_scores[i] for i in idx], [positive[i] for i in idx])
        b = roc_auc([rule_scores[i] for i in idx], [positive[i] for i in idx])
        if a is not None and b is not None:
            auc.append(a - b)

    def interval(values: list[float]) -> tuple[float, float] | None:
        if not values:
            return None
        values.sort()
        return values[int(0.025 * len(values))], values[int(0.975 * len(values)) - 1]

    return {"accuracy_diff": interval(acc), "auc_diff": interval(auc)}


def macro_auc(
    probabilities: Sequence[Mapping[str, float]], labels: Sequence[str], classes: Sequence[str]
) -> tuple[float | None, dict[str, float | None]]:
    """
    One-against-the-rest AUC for each class and their mean.

    :param probabilities: One distribution over `classes` per case.
    :param labels: The correct class of each case.
    :param classes: The classes to score.

    :returns auc: (mean over the classes that have both positives and negatives, per-class AUC).
    """
    per = {
        c: roc_auc([p.get(c, 0.0) for p in probabilities], [lab == c for lab in labels])
        for c in classes
    }
    known = [v for v in per.values() if v is not None]
    return (sum(known) / len(known) if known else None), per


def argmax(probabilities: Mapping[str, float]) -> str:
    """The most probable option; ties go to the first in sorted key order."""
    return max(sorted(probabilities), key=lambda k: probabilities[k])


def confusion(
    labels: Sequence[str], predicted: Sequence[str], classes: Sequence[str]
) -> dict[str, dict[str, int]]:
    """
    Count label (rows) against prediction (columns).

    :param labels: Correct classes.
    :param predicted: Predicted classes.
    :param classes: Row and column order.

    :returns matrix: matrix[label][predicted] = count.
    """
    matrix = {a: {b: 0 for b in classes} for a in classes}
    for lab, pred in zip(labels, predicted):
        matrix[lab][pred] += 1
    return matrix


def ece(confidence: Sequence[float], correct: Sequence[bool], bins: int = 10) -> float:
    """
    Expected calibration error over equal-width confidence bins.

    :param confidence: Probability of the chosen option for each case.
    :param correct: Whether the chosen option was right.
    :param bins: Number of bins on [0, 1].

    :returns ece: Weighted mean gap between confidence and accuracy; 0 for no cases.
    """
    n = len(confidence)
    if n == 0:
        return 0.0
    total = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, c in enumerate(confidence) if lo < c <= hi or (b == 0 and c == 0.0)]
        if not idx:
            continue
        conf = sum(confidence[i] for i in idx) / len(idx)
        acc = sum(1.0 for i in idx if correct[i]) / len(idx)
        total += len(idx) / n * abs(conf - acc)
    return total


def brier(
    probabilities: Sequence[Mapping[str, float]], labels: Sequence[str], classes: Sequence[str]
) -> float:
    """
    Multi-class Brier score: mean squared distance to the one-hot label (0 is perfect, 2 worst).

    :param probabilities: One distribution per case.
    :param labels: Correct classes.
    :param classes: All classes.

    :returns brier: Mean over the cases; 0 for no cases.
    """
    if not labels:
        return 0.0
    total = 0.0
    for p, lab in zip(probabilities, labels):
        total += sum((p.get(c, 0.0) - (1.0 if c == lab else 0.0)) ** 2 for c in classes)
    return total / len(labels)


def consistency(runs: Sequence[Sequence[Mapping[str, float]]]) -> tuple[float, float]:
    """
    How stable the answers are when the same request is sent with the options in other orders.

    :param runs: For each case, its distributions over the runs (same option keys).

    :returns stability: (share of cases whose chosen option is the same in every run,
        mean over cases of the largest probability change between runs).
    """
    if not runs:
        return 1.0, 0.0
    same = 0
    spread = 0.0
    for case in runs:
        if len({argmax(p) for p in case}) == 1:
            same += 1
        keys = case[0].keys()
        spread += max(max(p[k] for p in case) - min(p[k] for p in case) for k in keys)
    return same / len(runs), spread / len(runs)


__all__ = [
    "roc_auc",
    "macro_auc",
    "argmax",
    "confusion",
    "ece",
    "brier",
    "consistency",
    "paired_bootstrap",
]
