"""
The lake handlers: raw → features → predictions → dispatch, and the dead-letter bucket.

Each handler is invoked with the S3 event the watcher would build. The model and the agent
are replaced by small fakes where the test is about the handler; one test chains the three
handlers with the real model.
"""

import csv
import io
import json
import logging
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from smarthack.clients.object_store import LocalObjectStore
from smarthack.schemas.lake import S3Event, object_created_event
from smarthack.services.lake_service import (
    HANDLERS,
    default_store,
    features_object_created_handler,
    is_lake_object,
    parse_csv,
    predictions_object_created_handler,
    raw_object_created_handler,
    triage_item,
)
from tests.conftest import requires_extra

#: A model that reads three features, enough to see what is selected and what is dropped.
FEATURES = ["sensor_0_avg", "thermal_lift_bearing_de", "rpm_deviation"]


@pytest.fixture
def store(tmp_path: Path) -> LocalObjectStore:
    """
    A lake rooted in the test's own folder.

    :param tmp_path: pytest's per-test folder.

    :returns store: An empty local store.
    """
    return LocalObjectStore(tmp_path)


def _csv(rows: Sequence[Mapping[str, object]]) -> bytes:
    """
    Write rows as a CSV file, the header taken from the first row.

    :param rows: The rows.

    :returns body: The file's bytes.
    """
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode()


def _read_csv(store: LocalObjectStore, bucket: str, key: str) -> list[dict[str, str]]:
    """
    Read a CSV object back.

    :param store: The lake.
    :param bucket: Its bucket.
    :param key: Its key.

    :returns rows: One dictionary per row.
    """
    return list(csv.DictReader(io.StringIO(store.get_object(bucket, key).decode())))


class _FakePredictor:
    """Stands in for `TurbineHealthPredictor`: turbine 7 is critical, 13 breaks, others fine."""

    feature_columns = FEATURES

    def __init__(self) -> None:
        """Start with no turbine seen."""
        self.seen: dict[int, dict[str, Any]] = {}

    def evaluate_features(
        self, record: dict[str, Any], asset_id: int = 0, horizon_days: int = 7
    ) -> dict[str, Any]:
        """
        Return the predictor's result shape.

        :param record: The turbine's features.
        :param asset_id: The turbine.
        :param horizon_days: Forecast days; unused.

        :returns result: What `evaluate_features` returns.
        :raises RuntimeError: For turbine 13.
        """
        self.seen[asset_id] = record
        if asset_id == 13:
            raise RuntimeError("model exploded")
        critical = asset_id == 7
        return {
            "status": "CRITICAL" if critical else "NORMAL",
            "health_score": 5.0 if critical else 95.0,
            "fault_probability": 0.95 if critical else 0.05,
            "estimated_days_to_failure": 1.5 if critical else None,
            "suspected_subsystem": "Gearbox" if critical else None,
            "subsystem_risks": {"Gearbox": 0.95} if critical else {},
            "daily_forecast": [],
            "recommended_action": "Stop the turbine." if critical else "Nothing.",
            "anomalous_sensors": [],
            "records_evaluated": 1,
        }


# --- raw → features -----------------------------------------------------------------------


@requires_extra("wind")
def test_raw_keeps_only_the_model_features_and_the_latest_row(
    store: LocalObjectStore, caplog: pytest.LogCaptureFixture
) -> None:
    """A file that already has the features: other columns go, each turbine's last row stays."""
    rows = [
        {"time_stamp": "2026-11-08T10:10", "asset_id": 7, "sensor_0_avg": 2, "noise": 1,
         "thermal_lift_bearing_de": 20, "rpm_deviation": 3, "park_id": "p1"},
        {"time_stamp": "2026-11-08T10:00", "asset_id": 7, "sensor_0_avg": 1, "noise": 1,
         "thermal_lift_bearing_de": 10, "rpm_deviation": 3, "park_id": "p1"},
        {"time_stamp": "2026-11-08T10:00", "asset_id": 3, "sensor_0_avg": 9, "noise": 1,
         "thermal_lift_bearing_de": 30, "rpm_deviation": "", "park_id": "p1"},
    ]  # fmt: skip
    store.put_object("raw", "2026-11-08/park 1.csv", _csv(rows))

    with caplog.at_level(logging.INFO):
        report = raw_object_created_handler(
            object_created_event("raw", "2026-11-08/park 1.csv"),
            None,
            store=store,
            feature_columns=FEATURES,
        )

    assert report["objects"] == [
        {
            "bucket": "raw",
            "key": "2026-11-08/park 1.csv",
            "status": "written",
            "rows": 2,
            "columns": 6,
            "output": "s3://features/2026-11-08/park 1.csv",
            "error": None,
        }
    ]
    written = _read_csv(store, "features", "2026-11-08/park 1.csv")
    assert list(written[0]) == ["turbine_id", "park_id", "as_of", *FEATURES]
    assert [(r["turbine_id"], r["as_of"], r["sensor_0_avg"]) for r in written] == [
        ("3", "2026-11-08T10:00", "9.0"),
        ("7", "2026-11-08T10:10", "2.0"),
    ]
    assert written[0]["rpm_deviation"] == ""
    assert "New file s3://raw/2026-11-08/park 1.csv" in caplog.text
    assert "3 rows x 7 columns" in caplog.text


