# Plan: Wind-Park Map Feature

Implementation plan for the first real feature on top of `FASTAPI_REACT_PLAN.md`: an interactive map of wind parks (stored in Supabase) with clustering, a list drawer, and a details drawer.

---

## 1. Requirements (as specified)

1. Full-screen map showing each park as a clickable dot/pin.
2. Parks that are close together merge into one dot showing the count. Clicking a cluster zooms in.
3. A menu button (three lines) in the top right. Clicking it opens a drawer from the right with the list of parks.
4. Clicking a park (on the map or in the list) opens a details drawer from the right. For now it shows only the coordinates.
5. If a park is chosen from the list, the list drawer closes first, then the details drawer opens.
6. Data: Supabase table with park id, latitude, longitude.

---

## 2. Decisions

| Topic | Decision | Why |
|---|---|---|
| Map library | Leaflet + `react-leaflet` + `react-leaflet-cluster` (wraps `leaflet.markercluster`) | Clustering, "click cluster to zoom", and spiderfying are built in. LLMs know it very well |
| Tiles | OpenStreetMap raster tiles | Free, no API key. Needs internet at demo time |
| Markers | Custom `divIcon` dots styled with Tailwind | Avoids Leaflet's known broken-default-icon problem under Vite, and matches the "dots" look |
| Clustering | Client-side | Under 500 parks, so one fetch holds everything. No bounding-box queries or server-side clustering |
| Data access | Backend reads Supabase via its REST API (PostgREST) using the shared `httpx` client | Keeps the key off the browser and follows the existing `clients/` pattern. No new Python dependency or DB driver |
| Details data | Details drawer reads from the already-loaded parks list | The coordinates are already there. Add `GET /api/parks/{id}` only when real details exist |
| UI state | One small hook (`useDrawerFlow`) owns which drawer is open | The "close first, then open" rule is the only tricky logic, so it lives in one place |
| Map vs drawers | Drawers overlay the map. The map is not resized | Avoids Leaflet `invalidateSize` problems |

