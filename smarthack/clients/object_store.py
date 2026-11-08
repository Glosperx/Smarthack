"""
# Object store

The S3 stand-in: a folder per bucket under one root, an object key as a path inside it.
`ObjectStore` is the contract a handler depends on; `LocalObjectStore` is the only
implementation today. A store backed by boto3 goes next to it when the lake moves to real
S3, and the handlers do not change.

**Writes are atomic.** `put_object` writes a hidden `.tmp` file next to the target and
renames it into place, so a watcher never sees half an object: the final name appears only
when every byte is on disk. On one volume the rename is atomic on Windows, macOS and Linux.

**Keys stay inside their bucket.** A key is a relative, `/`-separated path; an absolute key,
a `..` part or a Windows drive is refused, so no key can reach outside the lake root.

The following can be imported from this module:
- `LocalObjectStore`
- `ObjectStore`
- `validate_bucket_name`
"""

import os
from pathlib import Path
import re
from typing import Protocol
import uuid

from smarthack.constants import LAKE_TEMP_SUFFIX

#: The S3 bucket naming rule, reduced to what matters for a folder name.
_BUCKET_NAME = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


def validate_bucket_name(bucket: str) -> str:
    """
    Check that a bucket name follows the S3 naming rule.

    :param bucket: Candidate name, such as `raw`.

    :returns bucket: The same name, when valid.
    :raises ValueError: When it has upper-case letters, slashes, or is under 3 or over 63
        characters.
    """
    if not _BUCKET_NAME.match(bucket):
        raise ValueError(f"invalid bucket name {bucket!r}: use 3-63 of a-z, 0-9, '.' and '-'")
    return bucket


def _key_parts(key: str) -> tuple[str, ...]:
    """
    Split an object key into path parts, refusing any key that could leave its bucket.

    :param key: Object key, such as `2026-11-08/turbine_7.csv`.

    :returns parts: The key's non-empty parts.
    :raises ValueError: When the key is empty, absolute, holds an empty, `.` or `..` part,
        a backslash or a drive colon.
    """
    parts = tuple(key.split("/"))
    if "\\" in key or ":" in key or any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"invalid object key {key!r}")
    return parts


class ObjectStore(Protocol):
    """The operations a lake handler needs from a bucket store."""

    def get_object(self, bucket: str, key: str) -> bytes:
        """
        Read an object's whole body.

        :param bucket: Bucket name.
        :param key: Object key.

        :returns body: The object's bytes.
        """
        ...

    def put_object(self, bucket: str, key: str, body: bytes) -> None:
        """
        Write an object, replacing any object under the same key.

        :param bucket: Bucket name.
        :param key: Object key.
        :param body: The object's bytes.
        """
        ...


class LocalObjectStore:
    """
    Buckets as folders under `root`, objects as files inside them.

    :param root: The lake root; each bucket is a sub-folder created on first use.
    """

    def __init__(self, root: Path) -> None:
        """
        Remember the lake root; nothing is created until a bucket is used.

        :param root: The lake root folder.
        """
        self.root = Path(root)

    def bucket_dir(self, bucket: str) -> Path:
        """
        Return a bucket's folder, creating it when missing.

        :param bucket: Bucket name.

        :returns path: The bucket's folder under the root.
        """
        path = self.root / validate_bucket_name(bucket)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def path_for(self, bucket: str, key: str) -> Path:
        """
        Return the file that holds an object.

        :param bucket: Bucket name.
        :param key: Object key.

        :returns path: Where the object lives; it may not exist yet.
        :raises ValueError: When the bucket name or the key is invalid.
        """
        return self.root.joinpath(validate_bucket_name(bucket), *_key_parts(key))

    def locate(self, path: Path) -> tuple[str, str] | None:
        """
        Turn a file path back into the bucket and key it stores.

        :param path: A file somewhere under the root.

        :returns location: `(bucket, key)`, or None when the path is outside the root, is
            the root's own file, or lies in a folder that is not a valid bucket name.
        """
        try:
            relative = Path(os.path.abspath(path)).relative_to(os.path.abspath(self.root))
        except ValueError:
            return None
        if len(relative.parts) < 2 or not _BUCKET_NAME.match(relative.parts[0]):
            return None
        return relative.parts[0], "/".join(relative.parts[1:])

    def get_object(self, bucket: str, key: str) -> bytes:
        """
        Read an object's whole body.

        :param bucket: Bucket name.
        :param key: Object key.

        :returns body: The object's bytes.
        :raises FileNotFoundError: When no object has that key.
        """
        return self.path_for(bucket, key).read_bytes()

    def put_object(self, bucket: str, key: str, body: bytes) -> None:
        """
        Write an object atomically: to a hidden temporary file, then renamed into place.

        :param bucket: Bucket name.
        :param key: Object key; missing folders on its path are created.
        :param body: The object's bytes.
        """
        target = self.path_for(bucket, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}{LAKE_TEMP_SUFFIX}")
        try:
            with temp.open("wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)


__all__ = ["LocalObjectStore", "ObjectStore", "validate_bucket_name"]