@requires_extra("wind")
def test_raw_derives_the_features_from_raw_sensors(store: LocalObjectStore) -> None:
    """Raw SCADA sensors are turned into the real model's features, in the model's order."""
    from smarthack.jobs.lake_job import sample_csv
    from smarthack.maintenance.agent_tool import load_predictor

    model = load_predictor().feature_columns
    store.put_object("raw", "scada.csv", sample_csv({4: "normal", 5: "gearbox_wear"}, hours=6))

    report = raw_object_created_handler(
        object_created_event("raw", "scada.csv"), None, store=store, feature_columns=model
    )

    assert report["objects"][0]["status"] == "written"
    written = _read_csv(store, "features", "scada.csv")
    assert [r["turbine_id"] for r in written] == ["4", "5"]
    assert list(written[0]) == ["turbine_id", "as_of", *model]
    assert "scenario" not in written[0]


@requires_extra("wind")
def test_raw_without_what_the_model_needs_goes_to_failed(
    store: LocalObjectStore, caplog: pytest.LogCaptureFixture
) -> None:
    """Neither the features nor the raw sensors: dead-letter, with what is missing named."""
    body = b"turbine_id,gearbox_oil_temp\n7,61.5\n"
    store.put_object("raw", "short.csv", body)

    report = raw_object_created_handler(
        object_created_event("raw", "short.csv"), None, store=store, feature_columns=FEATURES
    )

    assert report["objects"][0]["status"] == "failed"
    assert "missing features sensor_0_avg" in report["objects"][0]["error"]
    assert store.get_object("failed", "short.csv") == body
    assert "could not be processed" in caplog.text


@requires_extra("wind")
def test_raw_without_a_turbine_id_goes_to_failed(store: LocalObjectStore) -> None:
    """Rows that name no turbine cannot be scored."""
    store.put_object("raw", "anonymous.csv", b"sensor_0_avg\n1\n")

    report = raw_object_created_handler(
        object_created_event("raw", "anonymous.csv"), None, store=store, feature_columns=FEATURES
    )

    assert "no turbine id column" in report["objects"][0]["error"]


@requires_extra("wind")
def test_only_the_first_rows_of_a_long_file_are_printed(
    store: LocalObjectStore, caplog: pytest.LogCaptureFixture
) -> None:
    """A long file is summarised: its row count, and a preview of the first rows."""
    rows = [{"turbine_id": i, **{name: i for name in FEATURES}} for i in range(100)]
    store.put_object("raw", "long.csv", _csv(rows))

    with caplog.at_level(logging.INFO):
        raw_object_created_handler(
            object_created_event("raw", "long.csv"), None, store=store, feature_columns=FEATURES
        )

    assert "100 rows x 4 columns (first 5 shown)" in caplog.text
    assert '"turbine_id": "4"' in caplog.text and '"turbine_id": "5"' not in caplog.text


def test_an_invalid_file_is_copied_to_the_failed_bucket(
    store: LocalObjectStore, caplog: pytest.LogCaptureFixture
) -> None:
    """A file that is not CSV goes to `failed` under the same key, and the error is logged."""
    store.put_object("raw", "bad.csv", b"a,a\n1,2\n")

    report = raw_object_created_handler(object_created_event("raw", "bad.csv"), None, store=store)

    assert report["objects"][0]["status"] == "failed"
    assert "duplicated columns: a" in caplog.text
    assert store.get_object("failed", "bad.csv") == b"a,a\n1,2\n"


