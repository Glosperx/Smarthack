# Plan: FastAPI + React for Smarthack (24h hackathon edition)

This replaces `FASTAPI_REACT_PROPOSAL.md`. It keeps that proposal's strongest ideas (monorepo, OpenAPI-generated types, the layering guard, `config.py` as the only env reader) and cuts everything a 24-hour, 2-3 person build doesn't need.

---

## 1. Decisions

| Topic | Decision | Why |
|---|---|---|
| Repo layout | Monorepo: `smarthack/` (backend) + `frontend/` | One PR changes an endpoint and its UI together |
| Scale | 24h hackathon, 2-3 people | Minimal scaffolding; folders appear when first needed |
| Deployment | FastAPI serves the built React app (single process / optional single container) | Same origin means no CORS and no auth-cookie headaches |
| Data | No database. External APIs, localhost services, and local files | No ORM, no migrations, no `repositories/` layer |
| Auth | None | No auth code, no secrets handling beyond upstream API keys |
| Styling | Tailwind CSS v4 only | Most LLM-fluent option; no component copying or CLI setup. shadcn/ui can be added per-component later if needed |
| Server state | TanStack Query | Loading/error/retry handling for free, and LLMs write it reliably |
| Routing | React Router (declarative mode), added only once there is a second page | A single-screen demo doesn't need a router |
| API style | `async def` handlers + one shared `httpx.AsyncClient` | Most work is waiting on other services; async handles that without threads |
| API versioning | None. Routes live under `/api` | `/api/v1/...` is overhead for a throwaway API |
| Contract | TS types generated from a committed `openapi.json` | Frontend can work without the backend running |

---

## 2. Directory tree

Only what is needed on day one. Everything marked *(on demand)* is created when the first feature needs it.

```text
Smarthack/
├── smarthack/
│   ├── __init__.py
│   ├── __main__.py              # Entry point: runs Uvicorn
│   ├── config.py                # ONLY reader of os.environ (typed accessors)
│   ├── constants.py
│   ├── utils/                   # logging_utils.py, optional_imports.py
│   ├── schemas/                 # Pydantic models = the API contract
│   │   ├── __init__.py
│   │   └── <feature>.py         # (on demand) request/response models
│   ├── clients/                 # (on demand) thin wrappers over external APIs,
│   │   └── <service>.py         #   localhost services, and file reads
│   ├── services/                # (on demand) logic that combines clients; skip if a
│   │   └── <feature>_service.py #   route is a simple passthrough
│   └── api/
│       ├── __init__.py
│       ├── app.py               # create_app() factory + lifespan
│       ├── spa.py               # SPA static serving + fallback
│       ├── dependencies.py      # get_http_client(), etc.
│       ├── router.py            # Aggregates all route modules
│       └── routes/
│           ├── health.py        # GET /api/health
│           └── <feature>.py     # (on demand) one file per resource
│
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts           # React + Tailwind plugins, /api dev proxy
│   ├── openapi.json             # Committed; generated from the backend
│   └── src/
│       ├── main.tsx             # Root render, QueryClientProvider
│       ├── App.tsx
│       ├── index.css            # @import "tailwindcss";
│       ├── api/
│       │   ├── client.ts        # Typed fetch wrapper
│       │   └── hooks.ts         # TanStack Query hooks (split per resource if it grows)
│       ├── components/          # Shared components
│       ├── pages/               # (on demand) one file per page
│       └── types/api.ts         # GENERATED, committed, never edited by hand
│
├── data/                        # (on demand) local files the backend reads
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_layering.py     # Existing guard, updated RANKS
│   │   └── test_module_docstrings.py
│   └── integration/
│       └── test_api.py          # TestClient smoke tests + mocked upstreams
├── Dockerfile                   # (optional) only if you need to deploy
├── Makefile
├── .env.example
└── pyproject.toml
```

What's deliberately gone from the original tree: `features/`, `components/ui` + `layout`, `hooks/`, `v1/endpoints/`, per-layer unit-test folders, `docs/serving.md`, and any database/ORM layer.

---

## 3. Layering

Update `RANKS` in `tests/unit/test_layering.py`. `clients` and `services` are optional but reserve their ranks now so adding them later doesn't require touching the guard.

| Rank | Module | May import from | Responsibility |
|---|---|---|---|
| 0 | `config`, `constants`, `utils` | rank 0 only | Env vars, logging, scalars |
| 1 | `schemas` | 0 | Pydantic models (the API contract) |
| 2 | `clients` | 0, 1 | One module per external service or file source. Takes an `httpx.AsyncClient` as an argument and returns schema objects, so it is easy to mock |
| 3 | `services` | 0, 1, 2 | Combines clients into feature logic. No HTTP-framework imports |
| 4 | `api` | 0-3 | FastAPI app, routes, dependencies. Routes may call `clients` directly when there's no logic to add |
| 5 | `__main__` | 0-4 | Starts Uvicorn |

Rule of thumb for the team: **routes stay thin** (parse, call, return). If a route grows past ~20 lines, move the logic down into a service.

