"""The lake handlers: the raw bucket's handler logs a new CSV file, or sends it to `failed`."""

import logging
from pathlib import Path

import pytest

from smarthack.clients.object_store import LocalObjectStore
from smarthack.schemas.lake import S3Event, object_created_event
from smarthack.services.lake_service import (
    HANDLERS,
    default_store,
    is_lake_object,
    parse_csv,
    raw_object_created_handler,
)


@pytest.fixture
def store(tmp_path: Path) -> LocalObjectStore:
    """
    A lake rooted in the test's own folder.

    :param tmp_path: pytest's per-test folder.

    :returns store: An empty local store.
    """
    return LocalObjectStore(tmp_path)


def test_a_new_csv_file_is_logged_with_its_content(
    store: LocalObjectStore, caplog: pytest.LogCaptureFixture
) -> None:
    """The handler names the file, its shape, and prints its rows."""
    store.put_object("raw", "2026-11-08/turbine 7.csv", b"turbine_id,gearbox_oil_temp\n7,61.5\n")

    with caplog.at_level(logging.INFO):
        report = raw_object_created_handler(
            object_created_event("raw", "2026-11-08/turbine 7.csv"), None, store=store
        )

    assert "New file s3://raw/2026-11-08/turbine 7.csv" in caplog.text
    assert "1 rows x 2 columns" in caplog.text
    assert '"gearbox_oil_temp": "61.5"' in caplog.text
    assert report["objects"] == [
        {
            "bucket": "raw",
            "key": "2026-11-08/turbine 7.csv",
            "status": "logged",
            "rows": 1,
            "columns": 2,
            "error": None,
        }
    ]


def test_only_the_first_rows_of_a_long_file_are_printed(
    store: LocalObjectStore, caplog: pytest.LogCaptureFixture
) -> None:
    """A long file is summarised: its row count, and a preview of the first rows."""
    body = "n\n" + "".join(f"{i}\n" for i in range(100))
    store.put_object("raw", "long.csv", body.encode())

    with caplog.at_level(logging.INFO):
        raw_object_created_handler(object_created_event("raw", "long.csv"), None, store=store)

    assert "100 rows x 1 columns (first 5 shown)" in caplog.text
    assert '"n": "4"' in caplog.text and '"n": "5"' not in caplog.text


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


def test_records_that_are_not_new_csv_files_are_skipped(store: LocalObjectStore) -> None:
    """A deletion, or an object of another type, is not processed."""
    deleted = object_created_event("raw", "a.csv")
    deleted["Records"][0]["eventName"] = "ObjectRemoved:Delete"
    other = object_created_event("raw", "notes.txt")

    statuses = [
        raw_object_created_handler(event, None, store=store)["objects"][0]["status"]
        for event in (deleted, other)
    ]

    assert statuses == ["skipped", "skipped"]


@pytest.mark.parametrize(
    "key, expected",
    [
        ("a.csv", True),
        ("2026/A.CSV", True),
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


def test_the_raw_bucket_triggers_the_raw_handler() -> None:
    """The notification setup: a new object in `raw` invokes the raw handler."""
    assert HANDLERS == {"raw": raw_object_created_handler}


def test_the_default_store_is_rooted_at_the_configured_lake(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`LAKE_DIR` decides where the handlers read from."""
    monkeypatch.setenv("LAKE_DIR", str(tmp_path))

    assert default_store().root == tmp_path
