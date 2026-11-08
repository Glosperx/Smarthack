"""
# Data lake handlers

The functions the local lake invokes when an object lands in a bucket: the stand-ins for
AWS Lambda functions. Each has the Lambda signature, `handler(event, context)`, takes the
S3 event of `smarthack.schemas.lake` and returns a JSON-ready report, so it can be deployed
to a real Lambda behind a real S3 bucket with only its store replaced.

Three handlers make one pipeline. Each writes into the next bucket, and that write is the
event that starts the next handler, as an S3 notification would:

```
raw/*.csv ──raw_object_created_handler──▶ features/*.csv           only the model's features
features/*.csv ──features_object_created_handler──▶ predictions/*.json   the model's verdict
predictions/*.json ──predictions_object_created_handler──▶ dispatch/*.json   the agent's plan
```

- **raw → features** logs the new file, then keeps only what the maintenance model reads: one
  row per turbine with the model's features, selected or derived from raw sensors
  (`smarthack.maintenance.model_input`). The feature list is the model's own
  (`fault_features.json`), so a new model changes the selection without a code change.
- **features → predictions** scores every turbine with the maintenance model and writes its
  assessment: status, fault probability, lead time, subsystem, 7-day forecast.
- **predictions → dispatch** turns the assessments into triage items and runs the LangGraph
  dispatch agent once per park that has a turbine to repair: overlap check, power model,
  repair plan, crews and alerts, with the local decision model where it is switched on.

A file that cannot be processed is copied to the `failed` bucket under the same key, the
dead-letter queue of the pipeline, and the handler carries on with the next record. One
turbine whose scoring fails, or one park whose agent run fails, is recorded in the output and
does not stop the others.

The model is loaded once per process and kept, as a warm Lambda keeps it: restart the watcher
after replacing the model files. pandas and the model libraries come with the `wind` extra
and are imported inside the handlers, so the module itself imports on a core install.

`HANDLERS` maps a bucket to the handler its new objects trigger; the watcher reads it.

The following can be imported from this module:
- `HANDLERS`
- `LakeHandler`
- `default_store`
- `features_object_created_handler`
- `is_lake_object`
- `parse_csv`
- `predictions_object_created_handler`
- `raw_object_created_handler`
- `triage_item`
"""

from collections.abc import Callable, Mapping, Sequence
import csv
from datetime import datetime, timezone
import functools
import io
import json
import logging
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from smarthack import config
from smarthack.clients.object_store import LocalObjectStore, ObjectStore
from smarthack.constants import (
    LAKE_DISPATCH_BUCKET,
    LAKE_FAILED_BUCKET,
    LAKE_FEATURES_BUCKET,
    LAKE_OBJECT_SUFFIXES,
    LAKE_PREDICTIONS_BUCKET,
    LAKE_PREVIEW_ROWS,
    LAKE_RAW_BUCKET,
    LAKE_TEMP_SUFFIX,
    TURBINE_TABLE,
    WIND_FORECAST_DAYS,
)
from smarthack.schemas.dispatch import TurbineHealthTriage
from smarthack.schemas.lake import LakeObjectReport, LakeRunReport, S3Event

if TYPE_CHECKING:
    from smarthack.maintenance.predictor import TurbineHealthPredictor

logger = logging.getLogger(__name__)

#: A lake handler: the Lambda signature, plus its dependencies as optional keywords.
LakeHandler = Callable[..., dict[str, Any]]

#: What processing one object returns: the URI written, its rows and its columns.
_Written = tuple[str, int, int]

#: Health states that send a crew, as the agent's triage reads them.
_REPAIR_STATUSES = frozenset({"WARNING", "CRITICAL"})

#: The lead time given to a turbine the model expects to last the forecast: past the horizon,
#: so it is never a failure day. The dispatch agent reads the same value as "no failure".
_NO_FAILURE_LEAD_DAYS = float(WIND_FORECAST_DAYS + 1)

#: The parts of the agent's final state kept in the dispatch file. Keys an older graph does
#: not produce (the decision model's records) are simply absent.
_DISPATCH_KEYS = (
    "audit_summary",
    "alert_decisions",
    "crew_assignments",
    "repair_schedule",
    "repair_plan_choice",
    "channel_decisions",
    "decision_model_down",
    "power_model_invoked",
    "power_evaluations",
)


def default_store() -> LocalObjectStore:
    """
    Return the store of the local lake at the configured root.

    :returns store: A `LocalObjectStore` on `config.lake_dir()`.
    """
    return LocalObjectStore(config.lake_dir())


