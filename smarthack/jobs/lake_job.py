"""
# Local data lake worker

The command line of the local lake, standing in for S3 event notifications and the
`aws s3 cp` upload.

```
python -m smarthack.jobs.lake_job watch [--polling]
python -m smarthack.jobs.lake_job put FILE [--key KEY] [--bucket raw]
```

`watch` follows the lake root with `watchdog` (FSEvents on macOS, ReadDirectoryChangesW on
Windows, inotify on Linux) and, for every finished file that appears in a bucket with a
handler in `HANDLERS`, builds the S3 event and invokes the handler. `--polling` scans the
folder instead of waiting for the operating system's events: use it inside Docker on a
folder mounted from a macOS or Windows host, where those events do not cross the mount.

`put` writes a file into a bucket atomically, the way the producer of the telemetry should,
so the watcher never sees half a file. A file copied in by hand works too: the watcher waits
until its size stops changing before it reads it.

A new or overwritten object triggers its handler once. Created, modified and renamed events
all arrive for the same write, so an object is handled again only when its size or
modification time has changed, as S3 sends one event per `PutObject`.

The following can be imported from this module:
- `LakeEventRouter`
- `main`
- `put_file`
- `wait_until_stable`
- `watch`
"""

import argparse
import logging
import os
from pathlib import Path
import sys
import threading
import time
from typing import Callable, Mapping

from smarthack import config
from smarthack.clients.object_store import LocalObjectStore
from smarthack.constants import LAKE_RAW_BUCKET
from smarthack.schemas.lake import object_created_event
from smarthack.services.lake_service import HANDLERS, LakeHandler, is_lake_object
from smarthack.utils.logging_utils import configure_logging

logger = logging.getLogger(__name__)

#: Seconds between two size checks of a file that is still being copied in.
SETTLE_INTERVAL_S = 0.25

#: How many size checks a file gets before it is read anyway.
SETTLE_ATTEMPTS = 40


def wait_until_stable(
    path: Path,
    interval: float = SETTLE_INTERVAL_S,
    attempts: int = SETTLE_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
) -> os.stat_result | None:
    """
    Wait until a file stops growing: its size and modification time hold for one interval.

    :param path: The file to watch.
    :param interval: Seconds between two checks.
    :param attempts: How many checks before giving up waiting and returning the last one.
    :param sleep: The sleep function, replaced in tests.

    :returns stat: The file's last `os.stat`, or None when it disappeared meanwhile or cannot
        be read, such as a file another process holds locked on Windows.
    """
    try:
        previous = path.stat()
    except OSError:
        return None
    for _ in range(attempts):
        sleep(interval)
        try:
            current = path.stat()
        except OSError:
            return None
        if (current.st_size, current.st_mtime_ns) == (previous.st_size, previous.st_mtime_ns):
            return current
        previous = current
    return previous


class LakeEventRouter:
    """
    Turn a file event of the lake root into one S3 event for the bucket's handler.

    :param store: The lake's store; it maps a path back to its bucket and key.
    :param handlers: Which handler each bucket triggers. Defaults to `HANDLERS`.
    :param settle: Waits for a file to stop changing. Defaults to `wait_until_stable`.
    """

    def __init__(
        self,
        store: LocalObjectStore,
        handlers: Mapping[str, LakeHandler] | None = None,
        settle: Callable[[Path], os.stat_result | None] = wait_until_stable,
    ) -> None:
        """
        Keep the store and handlers; nothing has been handled yet.

        :param store: The lake's store.
        :param handlers: Bucket to handler. Defaults to `HANDLERS`.
        :param settle: Waits for a file to stop changing.
        """
        self.store = store
        self.handlers = HANDLERS if handlers is None else handlers
        self.settle = settle
        self._handled: dict[tuple[str, str], tuple[int, int]] = {}
        self._lock = threading.Lock()

    def on_path(self, path: Path) -> bool:
        """
        Invoke the handler for a file that appeared or changed, at most once per version.

        :param path: The file the event is about.

        :returns invoked: True when a handler ran.
        """
        location = self.store.locate(path)
        if location is None:
            return False
        bucket, key = location
        handler = self.handlers.get(bucket)
        if handler is None or not is_lake_object(key):
            return False
        with self._lock:
            stat = self.settle(path)
            if stat is None:
                return False
            version = (stat.st_size, stat.st_mtime_ns)
            if self._handled.get(location) == version:
                return False
            self._handled[location] = version
            event = object_created_event(bucket, key, size=stat.st_size)
            try:
                handler(event, None, store=self.store)
            except Exception:
                logger.exception("handler for s3://%s/%s failed", bucket, key)
            return True


