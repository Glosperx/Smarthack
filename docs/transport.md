# Oversize transport network

Can a convoy carrying the parts of a wind turbine get there? The map's **Oversize
transport** panel colours every major road of Romania for the oversize loads of a
2.4-3 MW turbine, and shows which roads can be reached from the ports where turbine parts
enter the country.

```bash
make transport               # first run downloads ~330 MB of OpenStreetMap (cached), then ~40 s
make transport ARGS=--refresh  # download a fresh extract first
```

The build writes `models/transport/` (`network.json.gz`, `summary.json`), served by
`GET /api/transport/{summary,network}`.

## There is no open map of oversize routes

Romania has no published network of roads approved for oversize transport. Each convoy
gets a special transport authorisation (AST) from CNAIR for one route. So the map is built
from what is open: the road network of OpenStreetMap and the limits tagged on it. Its job
is to show at a glance which regions are plausible, and where the obstacles are. It is not
a route authorisation.

## The reference vehicle

A 2.4-3 MW onshore turbine (Vestas V90/V110, GE 2.5, Enercon E-82 class). Each limit
comes from the part that sets it:

| Limit | Part | Value |
|---|---|---|
| Length | 45-55 m blade on an extendable trailer | 60 m |
| Height | bottom tower section, ~4.3 m diameter, on a low-bed | 4.8 m |
| Width | the same tower section | 4.5 m |
| Gross weight | 70-90 t nacelle with tractor and trailer | 120 t |

Values live in `smarthack/transport/constants.py`; change them and rebuild for another
turbine.

## How a road gets its colour

Every motorway, trunk, primary, secondary and tertiary road (with ramps) is read from the
Geofabrik extract. Its tags and its geometry raise reasons:

| Reason | Effect | Rule |
|---|---|---|
| Height limit under 4.8 m | blocks | `maxheight` |
| Width limit under 4.5 m | blocks | `maxwidth` |
| Weight limit under 20 t | blocks | `maxweight`: a weak bridge or road |
| Closed to heavy vehicles | blocks | `hgv=no`, `access=no/private` |
| Weight limit 20-40 t | to check | `maxweight` |
| Bridge with no known capacity | to check | `bridge` on secondary and county roads |
| Tunnel with no known clearance | to check | `tunnel` without `maxheight` |
| Tight curve (radius under 40 m) | to check | geometry, only the ~30 m around the curve |
| Roundabout | to check | `junction=roundabout` |
| County road | to check | `highway=tertiary`: often under 7 m wide |
| Narrow, single-lane, unpaved | to check | `width`, `lanes`, `surface` |
| Length limit, destination only | to check | `maxlength`, `hgv=destination` |

The curve radius is measured on a circle through the points 15 m before and after each
vertex, so the digitising noise of close OSM vertices does not read as a hairpin.

The roads that are not blocked are joined at their shared nodes, and the three entry
ports seed the graph: **Constanța** (sea, where blades and nacelles are unloaded) and the
Danube ports **Galați** and **Brăila** (barge). Each road then gets a verdict:

| Colour | Verdict | Meaning |
|---|---|---|
| Green | Viable | reached from a port, nothing known against the road |
| Amber | To check | reached from a port, something to check on this stretch |
| Red | Blocked | a signed limit or ban stops the vehicle |
| Grey | Isolated | no port reaches it without crossing a blocked road |

The verdict is per road, not per route. A green road may be reached only through amber
stretches, and those amber dots on the way are exactly the points to survey.

The build of 2026-11-08 (OSM data of 2026-11-06), 77,600 km of roads: 61.5 % viable,
31.7 % to check (mostly county roads), 3.9 % blocked, 2.8 % isolated.

## What it cannot tell

- **Bridges.** OSM rarely tags bridge capacity in Romania. "Nothing known against it" is
  not "allowed"; bridges on secondary and county roads are flagged for that reason.
- **Turns at junctions.** Curves are measured along each road, not where two roads meet.
- **Temporary restrictions.** Roadworks, closures and the summer heat bans for vehicles
  over 7.5 t are not in OSM.
- **The last kilometres.** Roads smaller than county roads, and the access road a site
  needs, are out of scope.

## Code

| Layer | Module |
|---|---|
| Pure computation | `smarthack/transport/` (`rules`, `geometry`, `network`, `osm`, `constants`) |
| Download | `smarthack/clients/transport_sources.py` |
| Build and serving | `smarthack/services/transport_service.py` |
| API | `smarthack/api/routes/transport.py` |
| Map | `frontend/src/features/transport/` |

The network file packs each road as `[class, verdict, reasons bitmask, ref index,
[lat, lon, ...]]`. The map draws one canvas multi-polyline per (verdict, class) pair, so
135,000 road pieces draw as about twenty layers; a click finds the nearest road of the
clicked layer.

OSM data © OpenStreetMap contributors, ODbL 1.0.
