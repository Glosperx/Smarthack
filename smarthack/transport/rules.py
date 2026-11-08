"""
# Oversize transport rules

Reads the OpenStreetMap tags of one road and says what stands in the way of the
reference vehicle (see `constants`). Pure functions of the tags, no geometry: the curve
check is in `geometry`.

A missing tag is not a permission. OSM rarely tags bridge capacity in Romania, so an
untagged bridge on a smaller road is "to check", never "fine".

The following can be imported from this module:
- `classify_tags`
- `parse_length_m`
- `parse_weight_t`
"""

import re

from smarthack.transport import constants as C

_NUMBER = re.compile(r"(\d+(?:[.,]\d+)?)")
_FEET_INCHES = re.compile(r"^\s*(\d+)\s*'\s*(?:(\d+)\s*\")?\s*$")


def parse_length_m(value: str | None) -> float | None:
    """
    Parse an OSM length such as `maxheight` or `width` into metres.

    :param value: Tag value, such as `"4.5"`, `"4,5 m"`, `"14'6\\""` or `"default"`.

    :returns metres: The length, or None when the value is missing or not a number.
    """
    if not value:
        return None
    feet = _FEET_INCHES.match(value)
    if feet:
        return int(feet.group(1)) * 0.3048 + int(feet.group(2) or 0) * 0.0254
    match = _NUMBER.search(value)
    if not match:
        return None
    number = float(match.group(1).replace(",", "."))
    if "cm" in value:
        return number / 100.0
    return number


def parse_weight_t(value: str | None) -> float | None:
    """
    Parse an OSM weight such as `maxweight` into metric tonnes.

    :param value: Tag value, such as `"7.5"`, `"20 t"`, `"3500 kg"` or `"none"`.

    :returns tonnes: The weight, or None when the value is missing or not a number.
    """
    if not value:
        return None
    match = _NUMBER.search(value)
    if not match:
        return None
    number = float(match.group(1).replace(",", "."))
    if "kg" in value:
        return number / 1000.0
    if "lbs" in value:
        return number * 0.000453592
    if "st" in value:  # short tons
        return number * 0.907185
    return number


def classify_tags(tags: dict[str, str]) -> int:
    """
    Return the reason bits (see `constants.REASON_LABELS`) the tags of a road raise.

    :param tags: The way's OSM tags; `highway` must be one of `constants.ROAD_CLASSES`
        or its `_link`.

    :returns reasons: OR of reason bits; 0 when nothing is known against the road.
    """
    road_class = tags.get("highway", "").removesuffix("_link")
    reasons = 0

    height = parse_length_m(tags.get("maxheight") or tags.get("maxheight:physical"))
    if height is not None and height < C.VEHICLE_HEIGHT_M:
        reasons |= 1
    max_width = parse_length_m(tags.get("maxwidth") or tags.get("maxwidth:physical"))
    if max_width is not None and max_width < C.VEHICLE_WIDTH_M:
        reasons |= 2

    weight = parse_weight_t(tags.get("maxweight") or tags.get("maxweightrating"))
    if weight is not None and weight < C.WEAK_STRUCTURE_MAXWEIGHT_T:
        reasons |= 4
    elif weight is not None and weight < C.WEAK_ROAD_MAXWEIGHT_T:
        reasons |= 16

    if "no" in (tags.get("hgv"), tags.get("motor_vehicle"), tags.get("access")):
        reasons |= 8
    elif tags.get("access") == "private":
        reasons |= 8
    elif "destination" in (tags.get("hgv"), tags.get("access")):
        reasons |= 4096

    bridge = tags.get("bridge", "no") not in ("no", "")
    if bridge and weight is None and road_class in C.BRIDGE_CHECK_CLASSES:
        reasons |= 32
    tunnel = tags.get("tunnel", "no") not in ("no", "")
    if tunnel and height is None:
        reasons |= 64

    if tags.get("junction") in ("roundabout", "circular"):
        reasons |= 256
    if road_class == "tertiary":
        reasons |= 512

    width = parse_length_m(tags.get("width") or tags.get("est_width"))
    unpaved = tags.get("surface") in ("unpaved", "gravel", "dirt", "ground", "compacted", "grass")
    # One lane each way is normal on a ramp or a dual carriageway; only two-way roads count.
    two_way = tags.get("oneway", "no") not in ("yes", "-1", "true", "1")
    single_lane = tags.get("lanes") == "1" and two_way
    if (width is not None and two_way and width < C.MIN_ROAD_WIDTH_M) or single_lane or unpaved:
        reasons |= 1024
    if parse_length_m(tags.get("maxlength")) is not None:
        reasons |= 2048
    return reasons


__all__ = ["classify_tags", "parse_length_m", "parse_weight_t"]