def watch(
    root: Path, polling: bool = False, stop: threading.Event | None = None
) -> None:  # pragma: no cover - exercised by the integration test, in a thread
    """
    Follow the lake root and route each new file to its bucket's handler until stopped.

    :param root: The lake root.
    :param polling: Whether to scan the folder instead of using the system's file events.
    :param stop: Ends the loop when set. Defaults to running until Ctrl+C.

    :raises SystemExit: When the `lake` extra (`watchdog`) is not installed.
    """
    # Imported here so that the rest of the module, and the handlers, work on a core
    # install: only the watcher needs the `lake` extra.
    try:
        from watchdog.events import FileSystemEvent, FileSystemEventHandler
        from watchdog.observers import Observer
        from watchdog.observers.polling import PollingObserver
    except ImportError as exc:
        raise SystemExit(f'{exc.name} is missing: pip install -e ".[lake]"') from exc

    store = LocalObjectStore(root)
    for bucket in sorted({*HANDLERS, LAKE_RAW_BUCKET}):
        store.bucket_dir(bucket)
    router = LakeEventRouter(store)

    class _Forward(FileSystemEventHandler):
        """Send the path of every created, changed or renamed file to the router."""

        def on_any_event(self, event: FileSystemEvent) -> None:
            """
            Forward a file event; folder events and deletions are ignored.

            :param event: The event watchdog observed.
            """
            if event.is_directory or event.event_type not in ("created", "modified", "moved"):
                return
            target = event.dest_path if event.event_type == "moved" else event.src_path
            router.on_path(Path(os.fsdecode(target)))

    observer = PollingObserver() if polling else Observer()
    observer.schedule(_Forward(), str(root), recursive=True)
    observer.start()
    mode = "polling" if polling else "file system events"
    logger.info("Watching the lake at %s (%s); buckets: %s", root, mode, ", ".join(HANDLERS))
    stop = stop or threading.Event()
    try:
        while not stop.wait(0.5):
            pass
    except KeyboardInterrupt:
        logger.info("Stopping the lake watcher")
    finally:
        observer.stop()
        observer.join()


def put_file(store: LocalObjectStore, source: Path, bucket: str, key: str | None = None) -> str:
    """
    Upload a local file into a bucket, atomically.

    :param store: The lake's store.
    :param source: The file to upload.
    :param bucket: Target bucket.
    :param key: Target key. Defaults to the file's name.

    :returns key: The key the object was stored under.
    """
    target_key = key or source.name
    store.put_object(bucket, target_key, source.read_bytes())
    return target_key


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """
    Parse the command line.

    :param argv: Arguments without the program name. Defaults to `sys.argv[1:]`.

    :returns args: The parsed arguments, with `command` set to `watch` or `put`.
    """
    parser = argparse.ArgumentParser(prog="python -m smarthack.jobs.lake_job")
    commands = parser.add_subparsers(dest="command", required=True)
    watch_cmd = commands.add_parser("watch", help="run the handlers on every new file")
    watch_cmd.add_argument(
        "--polling", action="store_true", help="scan the folder (Docker on a mounted folder)"
    )
    put_cmd = commands.add_parser("put", help="upload a file into a bucket atomically")
    put_cmd.add_argument("file", type=Path, help="the local file to upload")
    put_cmd.add_argument("--bucket", default=LAKE_RAW_BUCKET, help="target bucket (raw)")
    put_cmd.add_argument("--key", default=None, help="object key (the file's name)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    Run the `watch` or `put` command.

    :param argv: Arguments without the program name. Defaults to `sys.argv[1:]`.

    :returns code: 0 on success, 1 when the file to upload is missing or the key invalid.
    """
    args = _parse_args(argv)
    configure_logging()
    root = config.lake_dir()
    if args.command == "watch":  # pragma: no cover - blocks until Ctrl+C
        watch(root, polling=args.polling)
        return 0

    if not args.file.is_file():
        logger.error("%s is not a file", args.file)
        return 1
    try:
        key = put_file(LocalObjectStore(root), args.file, args.bucket, args.key)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1
    logger.info("Uploaded %s to s3://%s/%s", args.file, args.bucket, key)
    return 0


__all__ = ["LakeEventRouter", "main", "put_file", "wait_until_stable", "watch"]

if __name__ == "__main__":
    sys.exit(main())