Considered and rejected: calling Supabase directly from the browser (puts the key in the client and bypasses the backend's layering), and MapLibre GL (more powerful, but needs a style/tile source and more setup than a 24h build warrants).

---

## 3. Data flow

```text
Supabase (parks table)
   │  GET {SUPABASE_URL}/rest/v1/parks?select=id,latitude,longitude
   ▼
clients/supabase_parks.py      returns raw rows
   ▼
services/parks_service.py      validates rows, skips bad ones, 60s in-memory cache
   ▼
api/routes/parks.py            GET /api/parks  →  [{id, latitude, longitude}]
   ▼  (TanStack Query, cached 5 min)
frontend useParks()  →  ParkMap (pins/clusters)  +  ParkListDrawer  +  ParkDetailsDrawer
```

---

## 4. Backend

### 4.1 Files

```text
smarthack/
├── config.py                      # + supabase_url(), supabase_key(), supabase_parks_table()
├── schemas/parks.py               # Park
├── clients/supabase_parks.py      # fetch_parks(http) -> list[dict]
├── services/parks_service.py      # list_parks(http) -> list[Park]
└── api/routes/parks.py            # GET /api/parks  (registered in api/router.py)
tests/integration/test_parks_api.py
.env.example                       # + Supabase variables
```

The layering ranks from the main plan don't change. This feature uses ranks 1 (schemas), 2 (clients), 3 (services) and 4 (api).

### 4.2 Schema

```python
# smarthack/schemas/parks.py
from pydantic import BaseModel, Field

class Park(BaseModel):
    id: int                                   # use str if the table uses uuid
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
```

### 4.3 Client

```python
# smarthack/clients/supabase_parks.py
import httpx
from smarthack import config

def _headers() -> dict[str, str]:
    key = config.supabase_key()
    headers = {"apikey": key}
    if key.startswith("eyJ"):               # legacy JWT-style anon / service_role key
        headers["Authorization"] = f"Bearer {key}"
    return headers                          # newer sb_publishable_/sb_secret_ keys: apikey only

async def fetch_parks(http: httpx.AsyncClient) -> list[dict]:
    resp = await http.get(
        f"{config.supabase_url()}/rest/v1/{config.supabase_parks_table()}",
        params={"select": "id,latitude,longitude", "order": "id.asc", "limit": 1000},
        headers=_headers(),
    )
    resp.raise_for_status()
    return resp.json()
```

PostgREST returns at most 1000 rows by default. That is more than the under-500 target, but the explicit `limit` documents the assumption.

### 4.4 Service

```python
# smarthack/services/parks_service.py
import logging, time
import httpx
from pydantic import ValidationError
from smarthack.clients import supabase_parks
from smarthack.schemas.parks import Park

logger = logging.getLogger(__name__)
_TTL_SECONDS = 60
_cache: tuple[float, list[Park]] | None = None

async def list_parks(http: httpx.AsyncClient) -> list[Park]:
    global _cache
    now = time.monotonic()
    if _cache and now - _cache[0] < _TTL_SECONDS:
        return _cache[1]
    parks: list[Park] = []
    for row in await supabase_parks.fetch_parks(http):
        try:
            parks.append(Park.model_validate(row))
        except ValidationError:
            logger.warning("Skipping park row with invalid data: id=%s", row.get("id"))
    _cache = (now, parks)
    return parks
```

The service skips rows with missing or out-of-range coordinates, because one bad row would otherwise crash the whole map. The cache protects the demo from Supabase latency and rate limits.

### 4.5 Route

```python
# smarthack/api/routes/parks.py
from typing import Annotated
import httpx
from fastapi import APIRouter, Depends, HTTPException
from smarthack.api.dependencies import get_http_client
from smarthack.schemas.parks import Park
from smarthack.services import parks_service

router = APIRouter(prefix="/parks", tags=["parks"])

@router.get("", response_model=list[Park])
async def get_parks(http: Annotated[httpx.AsyncClient, Depends(get_http_client)]):
    try:
        return await parks_service.list_parks(http)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not load parks") from exc
```

### 4.6 Supabase setup (one-time, in the dashboard)

- Confirm the table name and columns. This plan assumes a table `parks` with `id`, `latitude`, `longitude`. If they differ, set `SUPABASE_PARKS_TABLE` or adjust the `select` string.
- **Row Level Security:** if you use the publishable/anon key, enable RLS with a read policy, or the API returns an empty list with no error:
  ```sql
  alter table parks enable row level security;
  create policy "parks are readable" on parks for select using (true);
  ```
  If you use the secret/service-role key (backend only, never in the frontend), RLS is bypassed. The publishable key plus a read-only policy is the least-privilege choice.
- Add 5 to 10 test parks, including two very close together and two at the exact same coordinates. They exercise clustering and spiderfying.
- **Free-tier projects pause after inactivity.** Wake the project before the demo and again on the morning of presentation day.

### 4.7 Config

```bash
# .env.example
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_KEY=                 # publishable (preferred) or secret key; backend only
SUPABASE_PARKS_TABLE=parks
```

`config.py` stays the only `os.environ` reader. Missing values raise a clear error at startup (check them in `lifespan`) so a typo doesn't surface later as a confusing 502.

### 4.8 Backend tests

In `tests/integration/test_parks_api.py`, mock the Supabase URL with `respx`:
- Returns the expected JSON for valid rows.
- Skips rows with null or out-of-range coordinates, still returns the rest.
- Returns 502 when Supabase fails or times out.
- Clear the service cache between tests (reset `_cache`).

---

## 5. Frontend

### 5.1 Dependencies and files

```bash
cd frontend
npm install leaflet react-leaflet react-leaflet-cluster
npm install -D @types/leaflet
```

Check peer dependencies before committing to versions (`npm view react-leaflet peerDependencies`, same for `react-leaflet-cluster`). `react-leaflet` v5 needs React 19, and the cluster wrapper must support the same major. If they conflict, pick the matching `react-leaflet` major rather than forcing the install.

```text
frontend/src/
├── api/hooks.ts                    # + useParks()
├── main.tsx                        # imports leaflet.css (+ cluster CSS if used)
└── features/map/
    ├── MapPage.tsx                 # layout and wiring; owns useDrawerFlow
    ├── ParkMap.tsx                 # Leaflet map, tiles, clusters, dots, fit-to-bounds
    ├── mapIcons.ts                 # dotIcon, selectedIcon, clusterIcon (divIcon)
    ├── MenuButton.tsx              # three-line button, top right
    ├── Drawer.tsx                  # generic right-side sliding panel
    ├── ParkListDrawer.tsx          # list of parks
    ├── ParkDetailsDrawer.tsx       # coordinates placeholder
    └── useDrawerFlow.ts            # drawer state machine
```

### 5.2 Data hook

```ts
// api/hooks.ts
export function useParks() {
  return useQuery({
    queryKey: ['parks'],
    queryFn: () => api.get<Park[]>('/api/parks'),   // Park from types/api.ts (generated)
    staleTime: 5 * 60_000,
  })
}
```

Run `make types` after the backend schema exists, so `Park` is generated, not hand-written.

### 5.3 The map (`ParkMap.tsx`)

- `MapContainer` fills its parent: `className="h-full w-full"`, with a parent that has explicit height (`h-screen`). A Leaflet map with no height renders as nothing.
- **Isolate the map's stacking context** with `relative isolate` on its wrapper. Leaflet panes and controls use z-indexes up to 1000, which would otherwise draw over the drawers and menu button.
- `TileLayer` with the OSM URL and the required attribution: `&copy; OpenStreetMap contributors`.
- A `FitToParks` child component uses `useMap()` once, when the data first arrives, and calls `map.fitBounds(bounds, { padding: [48, 48] })`. Don't hard-code a map center, and don't re-fit on refetch, or the map will jump while the user is exploring. With one park, use `setView` with a sensible zoom.
- Clustering:

```tsx
<MarkerClusterGroup
  chunkedLoading
  showCoverageOnHover={false}
  maxClusterRadius={50}
  iconCreateFunction={clusterIcon}
>
  {parks.map((p) => (
    <Marker
      key={p.id}
      position={[p.latitude, p.longitude]}
      icon={p.id === selectedId ? selectedIcon : dotIcon}
      eventHandlers={{ click: () => onSelect(p.id) }}
    />
  ))}
</MarkerClusterGroup>
```

  `markercluster` already provides "click a cluster to zoom to its bounds" (`zoomToBoundsOnClick`, on by default) and spiderfies markers at identical coordinates when max zoom is reached.
- `mapIcons.ts`: define icons once at module level (stable references). `dotIcon` is a 16px circle `divIcon` with Tailwind classes. `selectedIcon` is larger and a different color. `clusterIcon` builds a bigger darker circle with the child count, using `cluster.getChildCount()`.
- Clicking empty map space closes any open drawer (`useMapEvents({ click: onBackgroundClick })`). Drop this if you don't like it.
- **Optional polish:** when a park is chosen from the list, `map.flyTo([lat, lng], Math.max(map.getZoom(), 11))` so the pin is visible. It may still be inside a cluster if neighbors are very close. If that bothers you, use the cluster group's `zoomToShowLayer`.

### 5.4 Drawer behavior (`useDrawerFlow.ts`)

State: which drawer is visible, and which park is selected.

```ts
type Open = 'list' | 'details' | null
const DRAWER_ANIM_MS = 300            // must match Tailwind duration-300 on Drawer

export function useDrawerFlow() {
  const [open, setOpen] = useState<Open>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const timer = useRef<number>()

  const afterClose = (fn: () => void) => {
    window.clearTimeout(timer.current)            // newest click wins
    timer.current = window.setTimeout(fn, DRAWER_ANIM_MS)
  }
  useEffect(() => () => window.clearTimeout(timer.current), [])

  return {
    open, selectedId,
    toggleList() {
      if (open === 'list') return this.close()
      if (open === 'details') { setOpen(null); afterClose(() => setOpen('list')) }
      else setOpen('list')
    },
    selectPark(id: number) {                      // pin click or list click
      if (open === 'list') { setOpen(null); afterClose(() => { setSelectedId(id); setOpen('details') }) }
      else { setSelectedId(id); setOpen('details') }   // swap content, or open directly
    },
    close() { window.clearTimeout(timer.current); setOpen(null) },
  }
}
```

Rules this encodes:
- Only one drawer is open at a time. Switching between them always closes the first, waits for the slide-out, then opens the second. That includes pin click while the list is open, and menu click while details are open.
- Selecting another park while details are already open just swaps the content (no close/open cycle).
- `selectedId` is not cleared on close, so the details content doesn't go blank during the slide-out animation.
- Rapid clicks cancel the pending timer, so the latest intent wins.
- Escape closes the open drawer.

Because the timer delay matches the CSS transition by a constant rather than a `transitionend` event, keep `DRAWER_ANIM_MS` and the Tailwind duration in sync (or export one from the other).

### 5.5 Drawer component and screens

`Drawer.tsx` (generic):
- `fixed inset-y-0 right-0 z-30 w-full sm:w-96 bg-white shadow-xl transition-transform duration-300`, with `translate-x-full` when closed and `translate-x-0` when open.
- `role="dialog"`, `aria-label`, a header with a close (X) button, and `inert`/`aria-hidden` while closed so hidden buttons can't take keyboard focus.
- Children render inside a scrollable body (`overflow-y-auto`).

`MenuButton.tsx`: `absolute top-4 right-4 z-20`, three-line icon, `aria-label="Open park list"`. The list drawer covers it when open, and the drawer's own X replaces it.

`ParkListDrawer.tsx`: scrollable list, one row per park labeled `Park #<id>` with its coordinates in small text, the selected park highlighted. Clicking a row calls `selectPark(id)`. When parks get names later, only the row label changes, and a search box can be added.

`ParkDetailsDrawer.tsx`: shows the park looked up by `selectedId` from the loaded list, with title `Park #<id>`, `Latitude` and `Longitude` rows (placeholder as agreed). Leave one clearly marked spot for future details.

### 5.6 Loading, error, empty

- Loading: a centered "Loading parks…" overlay on the map.
- Error: a banner with a Retry button (`refetch`). Show the message from the 502.
- Empty (0 parks): the map still renders, with a small "No parks found" notice.
- The menu button is disabled until data has loaded.

---

## 6. Build order and split (2-3 people)

| Step | Who | What | Est. |
|---|---|---|---|
| 1 | Backend | **Stub first:** `GET /api/parks` returns 8 hard-coded parks in the real schema. Run `make types` and commit | 20 min |
| 2 | Frontend | `ParkMap` with tiles, dots from `useParks()`, fit-to-bounds, clustering, cluster click zoom | 1.5 h |
| 2 | Backend (in parallel) | Supabase table check/RLS/seed data, config, client, service, tests, swap the stub for the real thing | 1.5 h |
| 3 | Frontend | `Drawer`, `MenuButton`, list and details drawers, `useDrawerFlow` | 1.5 h |
| 4 | Both | Connect to the real endpoint, check the acceptance list, error/loading states | 45 min |
| 5 | Both | Polish: icons and colors, `flyTo`, mobile check, demo rehearsal | as time allows |

Because the stub ships in step 1, the frontend never waits on Supabase.

---

## 7. Acceptance checklist

- [ ] The map loads and fits all parks in view on first load.
- [ ] Each park shows as a dot. Clicking one opens the details drawer with its coordinates.
- [ ] Two parks close together appear as one dot with the number 2, and zooming in separates them.
- [ ] Clicking a numbered dot zooms into it (never opens a drawer).
- [ ] Parks at identical coordinates spiderfy at max zoom and can each be clicked.
- [ ] The three-line button is in the top right and opens the list drawer from the right.
- [ ] Choosing a park in the list closes the list first, then opens details after the slide-out.
- [ ] Clicking a pin while the list is open follows the same close-then-open sequence.
- [ ] Clicking another pin while details are open swaps the content without closing.
- [ ] Escape and the X button close the open drawer.
- [ ] Reloading (or `make serve` on a production build) behaves the same.
- [ ] With the backend or Supabase down, the UI shows an error and a Retry button.
- [ ] Works at a phone-width viewport (drawers go full width).

---

## 8. Gotchas

- Leaflet CSS must be imported (`import 'leaflet/dist/leaflet.css'` in `main.tsx`). If you use the default cluster styling, also import `leaflet.markercluster/dist/MarkerCluster.css` and `MarkerCluster.Default.css`. Missing CSS shows up as broken tiles or scattered images.
- The default Leaflet marker icon breaks under Vite. That's why this plan uses `divIcon`, so don't switch to `<Marker>` without an `icon`.
- React `StrictMode` double-mounts components in dev. `react-leaflet` handles it, but custom code that calls `map.fitBounds` in an effect should be idempotent.
- OSM tiles need internet and have a fair-use policy. For a hackathon demo that's fine. If tiles are blocked or rate-limited, swap the URL for another provider (e.g. a free-tier key from Stadia/MapTiler/CARTO).
- Supabase: an empty list with a 200 status almost always means RLS is on with no read policy. Check that before debugging the backend.
- Keep the Supabase key out of `frontend/`. Only `/api/parks` data crosses to the browser.

---

## 9. Assumptions to confirm

1. Table is named `parks`, with columns `id`, `latitude`, `longitude` (and `id` is an integer).
2. Coordinates are WGS84 decimal degrees (normal lat/lng, not a projected system like Stereo70).
3. Clicking empty map space should close open drawers.
4. Park labels are `Park #<id>` until names exist.
5. The backend host can reach Supabase over the internet, and so can the browser for map tiles.

## 10. Later (not now)

Park names and real details (`GET /api/parks/{id}`), search/filter in the list, selected-park URL hash (`#park-12`) for sharing links, marker colors by status or capacity, viewport-based loading if the count grows past a few thousand, and offline tile caching for unreliable demo networks.
