# Plan V2: Map Feature on the Real Tables (park → turbine → today's prediction)

This is a **modification plan** for `MAP_FEATURE_PLAN.md`. The map library, clustering, drawer layout, `useDrawerFlow` hook, build tooling, and layering ranks are all unchanged. What changes is the data layer, the API, and what the details drawer shows.

---

## 1. Goal

- Map shows every wind park as a clickable dot (clusters as before).
- Clicking a park (pin or list) opens the details drawer with **every turbine of that park**, each shown as:

  > `Turbine {id}, status {status}, {daily_fault_probability} for {suspected_subsystem}`

  using the `turbine_mentenance` row whose `predicted_date` is **today**.
- Park list and pin tooltips now show the park **name**.

---

## 2. What changes vs. the previous plan

| Area | Previous plan | Now |
|---|---|---|
| Park source | `parks(id, latitude, longitude)` | `park(id, name, location geography)`, read through a **`park_map` view** that exposes `latitude` / `longitude` |
| `Park` schema | `id, latitude, longitude` | `id, name, latitude, longitude` |
| Endpoints | `GET /api/parks` | `GET /api/parks` **+** `GET /api/parks/{park_id}/turbines` |
| Details drawer | Coordinates placeholder | Turbine list for today (coordinates kept as a small subtitle) |
| Supabase client | `clients/supabase_parks.py` | `clients/supabase.py` with two functions |
| Config | `SUPABASE_PARKS_TABLE` | Removed (table names become constants). Added `SMARTHACK_TIMEZONE` |
| Frontend data | `useParks()` | `useParks()` **+** `useParkTurbines(parkId)` |
| New dependency | none | `tzdata` (Python), so the timezone lookup works on slim containers |

---

## 3. Key design decisions

| Topic | Decision | Why |
|---|---|---|
| Reading `geography` | A SQL **view** `park_map` that converts `location` to `latitude` / `longitude` | PostgREST returns geography columns as an opaque hex string (EWKB), not coordinates. Converting in SQL avoids parsing binary in Python |
| Turbines + today's data | One PostgREST call with an **embedded resource** (`turbine` with its `turbine_mentenance` rows, filtered to today) | One round trip, no custom DB function, and turbines without a prediction today still come back (with an empty list) |
| When to load turbines | **Lazily, per park, on click** | Daily maintenance rows for every turbine in the system may be tens of thousands. The map only needs park names and positions |
| What "today" means | Computed **in the backend** in a configured timezone and sent to Supabase as an explicit date | The database's `current_date` is UTC, which can be a different day from the one the operators are in |
| Sorting | Riskiest first (highest `daily_fault_probability`), turbines with no prediction last | The most useful order for a maintenance view. Done in the service, easy to change |
| Probability display | Percentage with one decimal (`0.124` → `12.4%`) | Reads better than a raw fraction. One formatting function to change if you want the raw value |
| Tables stay as-is | No schema changes to the three tables (the `turbine_mentenance` spelling is kept as is) | The view and indexes are additions only |

---

## 4. Database preparation (Supabase SQL editor, ~20 min)

### 4.1 The map view

```sql
create or replace view public.park_map
with (security_invoker = true) as
select
  id,
  name,
  st_y(location::geometry) as latitude,    -- Y = latitude
  st_x(location::geometry) as longitude    -- X = longitude
from public.park;

grant select on public.park_map to anon;
```

`ST_X` is longitude and `ST_Y` is latitude. Mixing them up puts every park in the ocean. `security_invoker = true` makes the view obey the caller's access rules rather than the owner's.

### 4.2 Indexes (Postgres does not index foreign keys automatically)

```sql
create index if not exists turbine_park_id_idx
  on public.turbine (park_id);

create index if not exists turbine_mentenance_turbine_date_idx
  on public.turbine_mentenance (turbine_id, predicted_date);
```

Optional, if the prediction pipeline guarantees one row per turbine per day, enforce it:
`alter table public.turbine_mentenance add constraint uniq_turbine_day unique (turbine_id, predicted_date);`