---

## 4. Backend details

### 4.1 App factory and entry points

One convention, used everywhere: `create_app()` is a factory.

```python
# smarthack/api/app.py
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI
from smarthack import config
from smarthack.api.router import api_router
from smarthack.api.spa import mount_spa

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=config.http_timeout())
    yield
    await app.state.http.aclose()

def create_app() -> FastAPI:
    app = FastAPI(
        title="Smarthack",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.include_router(api_router, prefix="/api")   # API first
    mount_spa(app, config.frontend_dist_dir())      # SPA catch-all last
    return app
```

- Dev: `uvicorn smarthack.api.app:create_app --factory --reload --port 8000`
- Prod / demo: `python -m smarthack` (which calls `uvicorn.run("smarthack.api.app:create_app", factory=True, host=..., port=...)`)
- Tests: `TestClient(create_app())`

### 4.2 Serving the React build (with SPA fallback)

`StaticFiles(html=True)` alone returns a 404 on refresh for any client-side route such as `/settings`. Use an explicit fallback instead:

```python
# smarthack/api/spa.py
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

def mount_spa(app: FastAPI, dist: Path) -> None:
    index = dist / "index.html"
    if not index.exists():
        return  # Dev mode: Vite serves the frontend on :5173

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)  # JSON 404 for unknown API paths
        candidate = (dist / full_path).resolve()
        if candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)         # favicon.ico, etc.
        return FileResponse(index)                 # everything else -> React
```

The dist path comes from `config.frontend_dist_dir()` (env `SMARTHACK_FRONTEND_DIST`, default `<repo>/frontend/dist`) rather than a hard-coded relative path, so it still works when the process starts from another directory or inside a container.

### 4.3 Calling other services

All outbound calls follow the same pattern so teammates (and LLMs) copy it:

```python
# smarthack/clients/example_service.py
import httpx
from smarthack import config
from smarthack.schemas.example import ExampleResult

async def fetch_example(http: httpx.AsyncClient, query: str) -> ExampleResult:
    resp = await http.get(f"{config.example_service_url()}/search", params={"q": query})
    resp.raise_for_status()
    return ExampleResult.model_validate(resp.json())
```

```python
# smarthack/api/dependencies.py
from fastapi import Request
import httpx

def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http
```

```python
# smarthack/api/routes/example.py
from typing import Annotated
import httpx
from fastapi import APIRouter, Depends, HTTPException
from smarthack.api.dependencies import get_http_client
from smarthack.clients import example_service
from smarthack.schemas.example import ExampleResult

router = APIRouter(prefix="/example", tags=["example"])

@router.get("", response_model=ExampleResult)
async def get_example(q: str, http: Annotated[httpx.AsyncClient, Depends(get_http_client)]):
    try:
        return await example_service.fetch_example(http, q)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream failed: {exc}") from exc
```

Conventions:
- **Always set timeouts** (default in `config.http_timeout()`). A hung upstream will otherwise hang the demo.
- Map upstream failures to **502/504** with a readable message so the UI can show something useful.
- If an upstream is slow or LLM-like, stream with `StreamingResponse` (SSE) rather than making the UI wait. Add this only if a feature needs it.
- Local files: read them through a `clients/` module, with the base directory from `config.data_dir()`.

### 4.4 Configuration

`config.py` stays the only `os.environ` reader. Starter accessors and their `.env.example` entries:

```bash
SMARTHACK_HOST=127.0.0.1             # use 0.0.0.0 inside Docker
SMARTHACK_PORT=8000
SMARTHACK_FRONTEND_DIST=             # optional override
SMARTHACK_HTTP_TIMEOUT=30
SMARTHACK_DATA_DIR=./data
SMARTHACK_EXAMPLE_SERVICE_URL=http://localhost:9000
EXAMPLE_API_KEY=                     # upstream keys, never sent to the browser
```

No CORS middleware: in dev the Vite proxy makes browser requests same-origin, and in production FastAPI serves the UI itself. Upstream API keys live only on the server.

---

## 5. Frontend details

**Stack:** React + TypeScript (strict) + Vite + Tailwind v4 + TanStack Query.

```ts
// frontend/vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
```

`src/index.css` is a single line: `@import "tailwindcss";`. No `tailwind.config.js` and no PostCSS config.

### Contract generation (no running server needed)

```make
types:
	python -c "import json; from smarthack.api.app import create_app; print(json.dumps(create_app().openapi()))" > frontend/openapi.json
	cd frontend && npx openapi-typescript openapi.json -o src/types/api.ts
```

Both `openapi.json` and `src/types/api.ts` are committed. Whoever changes a Pydantic model or route runs `make types` in the same commit. The frontend dev can then work from the committed types even if the backend is broken or half-written.

### API client and hooks

`api/client.ts` is a small typed `fetch` wrapper that throws on non-2xx. `api/hooks.ts` holds one `useQuery`/`useMutation` per endpoint, typed from `types/api.ts`. This hand-written layer is about 50 lines, so skip `orval`-style hook generators; their setup costs more than they save in 24h.