def test_a_missing_object_is_reported_not_raised(store: LocalObjectStore) -> None:
    """An event for an object that is already gone fails that record only."""
    report = raw_object_created_handler(object_created_event("raw", "gone.csv"), None, store=store)

    assert report["objects"][0]["status"] == "failed"


def test_records_that_are_not_new_files_of_the_handler_type_are_skipped(
    store: LocalObjectStore,
) -> None:
    """A deletion, an object of another type, or JSON in `raw` is not processed."""
    deleted = object_created_event("raw", "a.csv")
    deleted["Records"][0]["eventName"] = "ObjectRemoved:Delete"
    events = (
        deleted,
        object_created_event("raw", "notes.txt"),
        object_created_event("raw", "a.json"),
    )

    statuses = [
        raw_object_created_handler(event, None, store=store)["objects"][0]["status"]
        for event in events
    ]

    assert statuses == ["skipped", "skipped", "skipped"]


# --- features → predictions ---------------------------------------------------------------


@requires_extra("wind")
def test_features_are_scored_and_written_as_predictions(store: LocalObjectStore) -> None:
    """Every turbine gets an assessment; one that fails is recorded, not fatal."""
    rows = [
        {"turbine_id": 7, "park_id": "p1", "as_of": "2026-11-08T10:10", "sensor_0_avg": 1,
         "thermal_lift_bearing_de": 50, "rpm_deviation": ""},
        {"turbine_id": 13, "park_id": "", "as_of": "", "sensor_0_avg": 1,
         "thermal_lift_bearing_de": 1, "rpm_deviation": 1},
        {"turbine_id": 3, "park_id": "", "as_of": "", "sensor_0_avg": 1,
         "thermal_lift_bearing_de": 1, "rpm_deviation": 1},
    ]  # fmt: skip
    store.put_object("features", "2026-11-08/park.csv", _csv(rows))

    model = _FakePredictor()

    report = features_object_created_handler(
        object_created_event("features", "2026-11-08/park.csv"),
        None,
        store=store,
        predictor=model,  # type: ignore[arg-type]
    )

    assert report["objects"][0]["status"] == "written"
    assert report["objects"][0]["output"] == "s3://predictions/2026-11-08/park.json"
    document = json.loads(store.get_object("predictions", "2026-11-08/park.json"))
    assert document["source"] == "s3://features/2026-11-08/park.csv"
    first, second = document["predictions"]
    assert (first["turbine_id"], first["park_id"], first["health_status"]) == (7, "p1", "CRITICAL")
    assert model.seen[7] == {
        "sensor_0_avg": 1.0,
        "thermal_lift_bearing_de": 50.0,
        "rpm_deviation": None,
    }
    assert (second["turbine_id"], second["park_id"], second["as_of"]) == (3, None, None)
    assert document["errors"] == [{"line": 3, "turbine_id": 13, "error": "model exploded"}]


@requires_extra("wind")
def test_a_features_file_that_does_not_match_the_model_goes_to_failed(
    store: LocalObjectStore,
) -> None:
    """A feature the model reads is missing, typically after the model changed."""
    store.put_object("features", "old.csv", b"turbine_id,sensor_0_avg\n7,1\n")

    report = features_object_created_handler(
        object_created_event("features", "old.csv"),
        None,
        store=store,
        predictor=_FakePredictor(),  # type: ignore[arg-type]
    )

    assert (
        "does not match the model: missing thermal_lift_bearing_de" in report["objects"][0]["error"]
    )
    assert store.get_object("failed", "old.csv").startswith(b"turbine_id")


@requires_extra("wind")
def test_a_features_file_where_no_turbine_scores_goes_to_failed(store: LocalObjectStore) -> None:
    """Nothing to hand on: the file is dead-lettered rather than an empty document written."""
    store.put_object(
        "features", "broken.csv", _csv([{"turbine_id": 13, **{name: 1 for name in FEATURES}}])
    )

    report = features_object_created_handler(
        object_created_event("features", "broken.csv"),
        None,
        store=store,
        predictor=_FakePredictor(),  # type: ignore[arg-type]
    )

    assert report["objects"][0]["status"] == "failed"
    assert "no turbine could be scored" in report["objects"][0]["error"]