def is_lake_object(key: str) -> bool:
    """
    Report whether an object key is one the handlers should process.

    Temporary files of an atomic write, hidden files (`.DS_Store` on macOS) and file types
    the pipeline does not read are left alone.

    :param key: Object key, such as `2026-11-08/turbine_7.csv`.

    :returns process: True for a finished file of a handled type.
    """
    path = PurePosixPath(key)
    if any(part.startswith(".") for part in path.parts):
        return False
    if path.name.endswith(LAKE_TEMP_SUFFIX):
        return False
    return path.suffix.lower() in LAKE_OBJECT_SUFFIXES


def parse_csv(body: bytes) -> tuple[list[str], list[dict[str, str]]]:
    """
    Read a CSV file with a header line into its columns and rows.

    Values stay strings: typing them is the job of the step that feeds the model, which knows
    each column's type.

    :param body: The file's bytes, UTF-8, with or without a byte-order mark.

    :returns table: The column names and one dictionary per row.
    :raises ValueError: When the file is not UTF-8, has no header, repeats a column name or
        has a row with more values than columns.
    """
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"not UTF-8 text: {exc}") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    columns = list(reader.fieldnames or [])
    if not columns:
        raise ValueError("no header line")
    duplicated = sorted({name for name in columns if columns.count(name) > 1})
    if duplicated:
        raise ValueError(f"duplicated columns: {', '.join(duplicated)}")
    rows: list[dict[str, str]] = []
    for line_number, row in enumerate(reader, start=2):
        if None in row:
            raise ValueError(f"line {line_number} has more values than the header has columns")
        rows.append({name: value or "" for name, value in row.items()})
    return columns, rows


def _send_to_failed(store: ObjectStore, key: str, body: bytes) -> None:
    """
    Copy a file that could not be processed to the failed bucket, logging any failure.

    :param store: The lake's store.
    :param key: The object's key, kept unchanged in the failed bucket.
    :param body: The object's bytes.
    """
    try:
        store.put_object(LAKE_FAILED_BUCKET, key, body)
    except OSError:
        logger.exception("could not copy %s to the %s bucket", key, LAKE_FAILED_BUCKET)


def _handle(
    event: dict[str, Any],
    store: ObjectStore,
    handler: str,
    suffix: str,
    process: Callable[[str, bytes], _Written],
) -> dict[str, Any]:
    """
    Run one processing step over every record of an S3 event: the loop all handlers share.

    :param event: An S3 `ObjectCreated` event.
    :param store: Where objects are read from and written to.
    :param handler: The handler's name, for the report.
    :param suffix: The one file type this handler reads, such as `.csv`.
    :param process: Turns an object's key and bytes into what was written; raises
        `ValueError` (or `csv.Error`, `OSError`) when the object cannot be processed.

    :returns report: A `LakeRunReport` as a dictionary, one entry per record.
    """
    parsed = S3Event.model_validate(event)
    report = LakeRunReport(handler=handler)
    for record in parsed.records:
        bucket, key = record.s3.bucket.name, record.s3.object.decoded_key
        handled = is_lake_object(key) and key.lower().endswith(suffix)
        if not record.is_object_created or not handled:
            report.objects.append(LakeObjectReport(bucket=bucket, key=key, status="skipped"))
            continue
        try:
            body = store.get_object(bucket, key)
        except (OSError, ValueError) as exc:
            logger.error("s3://%s/%s could not be read: %s", bucket, key, exc)
            report.objects.append(
                LakeObjectReport(bucket=bucket, key=key, status="failed", error=str(exc))
            )
            continue
        try:
            output, rows, columns = process(key, body)
        except (ValueError, csv.Error, OSError) as exc:
            logger.error("s3://%s/%s could not be processed: %s", bucket, key, exc)
            _send_to_failed(store, key, body)
            report.objects.append(
                LakeObjectReport(bucket=bucket, key=key, status="failed", error=str(exc))
            )
            continue
        report.objects.append(
            LakeObjectReport(
                bucket=bucket,
                key=key,
                status="written",
                rows=rows,
                columns=columns,
                output=output,
            )
        )
    return report.model_dump()


def _json_key(key: str) -> str:
    """
    Return the key of the JSON object written for an input object.

    :param key: The input's key, such as `2026-11-08/park_3.csv`.

    :returns key: The same path with a `.json` suffix.
    """
    return PurePosixPath(key).with_suffix(".json").as_posix()


def _to_json(document: Mapping[str, Any]) -> bytes:
    """
    Serialise a handler's output, turning numpy scalars and dates into plain JSON values.

    :param document: The output document.

    :returns body: Indented UTF-8 JSON.
    """

    def plain(value: Any) -> Any:
        """Turn what `json` cannot write into something it can."""
        item = getattr(value, "item", None)
        return item() if callable(item) else str(value)

    return json.dumps(document, indent=2, ensure_ascii=False, default=plain).encode("utf-8")