---

## 6. Makefile

```make
.PHONY: install dev dev-api dev-web types build serve check

install:
	pip install -e ".[dev]"
	cd frontend && npm install

dev:                       # both servers; open http://localhost:5173
	$(MAKE) -j2 dev-api dev-web

dev-api:
	uvicorn smarthack.api.app:create_app --factory --reload --port 8000

dev-web:
	cd frontend && npm run dev

types:
	python -c "import json; from smarthack.api.app import create_app; print(json.dumps(create_app().openapi()))" > frontend/openapi.json
	cd frontend && npx openapi-typescript openapi.json -o src/types/api.ts

build:
	cd frontend && npm run build

serve: build               # demo mode: one process on http://localhost:8000
	python -m smarthack

check:
	ruff check . && pytest -q && cd frontend && npx tsc --noEmit
```

---

## 7. Testing (minimal on purpose)

- Keep `test_layering.py` and `test_module_docstrings.py` green: they are cheap and catch import drift.
- `tests/integration/test_api.py`: use `TestClient(create_app())` to check `GET /api/health`, and one test per upstream-backed route with the upstream mocked (`respx` for `httpx`, or `app.dependency_overrides`).
- No frontend tests. Use `tsc --noEmit` as the frontend safety net.
- Run `make check` before every merge to the shared branch.

---

## 8. Deployment

**For the demo itself:** `make serve` on the demo machine is enough. One process, one port, and localhost upstreams just work.

**If you need a hosted URL**, use a single container. Do this only after the app works locally:

```dockerfile
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY smarthack ./smarthack
RUN pip install --no-cache-dir .
COPY --from=web /web/dist /app/frontend_dist
ENV SMARTHACK_FRONTEND_DIST=/app/frontend_dist \
    SMARTHACK_HOST=0.0.0.0
EXPOSE 8000
CMD ["python", "-m", "smarthack"]
```

Gotcha: inside a container, `localhost` is the container, not your laptop. To reach other localhost services, point the `SMARTHACK_*_URL` variables at `host.docker.internal` (or run everything in one compose file).

---

## 9. Working in parallel (2-3 people)

The plan only works if the contract is fixed early. Do the first hour together, then split.

**Hour 0-1: skeleton (everyone, or one person while others read the upstream APIs)**
- Backend: `config.py`, `create_app()`, `health` route, one **stub** feature route returning hard-coded data in its real Pydantic shape.
- Frontend: Vite + Tailwind + TanStack Query scaffold, one page calling the stub.
- Run `make types`, `make dev`, and confirm the stub shows up in the browser. Commit.

**Hours 1-18: split by seam, not by layer**

| Person | Owns |
|---|---|
| A (backend) | `clients/` + `services/` + real route logic, replacing stubs without changing schemas |
| B (frontend) | Pages and components against the stubbed endpoints |
| C (3rd person, if any) | Whichever side is behind, plus the demo script, seed data, error states, README |

Rules: schema changes are announced in chat and followed by `make types` in the same commit. Commit small and rebase often, because `openapi.json` and `types/api.ts` are the likeliest merge conflicts: on conflict, just re-run `make types`.

**Hours 18-22: integration and polish.** Run `make serve`, test the production build (not just the dev server), fix error and empty states, and rehearse the demo.

**Hours 22-24: freeze.** Bug fixes only. Record a backup video of the demo in case an external API fails live.

---

## 10. LLM-friendly conventions

Since much of the code will be LLM-generated, make the right pattern easy to copy:

- Keep **one reference example** per layer (the `example` client, route, and hook above) and tell the LLM to "follow the existing example."
- One resource per file, one component per file, explicit names. Avoid clever abstractions.
- Paste the relevant Pydantic schema or the generated `types/api.ts` section into prompts when asking for UI work, and the route + schema when asking for tests.
- Add a short `CLAUDE.md` / `AGENTS.md` at the repo root stating: the layering ranks, "routes are thin," "never read `os.environ` outside `config.py`," "run `make types` after schema changes," and "Tailwind utility classes only, no custom CSS files."

---

## 11. Deferred (add only if the project survives the weekend)

Database + migrations, auth, API versioning, `features/`-sliced frontend structure, shadcn/ui or another component library, generated hooks (`orval` / `@hey-api/openapi-ts`), frontend tests (Vitest), CI that fails on a stale `openapi.json`, decoupled frontend hosting + CORS, and TanStack Router.

---

## 12. Assumptions to confirm

1. The upstream services are reachable from the machine that runs the demo (and the demo has network access, if any are external).
2. Python 3.12+ and Node 20+ are available to everyone.
3. The existing repo already has `config.py`, `constants.py`, `utils/`, and the layering test, so this plan adds `schemas/`, `clients/`, `services/`, `api/` and updates `RANKS`.
4. Upstream calls are request/response. If any need streaming (LLM tokens, long jobs), add an SSE route and `EventSource` usage on the frontend.
