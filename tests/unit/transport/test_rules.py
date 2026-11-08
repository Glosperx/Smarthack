"""Unit tests for the oversize transport tag rules."""

import pytest

from smarthack.transport.constants import REASONS_BLOCKING
from smarthack.transport.rules import classify_tags, parse_length_m, parse_weight_t


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("4.5", 4.5),
        ("4,2 m", 4.2),
        ("14'6\"", 14 * 0.3048 + 6 * 0.0254),
        ("450 cm", 4.5),
        ("default", None),
        (None, None),
    ],
)
def test_parse_length(raw: str | None, expected: float | None) -> None:
    """Lengths in metres, comma decimals, feet-inches and centimetres all read as metres."""
    got = parse_length_m(raw)
    assert got == pytest.approx(expected) if expected is not None else got is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("7.5", 7.5), ("20 t", 20.0), ("3500 kg", 3.5), ("none", None), (None, None)],
)
def test_parse_weight(raw: str | None, expected: float | None) -> None:
    """Weights in tonnes or kilograms read as tonnes; words are not numbers."""
    got = parse_weight_t(raw)
    assert got == pytest.approx(expected) if expected is not None else got is None


def test_plain_national_road_is_clear() -> None:
    """A national road with nothing against it raises no reason."""
    assert classify_tags({"highway": "primary", "ref": "DN2"}) == 0


def test_low_clearance_and_weak_bridge_block() -> None:
    """A 4.2 m height limit and a 10 t weight limit each block on their own."""
    reasons = classify_tags({"highway": "secondary", "maxheight": "4.2", "maxweight": "10"})
    assert reasons & 1 and reasons & 4
    assert reasons & REASONS_BLOCKING


def test_untagged_bridge_on_small_road_is_to_check_but_not_on_trunk() -> None:
    """Bridge capacity is unknown in OSM: flagged on secondary roads, trusted on trunk roads."""
    assert classify_tags({"highway": "secondary", "bridge": "yes"}) == 32
    assert classify_tags({"highway": "trunk", "bridge": "yes"}) == 0


def test_hgv_ban_blocks_and_destination_is_to_check() -> None:
    """`hgv=no` blocks; `hgv=destination` only asks for a check."""
    assert classify_tags({"highway": "primary", "hgv": "no"}) & 8
    assert classify_tags({"highway": "primary", "hgv": "destination"}) == 4096


def test_single_lane_counts_only_on_two_way_roads() -> None:
    """One lane is normal on a ramp (one-way); on a two-way road it is narrow."""
    assert classify_tags({"highway": "motorway_link", "lanes": "1", "oneway": "yes"}) == 0
    assert classify_tags({"highway": "secondary", "lanes": "1"}) == 1024


def test_county_road_and_roundabout_are_to_check() -> None:
    """County roads and roundabouts are not blocked, only flagged."""
    reasons = classify_tags({"highway": "tertiary", "junction": "roundabout"})
    assert reasons == 512 | 256
    assert not reasons & REASONS_BLOCKING