@functools.lru_cache(maxsize=1)
def _default_predictor() -> "TurbineHealthPredictor":
    """
    Load the maintenance model once per process, as a warm Lambda keeps it.

    :returns predictor: The loaded `TurbineHealthPredictor`.
    """
    # Imported here: the model needs pandas and its libraries, from the `wind` extra.
    from smarthack.maintenance.agent_tool import load_predictor

    return load_predictor()


def raw_object_created_handler(
    event: dict[str, Any],
    context: object | None = None,
    *,
    store: ObjectStore | None = None,
    feature_columns: Sequence[str] | None = None,
) -> dict[str, Any]:
    """
    Cut every new raw CSV file down to the model's input and write it to the features bucket.

    The file is logged first: its name, shape and first rows. Then one row per turbine is
    kept, holding only the model's features, selected or derived from raw sensors.

    :param event: An S3 `ObjectCreated` event, as `object_created_event` builds it.
    :param context: The Lambda context object; unused, kept for the Lambda signature.
    :param store: Where objects are read and written. Defaults to the local lake.
    :param feature_columns: The features the model reads. Defaults to the loaded model's.

    :returns report: A `LakeRunReport` as a dictionary, one entry per record.
    """
    lake = store or default_store()

    def process(key: str, body: bytes) -> _Written:
        """Log the raw file, select the model's features, write them."""
        columns, rows = parse_csv(body)
        preview = json.dumps(rows[:LAKE_PREVIEW_ROWS], indent=2, ensure_ascii=False)
        shown = "" if len(rows) <= LAKE_PREVIEW_ROWS else f" (first {LAKE_PREVIEW_ROWS} shown)"
        logger.info(
            "New file s3://%s/%s: %d bytes, %d rows x %d columns%s\n%s",
            LAKE_RAW_BUCKET,
            key,
            len(body),
            len(rows),
            len(columns),
            shown,
            preview,
        )
        # Imported here: deriving features needs pandas, from the `wind` extra.
        from smarthack.maintenance.model_input import build_model_input

        wanted = list(feature_columns or _default_predictor().feature_columns)
        table = build_model_input(columns, rows, wanted)
        lake.put_object(LAKE_FEATURES_BUCKET, key, table.to_csv(index=False).encode("utf-8"))
        output = f"s3://{LAKE_FEATURES_BUCKET}/{key}"
        logger.info(
            "s3://%s/%s: %d model features for %d turbines -> %s",
            LAKE_RAW_BUCKET,
            key,
            len(wanted),
            len(table),
            output,
        )
        return output, len(table), len(table.columns)

    return _handle(event, lake, "raw_object_created_handler", ".csv", process)


def _number(value: str) -> float | None:
    """
    Read one feature value of a features file.

    :param value: The CSV cell.

    :returns number: The value, or None for an empty or unreadable cell (the model's
        missing value).
    """
    try:
        return float(value) if value.strip() else None
    except ValueError:
        return None