### 4.3 Access: pick one

- **Secret key in the backend (simplest).** Keep the key server-side only (it already is, in `.env`). RLS stays as it is.
- **Publishable key + read-only policies (least privilege).** Do this if you'd rather the backend hold a low-privilege key:

  ```sql
  alter table public.park enable row level security;
  alter table public.turbine enable row level security;
  alter table public.turbine_mentenance enable row level security;

  create policy "read park" on public.park for select to anon using (true);
  create policy "read turbine" on public.turbine for select to anon using (true);
  create policy "read maintenance" on public.turbine_mentenance for select to anon using (true);
  ```

Warning: tables created with plain SQL usually have **RLS off**. With RLS off, the publishable key (which is designed to be public) can **read and write** them. If you use the publishable key, you must enable RLS as above.

### 4.4 Seed data for testing

```sql
insert into public.park (name, location) values
  ('Alpha Ridge',  st_setsrid(st_makepoint(28.60, 44.20), 4326)::geography),
  ('Alpha Ridge 2', st_setsrid(st_makepoint(28.61, 44.21), 4326)::geography),  -- very close: clusters
  ('Beta Plains',  st_setsrid(st_makepoint(27.00, 45.10), 4326)::geography);

-- turbines for the first park, then predictions:
--   turbine A: one row for today
--   turbine B: two rows for today (checks "latest entry wins")
--   turbine C: no row for today (checks the "no prediction" display)
--   one park with zero turbines (checks the empty state)
```

Adjust the coordinates to your region, and insert the `turbine` / `turbine_mentenance` rows with `current_date` for `predicted_date`.

### 4.5 Verify with `curl` before writing code

```bash
curl "$SUPABASE_URL/rest/v1/park_map?select=*" -H "apikey: $KEY"

curl "$SUPABASE_URL/rest/v1/turbine?select=id,turbine_mentenance(status,daily_fault_probability)&park_id=eq.1&turbine_mentenance.predicted_date=eq.2026-11-07" -H "apikey: $KEY"
```

If the first returns `[]`, it's RLS. If the second says it can't find a relationship, reload the schema cache with `notify pgrst, 'reload schema';`. For keys starting with `eyJ`, also send `-H "Authorization: Bearer $KEY"`. This 5-minute check de-risks the whole backend.

---

## 5. Backend changes

### 5.1 File changes

```text
smarthack/
├── config.py                      # + timezone(); - supabase_parks_table()
├── constants.py                   # + PARK_VIEW, TURBINE_TABLE, MAINTENANCE_TABLE
├── schemas/parks.py               # Park gains name; + TurbinePrediction, TurbineToday, ParkTurbines
├── clients/supabase.py            # replaces supabase_parks.py (fetch_parks, fetch_turbines_with_predictions)
├── services/parks_service.py      # list_parks (as before) + list_turbines_for_park
├── api/dependencies.py            # + get_today()
└── api/routes/parks.py            # + GET /{park_id}/turbines
pyproject.toml                     # + tzdata
.env.example                       # + SMARTHACK_TIMEZONE; - SUPABASE_PARKS_TABLE
tests/integration/test_parks_api.py
```

### 5.2 Schemas

```python
# smarthack/schemas/parks.py
from datetime import date
from pydantic import BaseModel, Field

class Park(BaseModel):
    id: int
    name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

class TurbinePrediction(BaseModel):
    entry_id: int
    predicted_date: date
    daily_fault_probability: float
    cumulative_fault_probability: float     # returned for later use, not displayed yet
    status: str
    suspected_subsystem: str

class TurbineToday(BaseModel):
    id: int
    prediction: TurbinePrediction | None    # None = no row for today

class ParkTurbines(BaseModel):
    park_id: int
    date: date                              # the "today" the data was selected for
    turbines: list[TurbineToday]
```

### 5.3 Client

