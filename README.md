# QuickRoute

QuickRoute is a dynamic indoor-navigation web system for large buildings — hospitals,
campuses, malls, offices. Nothing about it is hard-coded for one building: every
building, floor, destination and navigation graph is created and managed through the
admin UI and stored in MongoDB.

A visitor scans (or types) a QR/location code, picks where they want to go, and gets
step-by-step textual directions — including across floors, via stairs, elevators,
escalators or ramps.

---

## Stack

**Frontend** — React 19 + Vite, plain JavaScript, REST, trilingual UI (Arabic / Hebrew / English)
**Backend** — Python 3.12, FastAPI, Pydantic, Beanie ODM
**Database** — MongoDB Atlas
**Map processing** — PyMuPDF (PDF), Pillow + OpenCV (images)
**Semantic map analysis** — Anthropic Claude (Messages API, streaming)
**Auth** — JWT (HS256) + bcrypt/passlib, role-based access control, invitation codes
**Deployment** — Docker, AWS ECS, S3-backed map storage, CloudFront

---

## Project structure

```txt
QuickRoute/
│
├── backend/
│   ├── app.py                  FastAPI app: lifespan, CORS, /uploads static mount, routers
│   ├── core/                   security (JWT/bcrypt), auth dependencies, error constants
│   ├── database/mongo.py       Mongo client + Beanie document registration
│   ├── models/                 Beanie documents (Building, Map, MapGroup, Room,
│   │                           RoutePoint, RouteEdge, LocationCode, VerticalConnector,
│   │                           User, InvitationCode, SemanticMapAnalysis, ...)
│   ├── schemas/                Pydantic request/response models
│   ├── routes/                 one router per resource
│   ├── logic/                  routing: Dijkstra, multi-floor graph, instruction text
│   ├── services/               map image pipeline, semantic analysis, graph generation,
│   │                           auto-connect, storage backend (local / S3)
│   ├── constants/              destination and route-point type vocabularies
│   ├── prompts/                the single versioned semantic-analysis prompt
│   ├── uploads/maps/           generated + preserved map files (git-ignored)
│   └── tests/                  pytest suite — no real AI or database calls
│
├── frontend/
│   └── src/
│       ├── api/                one module per backend resource
│       ├── context/            Auth, Admin, Lang, Location providers
│       ├── screens/            end-user flow + admin screens
│       ├── components/         shared UI + route guards
│       ├── utils/              pure helpers (each with a *.test.mjs beside it)
│       └── translations/       localization helpers
│
└── README.md
```

---

## Running it locally

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate         # Windows
# source .venv/bin/activate    # macOS / Linux
pip install -r requirements.txt -r requirements-test.txt
cp .env.example .env           # then fill in the values (see "Configuration")
python -m uvicorn app:app --reload --port 8000
```

The API is then at `http://127.0.0.1:8000`, with interactive docs at
`http://127.0.0.1:8000/docs`. `GET /` is the health check.

Generated map images are served from `http://127.0.0.1:8000/uploads/...`.

### Frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
npm run build        # production bundle into dist/
npm run lint
```

`frontend/.env` must define `VITE_API_BASE_URL` (e.g. `http://127.0.0.1:8000`). There is
no built-in fallback — without it every request goes to `undefined/api/...`.

### Tests

```bash
cd backend && pytest tests/ -q
```

No test makes a real Anthropic or OpenAI API call, and none touches a real MongoDB —
the suite runs against an in-memory `mongomock` database.

Frontend helper tests are plain Node scripts:

```bash
cd frontend
node src/utils/roleRouting.test.mjs                            # one file
for f in $(find src -name "*.test.mjs"); do node "$f"; done    # all of them
```

---

## Configuration

All backend settings live in `backend/.env`. Copy `backend/.env.example` and fill it in;
never commit the real `.env` (it is git-ignored). That file carries the full annotated
list. The essentials:

