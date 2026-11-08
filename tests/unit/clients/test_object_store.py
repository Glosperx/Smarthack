"""The local object store: buckets as folders, atomic writes, keys kept inside the lake."""

from pathlib import Path

import pytest

from smarthack.clients.object_store import LocalObjectStore, validate_bucket_name


def test_an_object_reads_back_as_written(tmp_path: Path) -> None:
    """`put_object` then `get_object` is a round trip, nested keys included."""
    store = LocalObjectStore(tmp_path)

    store.put_object("raw", "2026-11-08/turbine_7.csv", b"a,b\n1,2\n")

    assert store.get_object("raw", "2026-11-08/turbine_7.csv") == b"a,b\n1,2\n"
    assert (tmp_path / "raw" / "2026-11-08" / "turbine_7.csv").is_file()


def test_a_write_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    """Only the final object is left in the bucket once the rename is done."""
    store = LocalObjectStore(tmp_path)

    store.put_object("raw", "x.csv", b"one")
    store.put_object("raw", "x.csv", b"two")

    assert [path.name for path in (tmp_path / "raw").iterdir()] == ["x.csv"]
    assert store.get_object("raw", "x.csv") == b"two"


@pytest.mark.parametrize(
    "key", ["", "../outside.csv", "a/../../outside.csv", "/abs.csv", "a\\b.csv", "C:/x.csv", "a//b"]
)
def test_a_key_that_could_leave_its_bucket_is_refused(tmp_path: Path, key: str) -> None:
    """No key reaches outside the bucket's folder."""
    with pytest.raises(ValueError, match="invalid object key"):
        LocalObjectStore(tmp_path).put_object("raw", key, b"")


@pytest.mark.parametrize("bucket", ["ab", "Raw", "raw/x", "-raw", "a" * 64])
def test_a_bucket_name_outside_the_s3_rule_is_refused(bucket: str) -> None:
    """Bucket names follow the S3 rule, so they map to safe folder names."""
    with pytest.raises(ValueError, match="invalid bucket name"):
        validate_bucket_name(bucket)


def test_locate_maps_a_path_back_to_its_bucket_and_key(tmp_path: Path) -> None:
    """A file under a bucket folder is that bucket's object, with a `/`-separated key."""
    store = LocalObjectStore(tmp_path)

    assert store.locate(tmp_path / "raw" / "2026" / "a.csv") == ("raw", "2026/a.csv")


@pytest.mark.parametrize("relative", ["loose.csv", "Not_A_Bucket/a.csv"])
def test_locate_ignores_what_is_not_in_a_bucket(tmp_path: Path, relative: str) -> None:
    """A file at the root, or in a folder that is not a bucket name, is no object."""
    assert LocalObjectStore(tmp_path).locate(tmp_path / relative) is None


def test_locate_ignores_paths_outside_the_root(tmp_path: Path) -> None:
    """A path elsewhere on disk belongs to no bucket."""
    store = LocalObjectStore(tmp_path / "lake")

    assert store.locate(tmp_path / "elsewhere" / "a.csv") is None


def test_bucket_dir_creates_the_folder(tmp_path: Path) -> None:
    """A bucket exists as soon as it is asked for."""
    path = LocalObjectStore(tmp_path).bucket_dir("raw")

    assert path == tmp_path / "raw" and path.is_dir()