```python
# smarthack/clients/supabase.py
from datetime import date
import httpx
from smarthack import config
from smarthack.constants import PARK_VIEW, TURBINE_TABLE, MAINTENANCE_TABLE

def _headers() -> dict[str, str]:
    key = config.supabase_key()
    headers = {"apikey": key}
    if key.startswith("eyJ"):                       # legacy JWT-style keys
        headers["Authorization"] = f"Bearer {key}"
    return headers

def _url(resource: str) -> str:
    return f"{config.supabase_url()}/rest/v1/{resource}"

async def fetch_parks(http: httpx.AsyncClient) -> list[dict]:
    resp = await http.get(
        _url(PARK_VIEW),
        params={"select": "id,name,latitude,longitude", "order": "id.asc", "limit": 1000},
        headers=_headers(),
    )
    resp.raise_for_status()
    return resp.json()

async def fetch_turbines_with_predictions(
    http: httpx.AsyncClient, park_id: int, day: date
) -> list[dict]:
    cols = ("entry_id,predicted_date,daily_fault_probability,"
            "cumulative_fault_probability,status,suspected_subsystem")
    resp = await http.get(
        _url(TURBINE_TABLE),
        params={
            "select": f"id,{MAINTENANCE_TABLE}({cols})",
            "park_id": f"eq.{park_id}",
            f"{MAINTENANCE_TABLE}.predicted_date": f"eq.{day.isoformat()}",  # filters only the embedded rows
            f"{MAINTENANCE_TABLE}.order": "entry_id.desc",                    # newest entry first
            "order": "id.asc",
            "limit": 1000,
        },
        headers=_headers(),
    )
    resp.raise_for_status()
    return resp.json()
```

