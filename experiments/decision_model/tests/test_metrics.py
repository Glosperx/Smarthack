import pytest

from decision_model.metrics import (
    argmax,
    brier,
    confusion,
    consistency,
    ece,
    macro_auc,
    roc_auc,
)


def test_roc_auc_perfect_reversed_and_ties() -> None:
    assert roc_auc([0.9, 0.8, 0.2, 0.1], [True, True, False, False]) == 1.0
    assert roc_auc([0.1, 0.2, 0.8, 0.9], [True, True, False, False]) == 0.0
    assert roc_auc([0.5, 0.5], [True, False]) == 0.5
    assert roc_auc([0.9, 0.3, 0.6], [True, False, True]) == 1.0


def test_roc_auc_needs_both_classes() -> None:
    assert roc_auc([0.2, 0.4], [True, True]) is None
    with pytest.raises(ValueError):
        roc_auc([0.1], [True, False])


def test_macro_auc_averages_known_classes() -> None:
    probs = [{"a": 0.8, "b": 0.2}, {"a": 0.3, "b": 0.7}]

    mean, per = macro_auc(probs, ["a", "b"], ["a", "b", "c"])

    assert per == {"a": 1.0, "b": 1.0, "c": None}
    assert mean == 1.0


def test_argmax_confusion_and_brier() -> None:
    assert argmax({"x": 0.2, "y": 0.8}) == "y"
    assert confusion(["a", "a", "b"], ["a", "b", "b"], ["a", "b"]) == {
        "a": {"a": 1, "b": 1},
        "b": {"a": 0, "b": 1},
    }
    assert brier([{"a": 1.0, "b": 0.0}], ["a"], ["a", "b"]) == 0.0
    assert brier([{"a": 0.0, "b": 1.0}], ["a"], ["a", "b"]) == 2.0


def test_ece_is_zero_when_confidence_matches_accuracy() -> None:
    assert ece([1.0, 1.0], [True, True]) == 0.0
    assert ece([0.9, 0.9], [False, False]) == pytest.approx(0.9)
    assert ece([], []) == 0.0


def test_consistency_counts_order_flips() -> None:
    stable = [{"a": 0.9, "b": 0.1}, {"a": 0.8, "b": 0.2}]
    flipped = [{"a": 0.6, "b": 0.4}, {"a": 0.4, "b": 0.6}]

    same, spread = consistency([stable, flipped])

    assert same == 0.5
    assert spread == pytest.approx((0.1 + 0.2) / 2)


def test_golden_compare_reports_choice_and_largest_gap() -> None:
    from decision_model.golden import compare

    result = compare({"a": 0.7, "b": 0.3}, {"a": 0.6, "b": 0.4})

    assert result == {"same_choice": True, "max_abs_diff": 0.1}


def test_paired_bootstrap_is_zero_for_identical_and_positive_for_better() -> None:
    from decision_model.metrics import paired_bootstrap

    pos = [True, False] * 10
    same = paired_bootstrap([True] * 20, [True] * 20, [0.9, 0.1] * 10, [1.0, 0.0] * 10, pos, 200)
    assert same["accuracy_diff"] == (0.0, 0.0)
    assert same["auc_diff"] == (0.0, 0.0)

    better = paired_bootstrap([True] * 20, [False] * 20, [0.9, 0.1] * 10, [0.0, 1.0] * 10, pos, 200)
    assert better["accuracy_diff"] == (1.0, 1.0)
    assert better["auc_diff"] == (1.0, 1.0)
