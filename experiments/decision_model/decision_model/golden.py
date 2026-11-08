"""
# Reference checks

Checks that a model runs on this Mac as its authors published it, by answering the examples
they ship with their published outputs:

- Cerno: `inference/examples/requests.json` against `answers.json` (their H200 run);
- Jeffan: the example of its model card;
- GLiDE 0.4B: the example of its model card (only the first question's choice and confidence
  are published).

Run from `experiments/decision_model`:

    uv run python -I -m decision_model.golden cerno-4b

The following can be imported from this module:
- `compare`
- `main`
"""

import argparse
import json
from typing import Any

from decision_model.adapters import MODELS_DIR, load_adapter

JEFFAN_EXAMPLE: dict[str, Any] = {
    "state": "Ticket #1042: the parcel arrived with the screen cracked; the customer asks for a "
    "replacement.",
    "question": "Which team should handle this ticket?",
    "options": ["Billing", "Shipping damage claims", "Technical support"],
    "published": {"Billing": 0.0010, "Shipping damage claims": 0.9621, "Technical support": 0.0369},
}

GLIDE_EXAMPLE: dict[str, Any] = {
    "state": {
        "ticket": "I was charged twice for order #4821 and the second charge is still pending.",
        "customer_tier": "gold",
    },
    "question": {
        "type": "choice",
        "instructions": "What does the customer want?",
        "criteria": {
            "refund": "Get money back",
            "cancel": "Cancel the order",
            "track": "Track a delivery",
            "other": "Something else",
        },
    },
    "published_choice": "refund",
    "published_confidence": 0.956,
}


def compare(mine: dict[str, float], published: dict[str, float]) -> dict[str, Any]:
    """
    Compare two distributions over the same options.

    :param mine: Probabilities from this run.
    :param published: Probabilities the authors published.

    :returns comparison: Same top option, and the largest absolute difference.
    """
    top_mine = max(mine, key=lambda k: mine[k])
    top_pub = max(published, key=lambda k: published[k])
    diff = max(abs(mine[k] - published[k]) for k in published)
    return {"same_choice": top_mine == top_pub, "max_abs_diff": round(diff, 4)}


def _cerno() -> list[dict[str, Any]]:
    """Cerno 4B v1.2 on its shipped examples, every choice and score question."""
    adapter: Any = load_adapter("cerno-4b")
    examples = MODELS_DIR / "cerno-4b-v1.2" / "inference" / "examples"
    requests = json.loads((examples / "requests.json").read_text(encoding="utf-8"))
    published = json.loads((examples / "answers.json").read_text(encoding="utf-8"))
    published = published["apertixai/cerno-4b-v1.2"]
    out = []
    for r in requests:
        response, _ = adapter.engine(r["state"], r["questions"])
        for qid, answer in response["answers"].items():
            ref = published[r["name"]][qid]
            if "probabilities" in answer and "probabilities" in ref:
                mine = {str(k): float(v) for k, v in answer["probabilities"].items()}
                theirs = {str(k): float(v) for k, v in ref["probabilities"].items()}
                out.append({"request": r["name"], "question": qid, **compare(mine, theirs)})
            elif "noul" in answer:
                diff = abs(float(answer["noul"]) - float(ref["noul"]))
                same = (answer["noul"] >= 0.5) == (ref["noul"] >= 0.5)
                out.append(
                    {
                        "request": r["name"],
                        "question": qid,
                        "same_choice": same,
                        "max_abs_diff": round(diff, 4),
                    }
                )
    return out


def _jeffan() -> list[dict[str, Any]]:
    """Jeffan on the example of its model card."""
    adapter = load_adapter("jeffan-4b")
    criteria = {o: None for o in JEFFAN_EXAMPLE["options"]}
    question = {"type": "choice", "instructions": JEFFAN_EXAMPLE["question"], "criteria": criteria}
    probs = adapter.choice({"state": JEFFAN_EXAMPLE["state"], "questions": {"q": question}})
    return [{"request": "model card", **compare(probs, JEFFAN_EXAMPLE["published"])}]


def _glide() -> list[dict[str, Any]]:
    """GLiDE 0.4B on the example of its model card."""
    adapter = load_adapter("glide-0.4b")
    request = {"state": GLIDE_EXAMPLE["state"], "questions": {"q": GLIDE_EXAMPLE["question"]}}
    probs = adapter.choice(request)
    ranked = sorted(probs.values(), reverse=True)
    top = max(probs, key=lambda k: probs[k])
    return [
        {
            "request": "model card",
            "same_choice": top == GLIDE_EXAMPLE["published_choice"],
            "max_abs_diff": round(abs((ranked[0] - ranked[1]) - 0.956), 4),
        }
    ]


def main(argv: list[str] | None = None) -> int:
    """
    Run one reference check and print it as JSON.

    :param argv: Arguments; None reads `sys.argv`.

    :returns status: 0 when every top option matches, 1 otherwise.
    """
    parser = argparse.ArgumentParser(description="Check a model against its published outputs.")
    parser.add_argument("model", choices=["cerno-4b", "jeffan-4b", "glide-0.4b"])
    args = parser.parse_args(argv)
    checks = {"cerno-4b": _cerno, "jeffan-4b": _jeffan, "glide-0.4b": _glide}[args.model]()
    print(json.dumps({"model": args.model, "checks": checks}, indent=1))
    return 0 if all(c["same_choice"] for c in checks) else 1


__all__ = ["compare", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
