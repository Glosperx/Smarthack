"""
# Data lake handlers

The functions the local lake invokes when an object lands in a bucket: the stand-ins for
AWS Lambda functions. Each has the Lambda signature, `handler(event, context)`, takes the
S3 event of `smarthack.schemas.lake` and returns a JSON-ready report, so it can be deployed
to a real Lambda behind a real S3 bucket with only its store replaced.

Today there is one, `raw_object_created_handler`, on the landing bucket. It reads the CSV
file that arrived and logs its name, its size and its first rows, nothing more: the step
that cuts the model's columns into a second bucket comes when the new model does.

A file that cannot be read as CSV is copied to the `failed` bucket under the same key,
the dead-letter queue of the pipeline, and the handler carries on with the next record.

`HANDLERS` maps a bucket to the handler its new objects trigger; the watcher reads it.

The following can be imported from this module:
- `HANDLERS`
- `LakeHandler`
- `default_store`
- `is_lake_object`
- `parse_csv`
- `raw_object_created_handler`
"""

import csv
import io
import json
import logging
from pathlib import PurePosixPath
from typing import Any, Callable

from smarthack import config
from smarthack.clients.object_store import LocalObjectStore, ObjectStore
from smarthack.constants import (
    LAKE_FAILED_BUCKET,
    LAKE_OBJECT_SUFFIXES,
    LAKE_PREVIEW_ROWS,
    LAKE_RAW_BUCKET,
    LAKE_TEMP_SUFFIX,
)
from smarthack.schemas.lake import LakeObjectReport, LakeRunReport, S3Event

logger = logging.getLogger(__name__)

#: A lake handler: the Lambda signature, plus the store as an optional keyword.
LakeHandler = Callable[..., dict[str, Any]]


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

    Values stay strings: the handler only shows them, and typing them is the job of the
    step that feeds the model, which knows each column's type.

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


def raw_object_created_handler(
    event: dict[str, Any], context: object | None = None, *, store: ObjectStore | None = None
) -> dict[str, Any]:
    """
    Log every CSV file that lands in the raw bucket: its name, shape and first rows.

    :param event: An S3 `ObjectCreated` event, as `object_created_event` builds it.
    :param context: The Lambda context object; unused, kept for the Lambda signature.
    :param store: Where objects are read from. Defaults to the local lake.

    :returns report: A `LakeRunReport` as a dictionary, one entry per record.
    """
    store = store or default_store()
    parsed = S3Event.model_validate(event)
    report = LakeRunReport(handler="raw_object_created_handler")
    for record in parsed.records:
        bucket, key = record.s3.bucket.name, record.s3.object.decoded_key
        if not record.is_object_created or not is_lake_object(key):
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
            columns, rows = parse_csv(body)
        except (ValueError, csv.Error) as exc:
            logger.error("s3://%s/%s is not a valid CSV file: %s", bucket, key, exc)
            _send_to_failed(store, key, body)
            report.objects.append(
                LakeObjectReport(bucket=bucket, key=key, status="failed", error=str(exc))
            )
            continue

        preview = json.dumps(rows[:LAKE_PREVIEW_ROWS], indent=2, ensure_ascii=False)
        shown = "" if len(rows) <= LAKE_PREVIEW_ROWS else f" (first {LAKE_PREVIEW_ROWS} shown)"
        logger.info(
            "New file s3://%s/%s: %d bytes, %d rows x %d columns%s\n%s",
            bucket,
            key,
            len(body),
            len(rows),
            len(columns),
            shown,
            preview,
        )
        report.objects.append(
            LakeObjectReport(
                bucket=bucket, key=key, status="logged", rows=len(rows), columns=len(columns)
            )
        )
    return report.model_dump()


#: Which handler a new object in each bucket triggers: the S3 event notification setup.
HANDLERS: dict[str, LakeHandler] = {LAKE_RAW_BUCKET: raw_object_created_handler}


__all__ = [
    "HANDLERS",
    "LakeHandler",
    "default_store",
    "is_lake_object",
    "parse_csv",
    "raw_object_created_handler",
]