| Variable | Purpose |
|---|---|
| `MONGO_URI`, `DATABASE_NAME` | MongoDB Atlas connection |
| `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | token signing |
| `ANTHROPIC_API_KEY` | semantic map analysis (required for it to run) |
| `ANTHROPIC_MAP_ANALYSIS_MODEL` | optional; falls back to a pinned Claude model |
| `AUTO_ANALYZE_MAPS` | queue an analysis automatically after a map upload |
| `MAP_STORAGE_BACKEND` | `local` (default) or `s3` |
| `CORS_ALLOWED_ORIGINS` | comma-separated; defaults to the Vite dev origins |
| `OPENAI_API_KEY`, `OPENAI_IMAGE_*` | **only** the optional cosmetic display-map recolor |

**On the two AI providers.** Semantic map analysis is Anthropic Claude, and only
Anthropic Claude. OpenAI appears in this project for exactly one unrelated, optional
feature: redrawing an uploaded floor plan as a prettier "display" map
(`services/map_image_service.py`). Leaving `OPENAI_API_KEY` empty simply falls back to
the locally generated display map; nothing about navigation or analysis changes.

---

## How the system works

### End-user flow

1. The visitor scans a QR label or types its code (`/screen/01`).
2. `GET /api/location-codes/resolve/{code}` — public — turns the code into a starting
   `RoutePoint`, plus its building, map and floor.
3. They choose a destination from that building's rooms (`/screen/17`).
4. `POST /api/navigation/multi-floor-route` runs Dijkstra over the RoutePoint/RouteEdge
   graph and returns route segments, totals and localized instructions.
5. The app shows **step-by-step textual directions** (`RouteSteps`). The current product
   decision is instructions-only: route coordinates are returned by the API but are
   deliberately not drawn over a floor-plan image.

### Navigation model

- **RoutePoint** — one navigable node, in original-image pixel coordinates, on one map.
- **RouteEdge** — a connection between two RoutePoints, with a real-world distance.
  A cross-floor edge additionally carries `to_map_id` and a `connector_id`.
- **VerticalConnector** — an elevator/stairwell/escalator/ramp spanning floors. It holds
  no coordinates itself; each floor it serves is a normal RoutePoint tagged with the
  connector. Transition edges between those stops are regenerated automatically.
- **Dijkstra** — `logic/multi_floor_routing.py` is the live implementation, weighted by
  `logic/routing_cost.py` (`shortest` / `fastest` / `accessible`, 1.3 m/s walking speed).
- **Instructions** — `logic/instruction_generator.py` produces `en` / `ar` / `he` steps
  with turn classification, leg merging and floor-transition wording.

### Roles

| Role | Scope |
|---|---|
| `super_admin` | everything, unconditionally |
| `global_manager` | project-wide by default; can be narrowed to specific buildings |
| `building_manager` | only their assigned buildings, and optionally only specific map groups or maps |
| `regular_user` | no admin access; the end-user navigation flow only |

Accounts are created from invitation codes, which carry the role and its scope; a code's
scope can never exceed its issuer's own. See `core/auth_deps.py` for the authoritative
rules, including the three `global_manager` scope shapes.

### Map upload and semantic analysis

1. An admin uploads a PNG / JPG / WEBP / PDF for one floor (or several at once as a
   **map group**).
2. The exact original bytes are copied to `uploads/maps/originals/` **synchronously,
   before the API reports success**, and recorded on `Map.analysis_source_path` — so a
   successful upload always has a durable, analysis-readable source on disk.
3. In the background the file is normalized to `uploads/maps/source/{map_id}.png`
   (PDFs: first page, via PyMuPDF) and a simplified `display` map is produced.
4. If `AUTO_ANALYZE_MAPS` is on, a semantic-analysis job is queued.
5. A single background worker inside the API process claims queued jobs
   (`services/semantic_analysis_worker.py`) and sends the source file to Claude —
   images as image blocks, PDFs as document blocks.
6. The structured result is validated locally, reviewed and corrected by an admin,
   validated again, then published; only published entities can be turned into
   Rooms/RoutePoints.

---

## Deployment

`backend/Dockerfile` builds a non-root Python 3.12 image (with `tesseract-ocr` and the
OpenCV runtime libraries) and serves the app with uvicorn on port 8000; `GET /` is the
health check. `quickroute-express-service.json` is the AWS ECS service definition —
secrets come from SSM Parameter Store, and `MAP_STORAGE_BACKEND=s3` switches map storage
to a private S3 bucket with presigned read URLs. The frontend builds to static files for
S3 + CloudFront.

---

## Legacy endpoints

`backend/routes/navigation_routes.py` still exposes five unprefixed, unauthenticated
endpoints that read the sample JSON files in `backend/data/` — `GET /buildings`,
`/buildings/{id}/rooms`, `/rooms/{id}`, `/graph` and `/route`. They are marked
`deprecated=True`, the UI does not call any of them, and they are **not** part of the
live system: the real equivalents are `/api/locations/buildings`, `/api/rooms` and
`/api/navigation/multi-floor-route`. They are kept only so no old client breaks
unexpectedly, and should be removed once nothing external depends on them.