def features_object_created_handler(
    event: dict[str, Any],
    context: object | None = None,
    *,
    store: ObjectStore | None = None,
    predictor: "TurbineHealthPredictor | None" = None,
) -> dict[str, Any]:
    """
    Score every turbine of a new features file and write the assessments to `predictions`.

    :param event: An S3 `ObjectCreated` event for the features bucket.
    :param context: The Lambda context object; unused, kept for the Lambda signature.
    :param store: Where objects are read and written. Defaults to the local lake.
    :param predictor: The maintenance model. Defaults to the one loaded for this process.

    :returns report: A `LakeRunReport` as a dictionary, one entry per record.
    """
    lake = store or default_store()

    def process(key: str, body: bytes) -> _Written:
        """Score each row with the model, write one JSON document of assessments."""
        columns, rows = parse_csv(body)
        model = predictor or _default_predictor()
        missing = [name for name in model.feature_columns if name not in columns]
        if missing:
            raise ValueError(f"the file does not match the model: missing {', '.join(missing)}")
        if not rows:
            raise ValueError("the file has no rows")
        # Imported here: the model needs pandas and its libraries, from the `wind` extra.
        from smarthack.maintenance.agent_tool import assess_turbine_health

        predictions: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for line, row in enumerate(rows, start=2):
            try:
                turbine_id = int(float(row.get("turbine_id", "")))
            except ValueError:
                errors.append({"line": line, "error": "no turbine_id"})
                continue
            record = {name: _number(row[name]) for name in model.feature_columns}
            try:
                result = assess_turbine_health(
                    asset_id=turbine_id, features_record=record, predictor=model
                )
            except Exception as exc:  # one turbine must not stop the others
                logger.exception("turbine %s of s3://features/%s failed", turbine_id, key)
                errors.append({"line": line, "turbine_id": turbine_id, "error": str(exc)})
                continue
            predictions.append(
                {
                    **result,
                    "turbine_id": turbine_id,
                    "park_id": row.get("park_id") or None,
                    "as_of": row.get("as_of") or None,
                }
            )
        if not predictions:
            raise ValueError(f"no turbine could be scored: {errors}")
        document = {
            "source": f"s3://{LAKE_FEATURES_BUCKET}/{key}",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model_features": len(model.feature_columns),
            "predictions": predictions,
            "errors": errors,
        }
        out_key = _json_key(key)
        lake.put_object(LAKE_PREDICTIONS_BUCKET, out_key, _to_json(document))
        by_status: dict[str, int] = {}
        for item in predictions:
            status = str(item.get("health_status"))
            by_status[status] = by_status.get(status, 0) + 1
        output = f"s3://{LAKE_PREDICTIONS_BUCKET}/{out_key}"
        logger.info(
            "s3://%s/%s: %d turbines scored %s, %d failed -> %s",
            LAKE_FEATURES_BUCKET,
            key,
            len(predictions),
            by_status,
            len(errors),
            output,
        )
        return output, len(predictions), len(model.feature_columns)

    return _handle(event, lake, "features_object_created_handler", ".csv", process)


def triage_item(prediction: Mapping[str, Any], park_id: str) -> dict[str, Any]:
    """
    Turn one model assessment into the triage item the dispatch agent works from.

    :param prediction: One entry of a predictions file: `assess_turbine_health`'s result with
        `turbine_id`.
    :param park_id: The park of the turbine.

    :returns item: A `TurbineHealthTriage` as a plain dictionary; a turbine without a
        predicted failure gets a lead time past the forecast horizon.
    """
    status = str(prediction.get("health_status") or "NORMAL").upper()
    days = prediction.get("estimated_days_to_failure")
    return TurbineHealthTriage(
        turbine_id=int(prediction["turbine_id"]),
        park_id=str(park_id),
        health_status=status,
        fault_probability=float(prediction.get("fault_probability") or 0.0),
        days_to_failure=float(days) if days is not None else _NO_FAILURE_LEAD_DAYS,
        suspected_failure=str(prediction.get("suspected_subsystem") or "General Drivetrain"),
        subsystem_risks=dict(prediction.get("subsystem_risks") or {}),
        daily_forecast=list(prediction.get("daily_forecast") or []),
        recommended_action=str(prediction.get("recommended_action") or "No action needed."),
        needs_repair=status in _REPAIR_STATUSES,
    ).model_dump()


def _lookup_parks(turbine_ids: Sequence[int]) -> dict[int, str]:
    """
    Find the park of each turbine where the agent's data lives: Supabase or the seed fleet.

    :param turbine_ids: Turbines a predictions file did not give a park for.

    :returns parks: Park id by turbine id; a turbine that is not registered is left out, and
        so is every turbine when the database cannot be read.
    """
    if not turbine_ids:
        return {}
    if config.agent_data_source() == "supabase":
        import httpx

        from smarthack.clients.supabase import select_rows

        ids = ",".join(str(turbine_id) for turbine_id in sorted(set(turbine_ids)))
        try:
            rows = select_rows(TURBINE_TABLE, {"select": "id,park_id", "id": f"in.({ids})"})
        except (httpx.HTTPError, RuntimeError) as exc:
            logger.warning("could not read the parks of turbines %s: %s", ids, exc)
            return {}
        return {int(r["id"]): str(r["park_id"]) for r in rows if r.get("park_id") is not None}
    # Imported here: the seed fleet scores turbines with the model, from the `wind` extra.
    from smarthack.services.fleet_service import get_default_fleet_service

    fleet = get_default_fleet_service()
    return {
        turbine_id: info.park_id
        for turbine_id in turbine_ids
        if (info := fleet.get_turbine_info(turbine_id)) is not None
    }


def _run_dispatch_agent(park_id: str, items: list[dict[str, Any]]) -> Mapping[str, Any]:
    """
    Run the LangGraph dispatch agent for one park on the given triage.

    :param park_id: The park.
    :param items: The park's triage items.

    :returns state: The agent's final state.
    """
    # Imported here: the graph pulls in the agent's tools and, through them, the models.
    from smarthack.services.agent.graph import run_park_dispatch_agent

    return run_park_dispatch_agent(park_id, triage_items=items)


