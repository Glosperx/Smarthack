"""
# Oversize transport network constants

The vehicle the network is judged for, the road classes kept, the entry ports, the
thresholds of each rule and the reason codes written to the built network.

The vehicle is the worst case of a 2.4-3 MW onshore turbine (Vestas V90/V110, GE 2.5,
Enercon E-82 class): each limit comes from the part that sets it.

| Limit | Part | Value |
|---|---|---|
| Length | blade of 45-55 m on an extendable trailer | 60 m |
| Height | bottom tower section, ~4.3 m diameter, on a low-bed | 4.8 m |
| Width | the same tower section | 4.5 m |
| Gross weight | nacelle of 70-90 t with tractor and trailer | 120 t |

The following can be imported from this module:
- `BRIDGE_CHECK_CLASSES`
- `CURVE_HALF_WINDOW_M`
- `CURVE_MIN_RADIUS_M`
- `GEOFABRIK_ROMANIA_URL`
- `MIN_ROAD_WIDTH_M`
- `PORT_SNAP_RADIUS_M`
- `PORTS`
- `REASON_LABELS`
- `REASONS_BLOCKING`
- `ROAD_CLASSES`
- `SIMPLIFY_TOLERANCE_DEG`
- `VEHICLE_GROSS_T`
- `VEHICLE_HEIGHT_M`
- `VEHICLE_LENGTH_M`
- `VEHICLE_WIDTH_M`
- `VERDICT_BLOCKED`
- `VERDICT_CONDITIONAL`
- `VERDICT_ISOLATED`
- `VERDICT_LABELS`
- `VERDICT_VIABLE`
- `WEAK_ROAD_MAXWEIGHT_T`
- `WEAK_STRUCTURE_MAXWEIGHT_T`
"""

#: OpenStreetMap extract of Romania, rebuilt daily by Geofabrik (ODbL).
GEOFABRIK_ROMANIA_URL: str = "https://download.geofabrik.de/europe/romania-latest.osm.pbf"

VEHICLE_LENGTH_M: float = 60.0
VEHICLE_HEIGHT_M: float = 4.8
VEHICLE_WIDTH_M: float = 4.5
VEHICLE_GROSS_T: float = 120.0

#: OSM `highway` values kept, in display order (index = class code in the built file).
#: In Romania: motorway = A*, trunk = expressways and main DN, primary/secondary = DN,
#: tertiary = mostly DJ (county roads). Smaller roads are last-mile work, out of scope.
ROAD_CLASSES: tuple[str, ...] = ("motorway", "trunk", "primary", "secondary", "tertiary")

#: Where turbine components enter the country: the Black Sea port, where blades and
#: nacelles are unloaded from ships, and the two Danube ports reached by barge.
#: (name, latitude, longitude)
PORTS: tuple[tuple[str, float, float], ...] = (
    ("Port Constanța", 44.1650, 28.6450),
    ("Port Galați", 45.4330, 28.0480),
    ("Port Brăila", 45.2720, 27.9800),
)

#: A port is connected to every network node within this distance of it.
PORT_SNAP_RADIUS_M: float = 5000.0

#: Signed weight limits below this mean a structurally weak bridge or road: blocked.
WEAK_STRUCTURE_MAXWEIGHT_T: float = 20.0

#: Signed weight limits below the standard 40 t truck limit, but not tiny: to check.
WEAK_ROAD_MAXWEIGHT_T: float = 40.0

#: Bridges on these classes have no known capacity in OSM and are flagged to check.
#: Motorway, trunk and primary bridges are built to national heavy-load standards.
BRIDGE_CHECK_CLASSES: frozenset[str] = frozenset({"secondary", "tertiary"})

#: Horizontal curve radius below which a 60 m blade needs a blade lifter or swept-path
#: work. Measured on a circle through points `CURVE_HALF_WINDOW_M` before and after each
#: node, so that the digitising noise of close nodes does not read as a curve.
CURVE_MIN_RADIUS_M: float = 40.0
CURVE_HALF_WINDOW_M: float = 15.0

#: A tagged carriageway narrower than this leaves no margin for a 4.5 m load.
MIN_ROAD_WIDTH_M: float = 6.0

#: Douglas-Peucker tolerance of the served geometry (~30 m), after all checks ran on the
#: full-resolution geometry.
SIMPLIFY_TOLERANCE_DEG: float = 0.0003

#: Reason bit -> label. A road's reasons are the OR of its bits.
REASON_LABELS: dict[int, str] = {
    1: "Signed height limit below 4.8 m",
    2: "Signed width limit below 4.5 m",
    4: "Signed weight limit below 20 t (weak bridge or road)",
    8: "Closed to heavy goods vehicles",
    16: "Signed weight limit below 40 t",
    32: "Bridge with no known load capacity",
    64: "Tunnel with no known clearance",
    128: "Tight curve (radius under 40 m)",
    256: "Roundabout",
    512: "County or local road (likely under 7 m wide)",
    1024: "Narrow, single-lane or unpaved",
    2048: "Signed length limit",
    4096: "Access only for destination traffic",
}

#: Reason bits that block the road on their own; every other bit means "to check".
REASONS_BLOCKING: int = 1 | 2 | 4 | 8

#: Verdict codes of a road in the built network.
VERDICT_VIABLE: int = 0
VERDICT_CONDITIONAL: int = 1
VERDICT_BLOCKED: int = 2
VERDICT_ISOLATED: int = 3

VERDICT_LABELS: dict[int, str] = {
    VERDICT_VIABLE: "Viable: nothing known against it, reachable from a port",
    VERDICT_CONDITIONAL: "To check: a bridge, curve, narrow or county road on this stretch",
    VERDICT_BLOCKED: "Blocked: a signed limit or ban stops the vehicle",
    VERDICT_ISOLATED: "Isolated: no port reaches it without a blocked road",
}

__all__ = [
    "BRIDGE_CHECK_CLASSES",
    "CURVE_HALF_WINDOW_M",
    "CURVE_MIN_RADIUS_M",
    "GEOFABRIK_ROMANIA_URL",
    "MIN_ROAD_WIDTH_M",
    "PORT_SNAP_RADIUS_M",
    "PORTS",
    "REASON_LABELS",
    "REASONS_BLOCKING",
    "ROAD_CLASSES",
    "SIMPLIFY_TOLERANCE_DEG",
    "VEHICLE_GROSS_T",
    "VEHICLE_HEIGHT_M",
    "VEHICLE_LENGTH_M",
    "VEHICLE_WIDTH_M",
    "VERDICT_BLOCKED",
    "VERDICT_CONDITIONAL",
    "VERDICT_ISOLATED",
    "VERDICT_LABELS",
    "VERDICT_VIABLE",
    "WEAK_ROAD_MAXWEIGHT_T",
    "WEAK_STRUCTURE_MAXWEIGHT_T",
]
