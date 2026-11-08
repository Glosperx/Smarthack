"""The lake worker: file events become one S3 event per object version; `put` is atomic."""

import os
from pathlib import Path
import threading
import time
from typing import Any

import pytest

from smarthack.clients.object_store import LocalObjectStore
from smarthack.jobs.lake_job import (
    DEFAULT_SAMPLE_TURBINES,
    LakeEventRouter,
    main,
    put_file,
    wait_until_stable,
)
from tests.conftest import requires_extra


class _Recorder:
    """A handler that records the events it is invoked with."""

    def __init__(self) -> None:
        """Start with no events."""
        self.events: list[dict[str, Any]] = []
        self.received = threading.Event()

    def __call__(self, event: dict[str, Any], context: object, *, store: object) -> dict[str, Any]:
        """
        Record an event.

        :param event: The S3 event.
        :param context: The Lambda context; unused.
        :param store: The lake's store; unused.

        :returns report: An empty report.
        """
        self.events.append(event)
        self.received.set()
        return {}


def _router(root: Path, recorder: _Recorder) -> LakeEventRouter:
    """
    Build a router whose only handler is `recorder`, without waiting for files to settle.

    :param root: The lake root.
    :param recorder: The handler of the raw bucket.

    :returns router: The router under test.
    """
    return LakeEventRouter(LocalObjectStore(root), {"raw": recorder}, settle=_stat_now)


def _stat_now(path: Path) -> os.stat_result | None:
    """
    Settle immediately: return the file's stat, or None when it is gone.

    :param path: The file.

    :returns stat: Its `os.stat`, or None.
    """
    return path.stat() if path.exists() else None


def test_a_new_file_triggers_its_bucket_handler_once(tmp_path: Path) -> None:
    """Created, modified and moved events for one write invoke the handler once."""
    recorder = _Recorder()
    router = _router(tmp_path, recorder)
    LocalObjectStore(tmp_path).put_object("raw", "a.csv", b"x\n1\n")
    path = tmp_path / "raw" / "a.csv"

    results = [router.on_path(path) for _ in range(3)]

    assert results == [True, False, False]
    assert recorder.events[0]["Records"][0]["s3"]["object"] == {"key": "a.csv", "size": 4}


def test_an_overwritten_file_triggers_the_handler_again(tmp_path: Path) -> None:
    """A new version of the same key is a new `ObjectCreated` event, as on S3."""
    recorder = _Recorder()
    router = _router(tmp_path, recorder)
    store = LocalObjectStore(tmp_path)
    store.put_object("raw", "a.csv", b"x\n1\n")
    router.on_path(tmp_path / "raw" / "a.csv")

    store.put_object("raw", "a.csv", b"x\n1\n2\n")

    assert router.on_path(tmp_path / "raw" / "a.csv") is True
    assert len(recorder.events) == 2


@pytest.mark.parametrize(
    "relative", ["raw/.a.csv.1234.tmp", "raw/.DS_Store", "raw/a.txt", "failed/a.csv", "a.csv"]
)
def test_files_with_no_handler_are_ignored(tmp_path: Path, relative: str) -> None:
    """Temporary and hidden files, other types, and buckets without a handler do nothing."""
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    recorder = _Recorder()

    assert _router(tmp_path, recorder).on_path(path) is False
    assert recorder.events == []


def test_a_file_gone_before_it_settles_is_ignored(tmp_path: Path) -> None:
    """An event for a file deleted meanwhile invokes nothing."""
    recorder = _Recorder()

    assert _router(tmp_path, recorder).on_path(tmp_path / "raw" / "gone.csv") is False


def test_a_failing_handler_does_not_stop_the_router(tmp_path: Path) -> None:
    """A handler that raises is logged; the next file is still handled."""

    def explode(event: dict[str, Any], context: object, *, store: object) -> dict[str, Any]:
        """
        Fail on every event.

        :param event: The S3 event.
        :param context: Unused.
        :param store: Unused.

        :returns: Never returns.
        """
        raise RuntimeError("boom")

    router = LakeEventRouter(LocalObjectStore(tmp_path), {"raw": explode}, settle=_stat_now)
    LocalObjectStore(tmp_path).put_object("raw", "a.csv", b"x")

    assert router.on_path(tmp_path / "raw" / "a.csv") is True


def test_wait_until_stable_waits_for_the_size_to_hold(tmp_path: Path) -> None:
    """A file still growing is checked again until two checks agree."""
    path = tmp_path / "growing.csv"
    path.write_bytes(b"a")
    writes = iter([b"ab", b"abc"])

    def grow(_: float) -> None:
        """
        Append to the file on the first two sleeps, as a slow copy would.

        :param _: The interval; unused.
        """
        chunk = next(writes, None)
        if chunk is not None:
            path.write_bytes(chunk)
            os.utime(path, ns=(time.time_ns(), time.time_ns() + len(chunk)))

    stat = wait_until_stable(path, interval=0, sleep=grow)

    assert stat is not None and stat.st_size == 3