# --- predictions → dispatch ---------------------------------------------------------------


def _prediction(turbine_id: int, status: str, park_id: str | None = None) -> dict[str, Any]:
    """
    One entry of a predictions file.

    :param turbine_id: The turbine.
    :param status: Its health status.
    :param park_id: Its park, or None to leave it to the lookup.

    :returns entry: What the features handler writes for one turbine.
    """
    failing = status in ("WARNING", "CRITICAL")
    return {
        "turbine_id": turbine_id,
        "park_id": park_id,
        "health_status": status,
        "fault_probability": 0.9 if failing else 0.1,
        "estimated_days_to_failure": 2.0 if failing else None,
        "suspected_subsystem": "Gearbox" if failing else None,
        "subsystem_risks": {},
        "daily_forecast": [],
        "recommended_action": "Inspect.",
    }


class _FakeAgent:
    """Records the parks it is run for; park `boom` raises."""

    def __init__(self) -> None:
        """Start with no runs."""
        self.runs: list[tuple[str, list[dict[str, Any]]]] = []

    def __call__(self, park_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Pretend to run the dispatch agent.

        :param park_id: The park.
        :param items: Its triage items.

        :returns state: A final state with the keys the dispatch file keeps, and one it drops.
        :raises RuntimeError: For park `boom`.
        """
        if park_id == "boom":
            raise RuntimeError("agent exploded")
        self.runs.append((park_id, items))
        return {"audit_summary": f"swept {park_id}", "alert_decisions": [], "triage_items": items}


def test_the_agent_runs_once_per_park_with_a_turbine_to_repair(store: LocalObjectStore) -> None:
    """Parks come from the file or the lookup; a healthy park, and an unknown turbine, get no run."""
    predictions = [
        _prediction(1, "CRITICAL", "a"),
        _prediction(2, "NORMAL", "a"),
        _prediction(10, "WARNING"),
        _prediction(20, "NORMAL"),
        _prediction(99, "CRITICAL"),
        _prediction(30, "CRITICAL", "boom"),
    ]
    store.put_object("predictions", "x/run.json", json.dumps({"predictions": predictions}).encode())
    agent = _FakeAgent()
    asked: list[list[int]] = []

    def lookup(ids: Sequence[int]) -> dict[int, str]:
        """Know turbines 10 and 20 only."""
        asked.append(list(ids))
        return {10: "b", 20: "c"}

    report = predictions_object_created_handler(
        object_created_event("predictions", "x/run.json"),
        None,
        store=store,
        run_agent=agent,
        park_lookup=lookup,
    )

    assert report["objects"][0]["output"] == "s3://dispatch/x/run.json"
    assert asked == [[10, 20, 99]]
    assert [(park, [i["turbine_id"] for i in items]) for park, items in agent.runs] == [
        ("a", [1, 2]),
        ("b", [10]),
    ]
    document = json.loads(store.get_object("dispatch", "x/run.json"))
    parks = document["parks"]
    assert parks["a"] == {
        "turbines": 2,
        "needs_repair": [1],
        "status": "dispatched",
        "audit_summary": "swept a",
        "alert_decisions": [],
    }
    assert parks["c"]["status"] == "no_repair_needed"
    assert parks["boom"] == {
        "turbines": 1,
        "needs_repair": [30],
        "status": "failed",
        "error": "agent exploded",
    }
    assert document["unassigned_turbines"] == [99]


@pytest.mark.parametrize(
    "body", [b"not json", b'{"predictions": 3}', b'{"predictions": [{"park_id": "a"}]}']
)
def test_a_malformed_predictions_file_goes_to_failed(store: LocalObjectStore, body: bytes) -> None:
    """Not JSON, no list, or an entry without a turbine: dead-letter, and no agent run."""
    store.put_object("predictions", "bad.json", body)
    agent = _FakeAgent()

    report = predictions_object_created_handler(
        object_created_event("predictions", "bad.json"),
        None,
        store=store,
        run_agent=agent,
        park_lookup=lambda ids: {},
    )

    assert report["objects"][0]["status"] == "failed"
    assert agent.runs == []
    assert store.get_object("failed", "bad.json") == body


def test_triage_item_reads_the_assessment_as_the_agent_expects() -> None:
    """A repair is needed from WARNING up; no predicted failure means a lead time past the week."""
    critical = triage_item(_prediction(1, "CRITICAL"), "a")
    healthy = triage_item(_prediction(2, "normal"), "a")

    assert critical["needs_repair"] is True
    assert (critical["days_to_failure"], critical["suspected_failure"]) == (2.0, "Gearbox")
    assert healthy["needs_repair"] is False
    assert (healthy["health_status"], healthy["days_to_failure"]) == ("NORMAL", 8.0)
    assert healthy["suspected_failure"] == "General Drivetrain"


# --- the chain ----------------------------------------------------------------------------


@requires_extra("wind")
def test_the_three_handlers_chain_from_raw_telemetry_to_a_dispatch_plan(
    store: LocalObjectStore,
) -> None:
    """Simulated SCADA through the real model: the failing turbine reaches the agent's park."""
    from smarthack.jobs.lake_job import sample_csv

    store.put_object("raw", "chain.csv", sample_csv({0: "normal", 1: "bearing_overheating"}, 24))
    agent = _FakeAgent()

    raw_object_created_handler(object_created_event("raw", "chain.csv"), None, store=store)
    features_object_created_handler(
        object_created_event("features", "chain.csv"), None, store=store
    )
    predictions_object_created_handler(
        object_created_event("predictions", "chain.json"), None, store=store, run_agent=agent
    )

    [(park_id, items)] = agent.runs
    assert park_id == "wind_farm_a"
    assert {i["turbine_id"]: i["needs_repair"] for i in items} == {0: False, 1: True}
    document = json.loads(store.get_object("dispatch", "chain.json"))
    assert document["parks"]["wind_farm_a"]["needs_repair"] == [1]


# --- shared -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key, expected",
    [
        ("a.csv", True),
        ("2026/A.CSV", True),
        ("a.json", True),
        (".a.csv.0f3c.tmp", False),
        ("a.csv.tmp", False),
        (".DS_Store", False),
        (".hidden/a.csv", False),
        ("a.parquet", False),
    ],
)
def test_is_lake_object(key: str, expected: bool) -> None:
    """Temporary, hidden and unhandled files are left alone."""
    assert is_lake_object(key) is expected