The date filter on the embedded table does not remove turbines that have no prediction today. They return with an empty list, which is what we want. (Adding `!inner` to the embed would turn it into an inner join and drop them, so don't.)

### 5.4 Service

```python
# smarthack/services/parks_service.py  (list_parks unchanged apart from the name field)
async def list_turbines_for_park(http, park_id: int, day: date) -> ParkTurbines:
    rows = await supabase.fetch_turbines_with_predictions(http, park_id, day)
    turbines: list[TurbineToday] = []
    for row in rows:
        preds = row.get("turbine_mentenance") or []
        prediction = None
        if preds:
            try:
                prediction = TurbinePrediction.model_validate(preds[0])  # newest entry for that day
            except ValidationError:
                logger.warning("Bad maintenance row for turbine %s", row["id"])
        turbines.append(TurbineToday(id=row["id"], prediction=prediction))

    turbines.sort(key=lambda t: (
        t.prediction is None,                                     # no prediction last
        -(t.prediction.daily_fault_probability if t.prediction else 0),
        t.id,
    ))
    return ParkTurbines(park_id=park_id, date=day, turbines=turbines)
```

No cache for turbines. The client (TanStack Query) caches per park, and clicks are infrequent. Keep the 60 s cache on the parks list only.

### 5.5 "Today" and the route

```python
# smarthack/api/dependencies.py
from datetime import date, datetime
from zoneinfo import ZoneInfo
from smarthack import config

def get_today() -> date:
    return datetime.now(ZoneInfo(config.timezone())).date()
```

```python
# smarthack/api/routes/parks.py
@router.get("/{park_id}/turbines", response_model=ParkTurbines)
async def get_park_turbines(
    park_id: int,
    http: Annotated[httpx.AsyncClient, Depends(get_http_client)],
    today: Annotated[date, Depends(get_today)],
):
    try:
        return await parks_service.list_turbines_for_park(http, park_id, today)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not load turbines") from exc
```

`today` is injected, so tests override `get_today` with a fixed date instead of mocking the clock. An unknown `park_id` returns an empty turbine list (not a 404), because the UI only requests ids it got from the park list.

### 5.6 Config

```bash
# .env.example
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_KEY=                      # secret key, or publishable key if RLS is enabled
SMARTHACK_TIMEZONE=UTC             # set to the operators' timezone, e.g. Europe/Bucharest
```

`config.timezone()` defaults to `UTC` and validates the name at startup (`ZoneInfo(name)`), so a typo fails fast.

### 5.7 Backend tests (`respx` + `dependency_overrides`)

- Parks: returns `name`, `latitude`, `longitude`; skips rows with null/out-of-range coordinates.
- Turbines: asserts the request to Supabase carries `park_id=eq.<id>` and `turbine_mentenance.predicted_date=eq.<overridden today>`.
- Turbine with `turbine_mentenance: []` → `prediction: null`.
- Turbine with two rows → the first (newest `entry_id`) is used.
- Sorting: highest probability first, no-prediction last.
- Park with no turbines → `turbines: []`.
- Supabase failure/timeout → 502 on both endpoints.
- `get_today()` with a monkeypatched timezone (a late-evening UTC instant in `Europe/Bucharest` yields the next date).

---

## 6. Frontend changes

### 6.1 Types and hooks

Run `make types` after the backend schemas exist. `Park`, `ParkTurbines`, and `TurbineToday` then come from `types/api.ts`.

```ts
// api/hooks.ts
export function useParkTurbines(parkId: number | null) {
  return useQuery({
    queryKey: ['parks', parkId, 'turbines'],
    queryFn: () => api.get<ParkTurbines>(`/api/parks/${parkId}/turbines`),
    enabled: parkId !== null,
    staleTime: 60_000,
  })
}
```

### 6.2 File changes

```text
frontend/src/features/map/
├── ParkMap.tsx              # + <Tooltip> with the park name on each pin
├── ParkListDrawer.tsx       # rows show park.name; optional name filter box
├── ParkDetailsDrawer.tsx    # title = park name; turbine list for today (was: coordinates)
├── TurbineRow.tsx           # NEW: one turbine line with a status dot
├── formatTurbine.ts         # NEW: the display sentence + percent formatting + status colors
└── useDrawerFlow.ts         # unchanged
```

### 6.3 The display sentence

```ts
// formatTurbine.ts
export function formatTurbine(t: TurbineToday): string {
  const p = t.prediction
  if (!p) return `Turbine ${t.id}, no prediction for today`
  const pct = (p.daily_fault_probability * 100).toFixed(1)
  return `Turbine ${t.id}, status ${p.status}, ${pct}% for ${p.suspected_subsystem}`
}

const STATUS_DOT: Record<string, string> = {
  ok: 'bg-green-500', healthy: 'bg-green-500', normal: 'bg-green-500',
  warning: 'bg-amber-500', watch: 'bg-amber-500',
  critical: 'bg-red-500', fault: 'bg-red-500', alarm: 'bg-red-500',
}
export const statusDot = (status?: string) =>
  STATUS_DOT[status?.toLowerCase() ?? ''] ?? 'bg-slate-400'   // unknown values stay neutral
```

The real `status` values aren't known yet. The text always shows the raw status, and only the dot color depends on this map, so wrong guesses are harmless.

### 6.4 Details drawer behavior

- Header: park name. Subtitle: `lat, lng` (5 decimals) and "Predictions for {data.date}", so the day being shown is always visible.
- Park name and coordinates come from the already-loaded park list (by `selectedId`).
- States:
  - Loading: 3 skeleton rows.
  - Error: message plus a Retry button.
  - Zero turbines: "No turbines registered for this park."
  - Otherwise: a scrollable list, one `TurbineRow` per turbine, with a count ("12 turbines") at the top.
- Switching parks while the drawer is open shows the skeleton for the new park (no stale data from the previous one).
- The list drawer and `useDrawerFlow` behave exactly as before (close list, wait, open details).

### 6.5 List and pins

- List rows: park `name` (primary) with a small `#id`. With names available and up to ~500 parks, add a simple case-insensitive **name filter** above the list (optional, ~15 min).
- Pins: a `<Tooltip>` with the park name on hover (optional, ~10 min).

---

## 7. Build order and split

| Step | Who | What | Est. |
|---|---|---|---|
| 1 | Whoever has Supabase access | Section 4: view, indexes, access choice, seed data, `curl` checks | 30 min |
| 2 | Backend | **Stub first:** both endpoints return fixed data in the new shapes (include a null prediction and an empty park). `make types`, commit | 20 min |
| 3a | Backend | Real client, service, route, config, tests (replace the stubs) | 1 to 1.25 h |
| 3b | Frontend (parallel) | Names in list and tooltips, `useParkTurbines`, `TurbineRow`, new details drawer states | 1 to 1.25 h |
| 4 | Both | Switch to real data, run the checklist, fix formatting and edge cases | 45 min |
| 5 | Both | Polish: status colors once real values are known, name filter, mobile check | as time allows |

---

## 8. Acceptance checklist (delta)

- [ ] Parks appear at the right place (not mirrored or in the sea), each hover shows its name.
- [ ] The list shows park names, and the close-then-open drawer behavior still works.
- [ ] Clicking a park shows every turbine of that park and no turbines of other parks.
- [ ] Each line matches `Turbine {id}, status {status}, {x}% for {subsystem}`.
- [ ] Only today's prediction is shown. Changing `predicted_date` in Supabase to yesterday makes that turbine show "no prediction for today".
- [ ] A turbine with two rows today shows the newest one.
- [ ] A park with no turbines shows the empty message.
- [ ] Riskiest turbines are at the top, and turbines without a prediction are last.
- [ ] Switching from one park to another shows the new park's data, not the old one's.
- [ ] With Supabase unreachable, both the map and the drawer show an error with Retry.
- [ ] Around midnight in the configured timezone, "today" changes to the new date.

---

## 9. Gotchas

- **Geography columns can't be selected directly.** Selecting `location` returns an unreadable hex string. Always go through `park_map`.
- **Longitude first in SQL, latitude first in Leaflet.** `ST_X` is longitude, `ST_Y` is latitude, and Leaflet positions are `[lat, lng]`.
- **RLS off + publishable key = anyone can write.** Enable RLS (section 4.3) or use the secret key.
- **New view not found?** Reload the PostgREST schema cache (`notify pgrst, 'reload schema';`).
- **Table name spelling.** `turbine_mentenance` is used exactly as created. A later rename means changing one constant in `constants.py`.
- **1000-row response cap.** Supabase returns at most 1000 rows per request by default. That's fine for under 500 parks and normal turbine counts, and a park with more than 1000 turbines would be silently truncated.
- **Empty results with a 200 status** almost always means RLS or the wrong date/timezone, not a backend bug. Compare `GET /api/parks/{id}/turbines` (check the returned `date`) with the same `curl` query.
- **Free-tier Supabase pauses** after inactivity. Wake it before the demo.
- Keep the Supabase key out of `frontend/`.

---

## 10. Assumptions to confirm

1. `park.location` is a **point** in WGS84 (lat/lng). If parks are stored as polygons, use `st_centroid(location::geometry)` in the view instead of the raw cast.
2. The **timezone** for "today" is the operators' local zone, not UTC. Set `SMARTHACK_TIMEZONE`.
3. `daily_fault_probability` is a fraction from 0 to 1 (so 0.124 displays as 12.4%).
4. The actual `status` values (to finalize dot colors): please send the list.
5. Showing "no prediction for today" for turbines without a row is the right behavior (versus hiding them).
6. Showing riskiest turbines first is preferred over ordering by id.
7. The three tables only ever grow with new rows; nobody expects `turbine_mentenance` to hold a second row per day on purpose.

---

## 11. Later (not now)

- **Pin color by worst status today.** A view `park_status_today` (park id, max `daily_fault_probability`, worst status) joined into `GET /api/parks` would let the map itself show which parks need attention, and clusters could take the worst color of their children.
- A summary line in the details drawer ("2 critical, 3 warning").
- `cumulative_fault_probability` and a small trend per turbine (needs a history endpoint).
- Date picker to view other days' predictions (the endpoint already takes `today` as a dependency, so it's a small addition).
- Realtime refresh with Supabase Realtime or polling.
