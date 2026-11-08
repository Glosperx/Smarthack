"""
# Data lake event schemas

The shape of the event a lake handler receives, copied from the one Amazon S3 sends to an
AWS Lambda function on `s3:ObjectCreated:*`. Keeping the real shape is what lets a handler
written against the local lake move to a real Lambda unchanged: only the code that builds
the event (the folder watcher here, S3 itself there) is replaced.

Only the fields the handlers read are modelled; anything else in a real event is ignored.
S3 URL-encodes the key in the event (a space becomes `+`), so `object_created_event`
encodes it the same way and `S3ObjectRef.decoded_key` decodes it.

The following can be imported from this module:
- `LakeObjectReport`
- `LakeRunReport`
- `S3BucketRef`
- `S3Entity`
- `S3Event`
- `S3EventRecord`
- `S3ObjectRef`
- `object_created_event`
"""

from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import quote_plus, unquote_plus

from pydantic import BaseModel, ConfigDict, Field


class S3BucketRef(BaseModel):
    """The bucket an event refers to."""

    name: str = Field(description="Bucket name, such as `raw`.")


class S3ObjectRef(BaseModel):
    """The object an event refers to."""

    key: str = Field(description="Object key as S3 sends it: URL-encoded.")
    size: int = Field(default=0, ge=0, description="Object size in bytes.")

    @property
    def decoded_key(self) -> str:
        """
        Return the key as it is stored, with S3's URL encoding removed.

        :returns key: Such as `2026-11-08/turbine 7.csv` for `2026-11-08/turbine+7.csv`.
        """
        return unquote_plus(self.key)


class S3Entity(BaseModel):
    """The `s3` part of a record: which bucket and which object."""

    bucket: S3BucketRef
    object: S3ObjectRef


class S3EventRecord(BaseModel):
    """One notification: one object created in one bucket."""

    model_config = ConfigDict(populate_by_name=True)

    event_source: str = Field(default="aws:s3", alias="eventSource")
    event_name: str = Field(alias="eventName", description="Such as `ObjectCreated:Put`.")
    event_time: datetime = Field(alias="eventTime")
    s3: S3Entity

    @property
    def is_object_created(self) -> bool:
        """
        Report whether the record announces a new or overwritten object.

        :returns created: True for every `ObjectCreated:*` event.
        """
        return self.event_name.startswith("ObjectCreated:")


class S3Event(BaseModel):
    """The whole event a handler is invoked with; S3 may batch several records."""

    model_config = ConfigDict(populate_by_name=True)

    records: list[S3EventRecord] = Field(default_factory=list, alias="Records")


class LakeObjectReport(BaseModel):
    """What a handler did with one object."""

    bucket: str
    key: str
    status: Literal["logged", "failed", "skipped"]
    rows: int = 0
    columns: int = 0
    error: str | None = None


class LakeRunReport(BaseModel):
    """What a handler returns, the way a Lambda function returns a JSON document."""

    handler: str
    objects: list[LakeObjectReport] = Field(default_factory=list)


def object_created_event(
    bucket: str, key: str, size: int = 0, event_time: datetime | None = None
) -> dict[str, Any]:
    """
    Build the event S3 would send for an object created with `PutObject`.

    :param bucket: Bucket name.
    :param key: Object key, unencoded; it is URL-encoded as S3 does.
    :param size: Object size in bytes. Defaults to 0.
    :param event_time: When the object was created. Defaults to now, in UTC.

    :returns event: A JSON-ready dictionary with one record under `Records`.
    """
    when = event_time or datetime.now(timezone.utc)
    return {
        "Records": [
            {
                "eventSource": "aws:s3",
                "eventName": "ObjectCreated:Put",
                "eventTime": when.isoformat().replace("+00:00", "Z"),
                "s3": {
                    "bucket": {"name": bucket},
                    "object": {"key": quote_plus(key, safe="/"), "size": size},
                },
            }
        ]
    }


__all__ = [
    "LakeObjectReport",
    "LakeRunReport",
    "S3BucketRef",
    "S3Entity",
    "S3Event",
    "S3EventRecord",
    "S3ObjectRef",
    "object_created_event",
]