def test_parse_csv_accepts_a_byte_order_mark_and_short_rows() -> None:
    """Excel's UTF-8 BOM is dropped, and a missing trailing value reads as empty."""
    columns, rows = parse_csv("﻿a,b\n1\n".encode("utf-8"))

    assert columns == ["a", "b"]
    assert rows == [{"a": "1", "b": ""}]


@pytest.mark.parametrize(
    "body, message",
    [(b"", "no header"), (b"\xff\xfe", "not UTF-8"), (b"a\n1,2\n", "more values")],
)
def test_parse_csv_rejects_what_is_not_a_table(body: bytes, message: str) -> None:
    """An empty file, binary data, or a row wider than the header is refused."""
    with pytest.raises(ValueError, match=message):
        parse_csv(body)


def test_the_event_is_the_one_s3_sends() -> None:
    """The key is URL-encoded like S3 does, and decoded back when read."""
    event = object_created_event("raw", "2026-11-08/turbine 7.csv", size=12)

    record = S3Event.model_validate(event).records[0]

    assert event["Records"][0]["s3"]["object"]["key"] == "2026-11-08/turbine+7.csv"
    assert record.s3.object.decoded_key == "2026-11-08/turbine 7.csv"
    assert record.is_object_created and record.s3.object.size == 12


def test_each_bucket_triggers_the_next_step_of_the_pipeline() -> None:
    """The notification setup: raw, features and predictions each have their handler."""
    assert HANDLERS == {
        "raw": raw_object_created_handler,
        "features": features_object_created_handler,
        "predictions": predictions_object_created_handler,
    }


def test_the_default_store_is_rooted_at_the_configured_lake(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`LAKE_DIR` decides where the handlers read from."""
    monkeypatch.setenv("LAKE_DIR", str(tmp_path))

    assert default_store().root == tmp_path