def test_wait_until_stable_returns_none_for_a_missing_file(tmp_path: Path) -> None:
    """A file that does not exist never settles."""
    assert wait_until_stable(tmp_path / "missing.csv", interval=0) is None


def test_put_file_uploads_under_the_file_name(tmp_path: Path) -> None:
    """Without a key, the object is named after the file."""
    source = tmp_path / "telemetry.csv"
    source.write_bytes(b"x\n1\n")
    store = LocalObjectStore(tmp_path / "lake")

    assert put_file(store, source, "raw") == "telemetry.csv"
    assert store.get_object("raw", "telemetry.csv") == b"x\n1\n"


def test_main_put_uploads_into_the_configured_lake(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`put FILE --key KEY` writes the object into the lake that `LAKE_DIR` names."""
    monkeypatch.setenv("LAKE_DIR", str(tmp_path / "lake"))
    source = tmp_path / "t.csv"
    source.write_bytes(b"x\n1\n")

    assert main(["put", str(source), "--key", "2026-11-08/t.csv"]) == 0
    assert (tmp_path / "lake" / "raw" / "2026-11-08" / "t.csv").read_bytes() == b"x\n1\n"


def test_main_put_fails_on_a_missing_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Uploading a file that does not exist exits with 1."""
    monkeypatch.setenv("LAKE_DIR", str(tmp_path / "lake"))

    assert main(["put", str(tmp_path / "missing.csv")]) == 1


def test_main_put_fails_on_a_key_leaving_its_bucket(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A key with `..` is refused and nothing is written outside the lake."""
    monkeypatch.setenv("LAKE_DIR", str(tmp_path / "lake"))
    source = tmp_path / "t.csv"
    source.write_bytes(b"x")

    assert main(["put", str(source), "--key", "../../escaped.csv"]) == 1
    assert not (tmp_path / "escaped.csv").exists()


@requires_extra("wind")
def test_main_sample_puts_simulated_scada_into_raw(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`sample` writes the raw sensors of the asked turbines, one row per 10 minutes."""
    monkeypatch.setenv("LAKE_DIR", str(tmp_path))

    code = main(
        [
            "sample",
            "--turbine",
            "3=gearbox_wear",
            "--turbine",
            "4",
            "--hours",
            "2",
            "--key",
            "s.csv",
        ]
    )

    assert code == 0
    lines = (tmp_path / "raw" / "s.csv").read_text().splitlines()
    header = lines[0].split(",")
    assert header[:2] == ["time_stamp", "turbine_id"]
    assert len(lines) == 1 + 2 * 12
    assert {line.split(",")[header.index("scenario")] for line in lines[1:]} == {
        "gearbox_wear",
        "normal",
    }


def test_main_sample_refuses_a_turbine_that_is_not_a_number(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`--turbine` takes ID=SCENARIO."""
    monkeypatch.setenv("LAKE_DIR", str(tmp_path))

    with pytest.raises(SystemExit):
        main(["sample", "--turbine", "seven=normal"])


def test_the_default_sample_is_the_seed_fleet_with_failures_in_both_parks() -> None:
    """Two failing turbines in one park make the agent call the power model."""
    assert sorted(DEFAULT_SAMPLE_TURBINES) == [0, 1, 2, 10, 11]
    assert [t for t, s in DEFAULT_SAMPLE_TURBINES.items() if s != "normal"] == [1, 2, 11]


@requires_extra("lake")
@pytest.mark.integration
@pytest.mark.parametrize("polling", [False, True])
def test_the_watcher_invokes_the_handler_for_a_dropped_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, polling: bool
) -> None:
    """End to end: a file written into `raw/` reaches the handler through watchdog."""
    from smarthack.jobs import lake_job

    recorder = _Recorder()
    monkeypatch.setattr(lake_job, "HANDLERS", {"raw": recorder})
    stop = threading.Event()
    thread = threading.Thread(target=lake_job.watch, args=(tmp_path, polling, stop), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not (tmp_path / "raw").is_dir() and time.monotonic() < deadline:
            time.sleep(0.05)
        time.sleep(0.5)
        LocalObjectStore(tmp_path).put_object("raw", "dropped.csv", b"x\n1\n")

        assert recorder.received.wait(10), "the handler was never invoked"
    finally:
        stop.set()
        thread.join(10)
    assert recorder.events[0]["Records"][0]["s3"]["object"]["key"] == "dropped.csv"