def predictions_object_created_handler(
    event: dict[str, Any],
    context: object | None = None,
    *,
    store: ObjectStore | None = None,
    run_agent: Callable[[str, list[dict[str, Any]]], Mapping[str, Any]] | None = None,
    park_lookup: Callable[[Sequence[int]], dict[int, str]] | None = None,
) -> dict[str, Any]:
    """
    Run the dispatch agent for every park of a new predictions file with a turbine to repair.

    :param event: An S3 `ObjectCreated` event for the predictions bucket.
    :param context: The Lambda context object; unused, kept for the Lambda signature.
    :param store: Where objects are read and written. Defaults to the local lake.
    :param run_agent: Runs the agent for one park and returns its final state. Defaults to
        the LangGraph dispatch agent.
    :param park_lookup: Finds the park of turbines the file names none for. Defaults to the
        agent's data source.

    :returns report: A `LakeRunReport` as a dictionary, one entry per record.
    """
    lake = store or default_store()
    agent = run_agent or _run_dispatch_agent
    lookup = park_lookup or _lookup_parks

    def process(key: str, body: bytes) -> _Written:
        """Group the assessments by park, run the agent where needed, write its decisions."""
        try:
            document = json.loads(body.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise ValueError(f"not UTF-8 text: {exc}") from exc
        predictions = document.get("predictions") if isinstance(document, dict) else None
        if not isinstance(predictions, list):
            raise ValueError("no `predictions` list")
        if not all(isinstance(p, dict) and "turbine_id" in p for p in predictions):
            raise ValueError("a prediction has no `turbine_id`")

        unplaced = [int(p["turbine_id"]) for p in predictions if not p.get("park_id")]
        found = lookup(unplaced)
        by_park: dict[str, list[dict[str, Any]]] = {}
        unassigned: list[int] = []
        for prediction in predictions:
            turbine_id = int(prediction["turbine_id"])
            park_id = prediction.get("park_id") or found.get(turbine_id)
            if park_id is None:
                unassigned.append(turbine_id)
                continue
            by_park.setdefault(str(park_id), []).append(triage_item(prediction, str(park_id)))

        parks: dict[str, dict[str, Any]] = {}
        for park_id, items in sorted(by_park.items()):
            failing = [item["turbine_id"] for item in items if item["needs_repair"]]
            summary: dict[str, Any] = {"turbines": len(items), "needs_repair": failing}
            if not failing:
                parks[park_id] = {**summary, "status": "no_repair_needed"}
                continue
            try:
                state = agent(park_id, items)
            except Exception as exc:  # one park must not stop the others
                logger.exception("dispatch agent failed for park %s of %s", park_id, key)
                parks[park_id] = {**summary, "status": "failed", "error": str(exc)}
                continue
            kept = {name: state[name] for name in _DISPATCH_KEYS if name in state}
            parks[park_id] = {**summary, "status": "dispatched", **kept}
            logger.info("park %s: %s", park_id, state.get("audit_summary", "agent ran"))
        if unassigned:
            logger.warning("%s: turbines %s belong to no known park", key, unassigned)

        document_out = {
            "source": f"s3://{LAKE_PREDICTIONS_BUCKET}/{key}",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "parks": parks,
            "unassigned_turbines": unassigned,
        }
        out_key = _json_key(key)
        lake.put_object(LAKE_DISPATCH_BUCKET, out_key, _to_json(document_out))
        dispatched = sum(1 for park in parks.values() if park["status"] == "dispatched")
        output = f"s3://{LAKE_DISPATCH_BUCKET}/{out_key}"
        logger.info(
            "s3://%s/%s: %d parks, agent run for %d -> %s",
            LAKE_PREDICTIONS_BUCKET,
            key,
            len(parks),
            dispatched,
            output,
        )
        return output, len(predictions), len(parks)

    return _handle(event, lake, "predictions_object_created_handler", ".json", process)


#: Which handler a new object in each bucket triggers: the S3 event notification setup.
HANDLERS: dict[str, LakeHandler] = {
    LAKE_RAW_BUCKET: raw_object_created_handler,
    LAKE_FEATURES_BUCKET: features_object_created_handler,
    LAKE_PREDICTIONS_BUCKET: predictions_object_created_handler,
}


__all__ = [
    "HANDLERS",
    "LakeHandler",
    "default_store",
    "features_object_created_handler",
    "is_lake_object",
    "parse_csv",
    "predictions_object_created_handler",
    "raw_object_created_handler",
    "triage_item",
]
