"""
# Scenarios

The labelled test set: about 80 situations for each decision. Clear cases cover every option and
are labelled with the rule of today, which decides them without doubt. Border cases (window edge,
0.69 against 0.71, WATCH with a short lead time, low ML1 confidence, turbines of other parks,
the "no failure" value 8) take their label from `data/border_labels.json`, written by hand with
a reason for each, before any model was run.

The following can be imported from this module:
- `Scenario`
- `ml2_scenarios`
- `channel_scenarios`
- `all_scenarios`
- `load_border_labels`
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from decision_model.rules import CONFLICT_WINDOW_DAYS, rule_channel, rule_ml2

BORDER_LABELS = Path(__file__).resolve().parent.parent / "data" / "border_labels.json"
OWN_PARK = "wind_farm_a"
SUBSYSTEMS = [
    "gearbox bearing",
    "generator winding",
    "pitch system",
    "main bearing",
    "converter",
    "yaw drive",
    "hydraulic system",
]


@dataclass(frozen=True)
class Scenario:
    """One labelled situation for one decision."""

    id: str
    decision: str
    kind: str
    category: str
    state: dict[str, Any]
    rule: str
    label: str
    rationale: str = field(default="")


def _turbine(
    turbine_id: int,
    days: float,
    status: str = "WARNING",
    probability: float = 0.6,
    park: str = OWN_PARK,
) -> dict[str, Any]:
    """A turbine row as the triage step hands it over."""
    return {
        "turbine_id": turbine_id,
        "park_id": park,
        "health_status": status,
        "days_to_failure": days,
        "fault_probability": probability,
    }


def _park(turbines: list[dict[str, Any]]) -> dict[str, Any]:
    """Decision 1 state for the own park."""
    return {
        "park_id": OWN_PARK,
        "conflict_window_days": CONFLICT_WINDOW_DAYS,
        "turbines": turbines,
    }


def _pairs(days: Sequence[Sequence[float]], statuses: str = "WC") -> list[list[dict[str, Any]]]:
    """Failing turbines with the given lead times, statuses cycling WARNING / CRITICAL."""
    names = {"W": "WARNING", "C": "CRITICAL"}
    out = []
    for group in days:
        out.append(
            [
                _turbine(10 + i, d, names[statuses[i % len(statuses)]], 0.5 + 0.1 * (i % 4))
                for i, d in enumerate(group)
            ]
        )
    return out


def _ml2_clear() -> list[tuple[str, list[dict[str, Any]]]]:
    """Clear decision-1 cases: (category, turbines)."""
    healthy = [_turbine(30, 8.0, "NORMAL", 0.02), _turbine(31, 8.0, "NORMAL", 0.03)]
    cases: list[tuple[str, list[dict[str, Any]]]] = []
    singles = [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 3.0, 1.2, 6.0]
    for i, d in enumerate(singles):
        status = "WARNING" if i % 2 == 0 else "CRITICAL"
        cases.append(("o_singura_turbina", [_turbine(10, d, status, 0.7)] + healthy[: i % 3]))
    same_day = [
        (1.2, 1.6),
        (2.1, 2.8),
        (3.3, 3.9),
        (4.0, 4.5),
        (5.2, 5.7),
        (0.3, 0.8),
        (6.1, 6.6),
        (2.0, 2.4),
        (1.0, 1.1),
        (4.4, 4.9),
    ]
    cases += [("doua_aceeasi_zi", t) for t in _pairs(same_day)]
    far = [
        (1.2, 4.5),
        (0.5, 5.5),
        (2.3, 6.8),
        (1.0, 6.0),
        (0.8, 3.9),
        (3.1, 6.9),
        (1.5, 5.1),
        (2.2, 5.9),
        (0.1, 4.2),
        (0.6, 7.0),
    ]
    cases += [("doua_departe", t) for t in _pairs(far)]
    crowd = [
        (1.2, 1.7, 5.0),
        (0.5, 3.6, 3.2),
        (2.2, 6.0, 2.9),
        (4.1, 0.5, 4.6),
        (6.3, 6.8, 1.0, 3.5),
        (0.2, 0.9, 4.4, 6.6),
        (3.0, 5.5, 3.4),
        (1.9, 1.4, 6.2),
    ]
    cases += [("mai_multe_doua_aceeasi_zi", t) for t in _pairs(crowd, "WCW")]
    spread = [
        (0.4, 3.5, 6.6),
        (0.9, 3.8, 6.9),
        (0.1, 3.2, 6.3),
        (0.6, 3.9, 6.1),
        (1.2, 4.4, 7.5),
        (0.5, 4.1, 7.2),
    ]
    cases += [("mai_multe_departe", t) for t in _pairs(spread, "CWW")]
    cases.append(("nicio_turbina_de_reparat", healthy))
    cases.append(("nicio_turbina_de_reparat", []))
    return cases


def _ml2_border() -> list[tuple[str, list[dict[str, Any]]]]:
    """Border decision-1 cases: (category, turbines); labels come from the labels file."""
    other = "wind_farm_b"
    cases: list[tuple[str, list[dict[str, Any]]]] = []
    cases += [
        ("fereastra_exact_1_zi", t)
        for t in _pairs([(1.3, 2.6), (3.0, 4.0), (0.2, 1.9), (5.5, 6.1)])
    ]
    cases += [
        ("fereastra_exact_2_zile", t)
        for t in _pairs([(1.3, 3.6), (2.0, 4.0), (0.5, 2.5), (4.9, 6.2)])
    ]
    cases += [
        ("rotunjire_in_jos", t)
        for t in _pairs([(1.95, 2.05), (1.0, 2.99), (0.99, 2.0), (2.9, 3.05)])
    ]
    cases += [
        ("alt_parc", [_turbine(10, 2.2), _turbine(40, 2.5, park=other)]),
        ("alt_parc", [_turbine(10, 4.1, "CRITICAL"), _turbine(41, 4.3, "CRITICAL", park=other)]),
        ("alt_parc", [_turbine(10, 1.1), _turbine(11, 5.2), _turbine(42, 1.4, park=other)]),
        ("alt_parc", [_turbine(10, 0.6), _turbine(11, 4.5), _turbine(43, 4.8, park=other)]),
        ("alt_parc", [_turbine(10, 3.2), _turbine(11, 3.7), _turbine(44, 3.4, park=other)]),
        ("alt_parc", [_turbine(45, 2.1, park=other), _turbine(46, 2.3, park=other)]),
    ]
    cases += [
        ("status_fara_reparatie", [_turbine(10, 2.1), _turbine(11, 2.4, "NORMAL", 0.3)]),
        ("status_fara_reparatie", [_turbine(10, 3.2), _turbine(11, 3.6, "WATCH", 0.6)]),
        ("status_fara_reparatie", [_turbine(10, 1.3, "CRITICAL"), _turbine(11, 1.8, "warning")]),
        ("status_fara_reparatie", [_turbine(10, 4.2, "WATCH"), _turbine(11, 4.5, "WATCH")]),
    ]
    cases += [
        ("fara_defect_prezis_8", [_turbine(10, 8.0), _turbine(11, 8.0)]),
        (
            "fara_defect_prezis_8",
            [_turbine(10, 8.0), _turbine(11, 8.0, "CRITICAL"), _turbine(12, 2.5)],
        ),
        ("fara_defect_prezis_8", [_turbine(10, 7.6), _turbine(11, 8.0)]),
        (
            "fara_defect_prezis_8",
            [_turbine(10, 8.0, "CRITICAL", 0.2), _turbine(11, 8.0, "WARNING", 0.1)],
        ),
    ]
    cases += [
        (
            "incredere_mica_ml1",
            [_turbine(10, 1.2, probability=0.03), _turbine(11, 1.7, probability=0.05)],
        ),
        (
            "incredere_mica_ml1",
            [_turbine(10, 3.1, probability=0.9), _turbine(11, 3.4, probability=0.04)],
        ),
        (
            "incredere_mica_ml1",
            [_turbine(10, 5.0, "CRITICAL", 0.08), _turbine(11, 5.9, "WARNING", 0.06)],
        ),
    ]
    cases += [
        ("deja_defect", [_turbine(10, -0.5, "CRITICAL", 0.95), _turbine(11, 0.4)]),
        ("deja_defect", [_turbine(10, 0.0, "CRITICAL", 0.95), _turbine(11, 3.0)]),
    ]
    cases += [
        ("multe_turbine", _pairs([(0.5, 2.6, 3.4, 5.5, 7.0)])[0]),
        ("multe_turbine", _pairs([(0.5, 2.5, 4.5, 6.5)])[0]),
        (
            "multe_turbine",
            [
                _turbine(10, 1.4),
                _turbine(11, 4.6, "CRITICAL"),
                _turbine(12, 1.8, "NORMAL", 0.2),
                _turbine(13, 4.2, "WATCH", 0.4),
                _turbine(47, 1.6, park=other),
                _turbine(48, 4.4, park=other),
            ],
        ),
    ]
    return cases


def _channel(
    turbine_id: int, status: str, days: float, probability: float, suspected: str | None = None
) -> dict[str, Any]:
    """Decision 2 state for one turbine."""
    return {
        "park_id": OWN_PARK,
        "turbine_id": turbine_id,
        "health_status": status,
        "days_to_failure": days,
        "fault_probability": probability,
        "suspected_failure": suspected or SUBSYSTEMS[turbine_id % len(SUBSYSTEMS)],
    }


def _channel_clear() -> list[tuple[str, dict[str, Any]]]:
    """Clear decision-2 cases: (category, state)."""
    cases: list[tuple[str, dict[str, Any]]] = []
    rows: list[tuple[str, str, list[tuple[float, float]]]] = [
        (
            "critic_aproape",
            "CRITICAL",
            [
                (0.5, 0.95),
                (0.8, 0.9),
                (1.0, 0.85),
                (1.2, 0.92),
                (1.5, 0.78),
                (1.8, 0.88),
                (0.3, 0.97),
                (1.1, 0.81),
            ],
        ),
        (
            "normal_fara_risc",
            "NORMAL",
            [
                (8.0, 0.01),
                (8.0, 0.02),
                (8.0, 0.03),
                (8.0, 0.05),
                (7.5, 0.08),
                (8.0, 0.1),
                (6.5, 0.12),
                (8.0, 0.15),
                (8.0, 0.2),
                (7.0, 0.04),
            ],
        ),
        (
            "warning_departe",
            "WARNING",
            [
                (3.5, 0.35),
                (4.0, 0.4),
                (4.5, 0.45),
                (5.0, 0.5),
                (5.5, 0.55),
                (6.0, 0.6),
                (6.5, 0.38),
                (3.8, 0.52),
            ],
        ),
        (
            "watch_departe",
            "WATCH",
            [(4.0, 0.15), (4.5, 0.2), (5.0, 0.25), (5.5, 0.3), (6.0, 0.35), (7.0, 0.4)],
        ),
        (
            "normal_defect_iminent",
            "NORMAL",
            [(0.5, 0.8), (0.7, 0.85), (0.9, 0.9), (1.1, 0.95), (1.3, 0.82), (1.5, 0.88)],
        ),
        ("normal_probabilitate_medie", "NORMAL", [(8.0, 0.4), (8.0, 0.45), (8.0, 0.5), (8.0, 0.6)]),
        ("warning_iminent", "WARNING", [(0.6, 0.9), (1.0, 0.85), (1.3, 0.8), (1.5, 0.92)]),
    ]
    n = 0
    for category, status, values in rows:
        for days, probability in values:
            n += 1
            cases.append((category, _channel(n, status, days, probability)))
    return cases


def _channel_border() -> list[tuple[str, dict[str, Any]]]:
    """Border decision-2 cases: (category, state); labels come from the labels file."""
    rows: list[tuple[str, str, float, float, str | None]] = [
        ("prag_070", "NORMAL", 5.0, 0.69, None),
        ("prag_070", "NORMAL", 5.0, 0.70, None),
        ("prag_070", "NORMAL", 5.0, 0.71, None),
        ("prag_070", "WARNING", 4.0, 0.69, None),
        ("prag_070", "WARNING", 4.0, 0.71, None),
        ("prag_030", "NORMAL", 8.0, 0.29, None),
        ("prag_030", "NORMAL", 8.0, 0.30, None),
        ("prag_030", "NORMAL", 8.0, 0.31, None),
        ("prag_2_zile", "NORMAL", 2.0, 0.5, None),
        ("prag_2_zile", "NORMAL", 2.01, 0.5, None),
        ("prag_2_zile", "NORMAL", 1.99, 0.5, None),
        ("prag_2_zile", "WATCH", 2.0, 0.25, None),
        ("prag_2_zile", "WATCH", 2.1, 0.25, None),
        ("watch_termen_scurt", "WATCH", 0.8, 0.35, None),
        ("watch_termen_scurt", "WATCH", 1.5, 0.2, None),
        ("watch_termen_scurt", "WATCH", 3.0, 0.69, None),
        ("incredere_mica_ml1", "NORMAL", 1.5, 0.05, None),
        ("incredere_mica_ml1", "NORMAL", 0.9, 0.08, None),
        ("incredere_mica_ml1", "NORMAL", 2.0, 0.03, None),
        ("incredere_mica_ml1", "NORMAL", 1.2, 0.10, None),
        ("incredere_mica_ml1", "NORMAL", 1.2, 0.12, None),
        ("incredere_mica_ml1", "WATCH", 1.0, 0.06, None),
        ("critic_semnale_contrare", "CRITICAL", 8.0, 0.05, None),
        ("critic_semnale_contrare", "CRITICAL", 6.5, 0.2, None),
        ("critic_semnale_contrare", "critical", 5.0, 0.3, None),
        ("deja_defect", "NORMAL", 0.0, 0.9, None),
        ("deja_defect", "NORMAL", -0.5, 0.6, None),
        ("status_necunoscut", "UNKNOWN", 8.0, 0.45, None),
        ("status_necunoscut", "", 8.0, 0.1, None),
        ("status_necunoscut", "OK", 8.0, 0.02, None),
        ("probabilitate_mare_fara_termen", "NORMAL", 8.0, 0.75, None),
        ("warning_probabilitate_mica", "WARNING", 8.0, 0.03, None),
        ("text_liber", "NORMAL", 8.0, 0.2, "smoke detected in the nacelle, fire risk"),
        ("text_liber", "NORMAL", 6.0, 0.25, "visible oil leak, growing since yesterday"),
    ]
    return [
        (category, _channel(100 + i, status, days, probability, suspected))
        for i, (category, status, days, probability, suspected) in enumerate(rows)
    ]


def load_border_labels(path: Path = BORDER_LABELS) -> dict[str, dict[str, str]]:
    """
    Read the hand-written labels of the border cases.

    :param path: JSON file mapping a scenario id to {"label", "rationale"}.

    :returns labels: The same mapping.
    """
    data: dict[str, dict[str, str]] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _build(
    decision: str,
    clear: list[tuple[str, Any]],
    border: list[tuple[str, Any]],
    rule: Any,
    labels: Mapping[str, Mapping[str, str]],
) -> list[Scenario]:
    """Number the cases, apply the rule, attach the labels."""
    prefix = "ml2" if decision == "ml2" else "ch"
    out = []
    for kind, cases in (("clar", clear), ("granita", border)):
        for i, (category, state) in enumerate(cases, start=1):
            sid = f"{prefix}-{'c' if kind == 'clar' else 'g'}-{i:02d}"
            baseline = rule(state)
            if kind == "clar":
                label, rationale = baseline, ""
            else:
                if sid not in labels:
                    raise KeyError(f"no label for border case {sid}")
                label, rationale = labels[sid]["label"], labels[sid]["rationale"]
            out.append(Scenario(sid, decision, kind, category, state, baseline, label, rationale))
    return out


def ml2_scenarios(labels: Mapping[str, Mapping[str, str]] | None = None) -> list[Scenario]:
    """
    Decision 1 scenarios.

    :param labels: Border labels; None reads `data/border_labels.json`.

    :returns scenarios: Clear cases first, then border cases.
    """
    labels = load_border_labels() if labels is None else labels
    clear = [(c, _park(t)) for c, t in _ml2_clear()]
    border = [(c, _park(t)) for c, t in _ml2_border()]
    return _build(
        "ml2",
        clear,
        border,
        lambda s: rule_ml2(s["park_id"], s["turbines"], s["conflict_window_days"]),
        labels,
    )


def channel_scenarios(labels: Mapping[str, Mapping[str, str]] | None = None) -> list[Scenario]:
    """
    Decision 2 scenarios.

    :param labels: Border labels; None reads `data/border_labels.json`.

    :returns scenarios: Clear cases first, then border cases.
    """
    labels = load_border_labels() if labels is None else labels
    return _build(
        "channel",
        _channel_clear(),
        _channel_border(),
        lambda s: rule_channel(s["health_status"], s["days_to_failure"], s["fault_probability"]),
        labels,
    )


def all_scenarios() -> list[Scenario]:
    """Both decisions, decision 1 first."""
    labels = load_border_labels()
    return ml2_scenarios(labels) + channel_scenarios(labels)


__all__ = [
    "Scenario",
    "ml2_scenarios",
    "channel_scenarios",
    "all_scenarios",
    "load_border_labels",
]
