# QuickRoute

**Dynamic indoor-navigation platform for large buildings — hospitals, campuses, malls and offices.**

QuickRoute turns an ordinary floor plan into a navigable graph. A visitor scans (or types) a
QR/location code, picks a destination, and receives step-by-step textual directions — including
across floors, via stairs, elevators, escalators or ramps. Nothing is hard-coded for a single
building: every building, floor, destination, route point and edge is created and managed through
the admin UI and stored in MongoDB.

---

## Table of contents

- [Problem statement](#problem-statement)
- [Main goal](#main-goal)
- [Key features](#key-features)
- [Technology stack](#technology-stack)
- [System architecture](#system-architecture)
- [Project structure](#project-structure)
- [Main components](#main-components)
- [How the system works](#how-the-system-works)
- [Installation and setup](#installation-and-setup)
- [Environment variables](#environment-variables)
- [Running the backend](#running-the-backend)
- [Running the frontend](#running-the-frontend)
- [Database setup](#database-setup)
- [API documentation](#api-documentation)
- [API reference](#api-reference)
- [Authentication and authorization](#authentication-and-authorization)
- [Testing](#testing)
- [Deployment](#deployment)
- [CI/CD — GitHub Actions](#cicd--github-actions)
- [AWS services used](#aws-services-used)
- [Usage guide](#usage-guide)
- [Example workflow](#example-workflow)
- [Legacy endpoints](#legacy-endpoints)
- [Contributors](#contributors)
- [License](#license)

---

## Problem statement

Large public buildings are hard to navigate. Outdoor map services stop at the front door, and the
usual in-building answer — printed signage and static "you are here" boards — cannot express a
route, cannot adapt when a department moves, and cannot speak the visitor's language. Building
operators are left with two bad options: pay for a bespoke, per-building indoor-navigation
deployment, or leave visitors to ask directions at a reception desk.

The technical obstacle behind that gap is data entry. An indoor route requires a navigation graph —
nodes, edges, real-world distances, floor transitions — and hand-digitizing one from a floor plan is
slow, error-prone work that has to be redone for every floor of every building.

## Main goal

Provide a **generic, building-agnostic indoor navigation system** in which a non-technical
administrator can upload a floor plan, have the system extract and place its rooms and corridors
semi-automatically, review the result, and publish working multi-floor navigation — while visitors
get localized, step-by-step directions from any QR code in the building.

---

## Key features

**For visitors**

- QR / location-code entry — scan with the device camera (`jsqr`) or type the code manually.
- Building and destination selection driven entirely by live database content.
- Multi-floor route calculation with step-by-step textual instructions.
- Three optimization modes: `shortest`, `fastest`, `accessible` (accessible mode excludes edges not
  flagged as accessible).
- Preference for a vertical transport type (e.g. elevator over stairs) when several are available.
- Trilingual UI and instructions: English, Arabic and Hebrew.

**For administrators**

- Building, map-group (multi-floor building) and per-floor map management.
- Map upload for PNG / JPG / WEBP / PDF, with background normalization and display-map generation.
- **AI semantic map analysis** — the uploaded plan is sent to Anthropic Claude, which returns a
  structured description of rooms, corridors and connectors; the result is reviewed and corrected by
  an admin, validated, and only then published.
- Automatic corridor-graph generation, destination auto-placement and auto-connection of
  destinations to the corridor network, each with a **preview → apply** pair of endpoints.
- Manual route-point and route-edge editing on top of the floor plan.
- Vertical connectors (elevator / stairs / escalator / ramp) spanning floors, with automatically
  regenerated transition edges.
- Map scale calibration (pixels → metres), copyable between floors, with automatic edge-distance
  recalculation.
- Location codes and printable QR labels (`qrcode`) bound to a specific route point.
- Invitation-code-based account creation, role-scoped user administration, and navigation-data
  cleanup/reset tooling.
- OCR-assisted destination naming (`pytesseract`, degrades gracefully when the Tesseract binary is
  absent).

---

## Technology stack

| Layer | Technology |
|---|---|
| Frontend | React 19, React Router 7, Vite 8, plain JavaScript (no TypeScript), CSS modules-free plain CSS |
| Backend | Python 3.12, FastAPI, Pydantic, Beanie ODM, Uvicorn |
| Database | MongoDB (Beanie documents; MongoDB Atlas in production) |
| Auth | JWT (PyJWT, HS256) + bcrypt via passlib |
| Map processing | PyMuPDF (PDF rendering), Pillow, OpenCV, NumPy |
| AI | Anthropic Claude — Messages API (semantic map analysis); OpenAI — optional cosmetic display-map generation only |
| OCR | pytesseract + system `tesseract-ocr` |
| Storage | Local disk or Amazon S3 (`boto3`), selected at runtime |
| QR | `jsqr` (scanning), `qrcode` (label generation) |
| Tests | pytest, pytest-asyncio, httpx, mongomock_motor (backend); dependency-free Node `*.test.mjs` scripts (frontend) |
| Container / deploy | Docker, Amazon ECR, Amazon ECS, S3 + CloudFront, GitHub Actions |

---

## System architecture

```
                    ┌───────────────────────────────────────────┐
   Visitor / Admin  │  React 19 SPA (Vite build)                │
   browser          │  screens · contexts · src/api/* modules   │
                    └───────────────┬───────────────────────────┘
                                    │  REST + JSON
                                    │  Authorization: Bearer <JWT>
                                    │  (VITE_API_BASE_URL)
                    ┌───────────────▼───────────────────────────┐
                    │  FastAPI application (backend/app.py)     │
                    │  CORS · request-logging middleware        │
                    │  /uploads static mount · lifespan hooks   │
                    ├───────────────────────────────────────────┤
                    │  routes/    16 routers, one per resource  │
                    │  schemas/   Pydantic request/response     │
                    │  core/      JWT security · auth deps      │
                    │  logic/     Dijkstra · instructions       │
                    │  services/  map pipeline · semantic AI    │
                    │  models/    Beanie documents              │
                    └──────┬──────────────┬─────────────┬───────┘
                           │              │             │
                   ┌───────▼──────┐ ┌─────▼──────┐ ┌────▼─────────┐
                   │  MongoDB     │ │ Map files  │ │ Anthropic    │
                   │  (Beanie)    │ │ local disk │ │ Claude API   │
                   │              │ │ or S3      │ │ (background  │
                   │              │ │            │ │  worker)     │
                   └──────────────┘ └────────────┘ └──────────────┘
```

**Frontend.** A single-page React application. `src/api/*.js` wraps every backend resource; all JSON
calls funnel through `apiRequest()` in `src/api/api.js`, which attaches the stored JWT and clears the
session on a 401. Cross-cutting state lives in four context providers — `AuthContext` (token/user),
`AdminContext` (admin working scope), `LangContext` (en/ar/he), `LocationContext` (resolved starting
point). Route paths are defined once in `src/config/routes.js` and `src/utils/adminNavigation.js`;
`RequireRole`, `RequireGlobalAdmin` and `RequireSuperAdmin` guard admin areas client-side.

**Backend.** `app.py` builds the FastAPI app, configures CORS from `CORS_ALLOWED_ORIGINS`, installs
a request-logging middleware that stamps an `X-Request-ID` on every response, mounts generated map
files at `/uploads`, and registers the 16 routers. Its lifespan handler initializes MongoDB/Beanie
and starts a single in-process background worker for semantic analysis jobs. Layering is strict:
`routes/` (HTTP + authorization) → `services/` (map, graph and AI pipelines) or `logic/` (routing,
auth, invitation rules) → `models/` (Beanie documents).

**Database.** MongoDB accessed through Beanie. `database/mongo.py` registers thirteen document
models: `User`, `InvitationCode`, `Building`, `Map`, `MapGroup`, `Room`, `RoutePoint`, `RouteEdge`,
`LocationCode`, `VerticalConnector`, `SemanticMapAnalysis`, `SemanticMapPublication` and
`SemanticEntity`.

**Map storage.** `services/storage_backend.py` selects local disk (`backend/uploads/`) or a private
S3 bucket with presigned read URLs, based on `MAP_STORAGE_BACKEND`.

---

## Project structure

```
QuickRoute/
├── .github/workflows/
│   └── deploy-aws.yml               CI/CD: build → ECR → ECS, build → S3 → CloudFront
├── backend/
│   ├── app.py                       FastAPI app: logging, CORS, /uploads mount, routers, lifespan
│   ├── Dockerfile                   Python 3.12-slim image, non-root user, uvicorn on :8000
│   ├── pytest.ini                   asyncio_mode = auto
│   ├── requirements.txt             runtime dependencies
│   ├── requirements-test.txt        test-only dependencies
│   ├── .env.example                 annotated template for backend/.env
│   ├── constants/                   destination and route-point type vocabularies
│   ├── core/                        security.py (JWT + bcrypt), auth_deps.py (RBAC), errors.py
│   ├── data/                        sample JSON used only by the deprecated legacy endpoints
│   ├── database/mongo.py            Mongo client + Beanie document registration
│   ├── logic/                       routing, instruction generation, auth and invitation rules
│   ├── models/                      12 Beanie document modules
│   ├── prompts/                     versioned semantic-analysis prompt
│   ├── routes/                      16 routers, one per resource
│   ├── schemas/                     Pydantic request/response models
│   ├── services/                    32 service modules: map pipeline, graph generation, AI, storage
│   ├── tests/                       50 pytest modules
│   └── uploads/maps/                generated and preserved map files (git-ignored)
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── cloudfront-distribution.json
│   ├── frontend-bucket-policy.json
│   ├── public/                      favicon, icon sprite, sample map image
│   └── src/
│       ├── api/                     one module per backend resource
│       ├── assets/
│       ├── components/              shared UI, route guards, dashboard primitives
│       ├── config/                  routes.js, publicUrl.js
│       ├── constants/
│       ├── context/                 Auth, Admin, Lang, Location providers
│       ├── data/
│       ├── screens/                 end-user flow + admin screens (incl. admin/ workspaces)
│       ├── styles/
│       ├── translations/            en / ar / he strings
│       ├── utils/                   pure helpers, each with a *.test.mjs beside it
│       ├── App.jsx
│       └── main.jsx
├── eslint.config.js
├── quickroute-express-service.json  AWS ECS Express service definition
├── QuickRoute_Complete_Code_Audit.md
└── README.md
```

---

## Main components

| Component | Location | Responsibility |
|---|---|---|
| Auth & RBAC | `backend/core/security.py`, `backend/core/auth_deps.py`, `backend/logic/auth_logic.py` | JWT issue/verify, bcrypt hashing, role and building/map-group/map scope enforcement |
| Invitation codes | `backend/logic/invitation_code_logic.py`, `routes/invitation_code_routes.py` | Minting, validating, reserving and revoking codes; a code's scope can never exceed its issuer's |
| Map pipeline | `backend/services/map_image_service.py`, `map_label_extraction_service.py`, `ocr_service.py` | Upload handling, PDF/image normalization, display-map generation, label/OCR extraction |
| Semantic analysis | `backend/services/semantic_analysis_service.py`, `semantic_analysis_worker.py`, `semantic_publication_service.py`, `prompts/` | Queue, run and retry Claude analyses; validate, review and publish semantic entities |
| Graph generation | `backend/services/corridor_graph_service.py`, `graph_generation_service.py`, `graph_connection_service.py`, `graph_connectivity_service.py` | Derive corridor nodes/edges from a plan, connect them, check connectivity |
| Destination placement | `backend/services/destination_auto_placement_service.py`, `destination_attachment_service.py`, `auto_connect_destinations_service.py` | Place destinations on the graph and attach them to the nearest usable corridor |
| Routing | `backend/logic/multi_floor_graph.py`, `multi_floor_routing.py`, `routing_cost.py`, `route_calculator.py` | Build the multi-floor graph and run Dijkstra under the selected cost model |
| Instructions | `backend/logic/instruction_generator.py` | Turn a path into localized `en`/`ar`/`he` steps with turn classification and leg merging |
| Vertical connectors | `backend/services/vertical_connector_service.py`, `routes/vertical_connectors_routes.py` | Elevators/stairs/escalators/ramps and their per-floor stops |
| Storage abstraction | `backend/services/storage_backend.py` | Local-disk or S3 map storage, presigned URLs |
| Frontend API layer | `frontend/src/api/` | One module per resource, all sharing `apiRequest()` |
| Frontend navigation UI | `frontend/src/screens/IndoorNavigationScreen.jsx`, `components/RouteSteps.jsx`, `NavigationRouteMap.jsx` | Active navigation, step list, route rendering |
| Admin workspaces | `frontend/src/screens/admin/`, `screens/Admin*.jsx`, `components/dashboard/` | Building/floor workspaces, map tools, users & access, cleanup |

---

## How the system works

### Visitor flow

1. The visitor opens `/start` — by scanning a QuickRoute QR label
   (`{VITE_PUBLIC_FRONTEND_URL}/?locationCode=<code>`) or by typing the code.
2. `GET /api/location-codes/resolve/{code}` (public) turns the code into a starting `RoutePoint`,
   plus its building, map and floor.
3. `/buildings` and `/destinations` list what is actually published for that building.
4. `POST /api/navigation/multi-floor-route` runs Dijkstra over the `RoutePoint`/`RouteEdge` graph and
   returns route segments, totals and localized instructions.
5. `/navigation` renders the step-by-step directions.

### Navigation model

- **RoutePoint** — one navigable node, stored in original-image pixel coordinates, belonging to one
  map (floor).
- **RouteEdge** — a connection between two route points carrying a real-world distance. A cross-floor
  edge additionally carries `to_map_id` and a `connector_id`.
- **VerticalConnector** — an elevator, stairwell, escalator or ramp spanning floors. It holds no
  coordinates of its own; each floor it serves is a normal route point tagged with the connector, and
  the transition edges between those stops are regenerated automatically.
- **Cost model** — `logic/routing_cost.py`: `shortest` and `accessible` minimize physical distance,
  `fastest` minimizes estimated time at a walking speed of 1.3 m/s; `accessible` additionally
  excludes edges not flagged accessible.
- **Instructions** — `logic/instruction_generator.py` emits `en`/`ar`/`he` steps with turn
  classification, leg merging and floor-transition wording.

### Map upload and semantic analysis

1. An admin uploads a PNG / JPG / WEBP / PDF for one floor, or several floors at once as a **map
   group**.
2. The original bytes are preserved before the API reports success, so a successful upload always has
   a durable, analysis-readable source.
3. In the background the file is normalized to a PNG source (PDFs are rendered with PyMuPDF at
   `MAP_PDF_RENDER_DPI`) and a simplified *display* map is produced.
4. If `AUTO_ANALYZE_MAPS` is enabled, a semantic-analysis job is queued; otherwise an admin presses
   **Start Analysis**.
5. The in-process worker (`services/semantic_analysis_worker.py`) claims queued jobs and sends the
   source to Claude — images as image blocks, PDFs as document blocks — retrying transient failures
   up to `SEMANTIC_ANALYSIS_MAX_RETRIES` times and requeuing jobs stale beyond
   `SEMANTIC_ANALYSIS_JOB_TIMEOUT_SECONDS`.
6. The structured result is validated locally, reviewed and corrected by an admin, validated again,
   then published. Only published entities can be turned into rooms and route points.

---

## Installation and setup

### Prerequisites

- Python 3.12
- Node.js 22 (the version used by CI) and npm
- A MongoDB instance or MongoDB Atlas cluster
- Optional: `tesseract-ocr` on the system path, for OCR-assisted destination naming
- Optional: Docker, for the containerized backend

### Clone

```bash
git clone <repository-url>
cd QuickRoute
```

---

## Environment variables

Backend settings live in `backend/.env`. Copy the annotated template and fill it in — the real
`.env` is git-ignored and must never be committed.

```bash
cd backend
cp .env.example .env
```

Variable **names** only; see `backend/.env.example` for the full annotated list.

| Variable | Purpose |
|---|---|
| `MONGO_URI` | MongoDB connection string. Falls back to `mongodb://localhost:27017` when unset |
| `DATABASE_NAME` | Database name (defaults to `quickroute_db`) |
| `JWT_SECRET_KEY` | Token signing secret. **Must** be set in every real environment — otherwise a random per-process key is generated and tokens are invalidated on restart |
| `JWT_ALGORITHM` | Defaults to `HS256` |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Access-token lifetime in minutes |
| `CORS_ALLOWED_ORIGINS` | Comma-separated browser origins. Unset falls back to the Vite dev origins (`5173`/`5174`) |
| `ANTHROPIC_API_KEY` | Required for semantic map analysis |
| `ANTHROPIC_MAP_ANALYSIS_MODEL` | Claude model id for analysis; blank falls back to the service default |
| `AUTO_ANALYZE_MAPS` | Queue an analysis automatically after a successful map upload |
| `SEMANTIC_ANALYSIS_MAX_RETRIES` | Extra attempts before a job is marked permanently failed |
| `SEMANTIC_ANALYSIS_JOB_TIMEOUT_SECONDS` | After this, a claimed job is treated as stale and requeued |
| `SEMANTIC_ANALYSIS_MAX_OUTPUT_TOKENS` | `max_tokens` for the analysis call |
| `SEMANTIC_ANALYSIS_STRICT_SCHEMA` | Read, reserved for a future strict-schema mode |
| `MAP_IMAGE_MAX_EDGE` | Longest-edge downscale limit for images sent to Claude (PDFs exempt) |
| `MAP_MAX_UPLOAD_SIZE_MB` | Upload size limit |
| `MAP_PDF_RENDER_DPI` | DPI used when rendering PDF pages |
| `AI_EDGE_SCORE_THRESHOLD` | Score threshold used when accepting generated edges |
| `MAP_STORAGE_BACKEND` | `local` (default) or `s3` |
| `AWS_S3_BUCKET`, `AWS_REGION` | Target bucket and region when `MAP_STORAGE_BACKEND=s3` |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Explicit credentials for local development only; ECS uses IAM task roles |
| `OPENAI_API_KEY` | **Only** the optional cosmetic display-map regeneration |
| `OPENAI_IMAGE_MODEL`, `OPENAI_IMAGE_QUALITY`, `OPENAI_IMAGE_MAX_EDGE` | Settings for that same optional feature |
| `ALLOW_DEV_INVITATION_ENDPOINTS` | Dev-only. Enables `POST /api/invitation-codes/dev-create` for bootstrapping the first `super_admin` on an empty database; refuses to run once any `super_admin` exists |

Frontend settings live in `frontend/.env` (development) and `frontend/.env.production`:

| Variable | Purpose |
|---|---|
| `VITE_API_BASE_URL` | Backend base URL. **Required** — there is no fallback; without it every request goes to `undefined/api/...` |
| `VITE_PUBLIC_FRONTEND_URL` | Public origin used to build the URL a QR label encodes. Optional; falls back to `window.location.origin` |

> Two AI providers appear in this project and they never share a key or a model. Semantic map
> analysis is Anthropic Claude and only Claude. OpenAI is used for exactly one optional, unrelated
> feature — redrawing an uploaded plan as a prettier *display* map. Leaving `OPENAI_API_KEY` empty
> simply falls back to the locally generated display map; navigation and analysis are unaffected.

---

## Running the backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS / Linux

pip install -r requirements.txt
python -m uvicorn app:app --reload --port 8000
```

The API is then available at `http://127.0.0.1:8000`. `GET /` is the health check, and generated map
files are served from `http://127.0.0.1:8000/uploads/...`.

### With Docker

```bash
cd backend
docker build -t quickroute-backend .
docker run --rm -p 8000:8000 --env-file .env quickroute-backend
```

The image is Python 3.12-slim with the OpenCV runtime libraries and `tesseract-ocr`, runs as a
non-root user, exposes port 8000, and declares a `HEALTHCHECK` against `GET /`.

## Running the frontend

```bash
cd frontend
npm install
npm run dev          # development server on http://localhost:5173
npm run build        # production bundle into dist/
npm run preview      # serve the built bundle
npm run lint         # ESLint
```

---

## Database setup

No migration step is required. On startup `database/mongo.py` connects with `MONGO_URI` and calls
`init_beanie()`, which registers every document model and creates the underlying collections on
first write. Provide a reachable MongoDB instance (local or Atlas) and set `MONGO_URI` and
`DATABASE_NAME`.

Bootstrapping the first administrator on an empty database: set `ALLOW_DEV_INVITATION_ENDPOINTS=true`
temporarily and call `POST /api/invitation-codes/dev-create` to mint the first `super_admin`
invitation code, then sign up with it via `POST /api/auth/signup`. That endpoint refuses to run once
any `super_admin` account exists, and should be left disabled in every real environment. From then
on, all invitation codes are created through the authenticated admin UI.

Maintenance/backfill endpoints under `/api/maintenance` exist for migrating older data (buildings,
map groups, room names, room-name translations).

---

## API documentation

The backend is a FastAPI application, so OpenAPI documentation is generated automatically and served
by the running API:

| Path | Description |
|---|---|
| `/docs` | Swagger UI |
| `/redoc` | ReDoc |
| `/openapi.json` | Raw OpenAPI schema |

The application is titled **QuickRoute API**, version `1.0.0`. Endpoints are grouped by tag: *Auth*,
*Invitation Codes*, *Admin - Users & Access*, *Locations - Buildings*, *Map Management*, *Map Groups*,
*Rooms & Destinations*, *Route Points*, *Route Edges*, *Vertical Connectors*, *Location Codes*,
*Navigation*, *Automatic Navigation Build*, *Navigation Cleanup*, *Semantic Map Analysis* and
*Maintenance*.

---

## API reference

All endpoints below exist in `backend/routes/`. Protected endpoints expect
`Authorization: Bearer <token>`.

### Auth — `/api/auth`

| Method | Path | Notes |
|---|---|---|
| POST | `/api/auth/register` | Create a `regular_user` account |
| POST | `/api/auth/login` | Exchange credentials for a JWT |
| POST | `/api/auth/signup` | Create an account from an invitation code; role and scope are copied from the code, never from client input |
| GET | `/api/auth/me` | Current user (authenticated) |

### Invitation codes — `/api/invitation-codes`

| Method | Path | Notes |
|---|---|---|
| POST | `/api/invitation-codes/validate` | Validate a code before account creation |
| GET | `/api/invitation-codes` | List (global admin) |
| POST | `/api/invitation-codes` | Create (global admin) |
| GET | `/api/invitation-codes/{code_id}` | Fetch one (global admin) |
| POST | `/api/invitation-codes/{code_id}/revoke` | Revoke (global admin) |
| POST | `/api/invitation-codes/dev-create` | Dev-only bootstrap; gated by `ALLOW_DEV_INVITATION_ENDPOINTS` |

### Users & access — `/api/admin/users`

| Method | Path |
|---|---|
| GET | `/api/admin/users` |
| GET | `/api/admin/users/{user_id}` |
| PUT | `/api/admin/users/{user_id}` |
| DELETE | `/api/admin/users/{user_id}` |

### Buildings — `/api/locations/buildings`

| Method | Path | Notes |
|---|---|---|
| POST | `/api/locations/buildings` | Global admin |
| GET | `/api/locations/buildings` | Optional auth — scope-filtered when authenticated |
| GET | `/api/locations/buildings/{building_id}` | |
| PUT | `/api/locations/buildings/{building_id}` | Authenticated, scope-checked |
| DELETE | `/api/locations/buildings/{building_id}` | Global admin |

### Maps — `/api/maps`

| Method | Path | Notes |
|---|---|---|
| POST | `/api/maps` | Create a map record |
| POST | `/api/maps/upload` | Multipart floor-plan upload (PNG/JPG/WEBP/PDF) |
| GET | `/api/maps` | List (admin) |
| GET | `/api/maps/current` | Current map (optional auth) |
| GET | `/api/maps/{map_id}` | Fetch one (optional auth) |
| PUT | `/api/maps/{map_id}` | Update |
| DELETE | `/api/maps/{map_id}` | Global admin; cascades the map's graph |
| GET | `/api/maps/{map_id}/processing-status` | Background-processing state |
| POST | `/api/maps/{map_id}/retry-processing` | Re-run processing |
| POST | `/api/maps/{map_id}/generate-graph/preview` | Preview generated corridor graph |
| POST | `/api/maps/{map_id}/generate-graph` | Apply generated corridor graph |
| GET | `/api/maps/{map_id}/generate-graph/cleanup/preview` | Preview cleanup of generated graph |
| POST | `/api/maps/{map_id}/generate-graph/cleanup/apply` | Apply that cleanup |
| DELETE | `/api/maps/{map_id}/generated-graph` | Clear the generated graph |
| POST | `/api/maps/{map_id}/calibrate-scale` | Set pixels-per-metre scale |
| POST | `/api/maps/{map_id}/copy-calibration` | Copy calibration from another map |
| POST | `/api/maps/{map_id}/ocr-suggest` | OCR-based destination-name suggestion |

### Map groups — `/api/map-groups`

| Method | Path |
|---|---|
| POST | `/api/map-groups` |
| POST | `/api/map-groups/{group_id}/floors` |
| GET | `/api/map-groups` |
| GET | `/api/map-groups/{group_id}` |
| GET | `/api/map-groups/{group_id}/validate-navigation` |
| PUT | `/api/map-groups/{group_id}` |
| DELETE | `/api/map-groups/{group_id}/floors/{map_id}` |
| DELETE | `/api/map-groups/{group_id}` |

### Rooms & destinations — `/api/rooms`

| Method | Path | Notes |
|---|---|---|
| POST | `/api/rooms` | Create |
| POST | `/api/rooms/sync-from-route-points` | Create/refresh rooms from destination-capable route points |
| GET | `/api/rooms` | List (optional auth) |
| GET | `/api/rooms/{room_id}` | Fetch one |
| PUT | `/api/rooms/{room_id}` | Update |
| DELETE | `/api/rooms/{room_id}` | Delete |

### Route points — `/api/route-points`

| Method | Path | Notes |
|---|---|---|
| POST | `/api/route-points` | Create (admin) |
| GET | `/api/route-points` | List |
| GET | `/api/route-points/count` | Count |
| GET | `/api/route-points/list` | Paginated list |
| GET | `/api/route-points/public` | Public projection |
| GET | `/api/route-points/public/{point_id}` | Public projection, one point |
| GET | `/api/route-points/{point_id}` | Fetch one |
| PUT | `/api/route-points/{point_id}` | Update |
| DELETE | `/api/route-points/{point_id}` | Delete |
| POST | `/api/route-points/bulk-delete/preview` | Preview a bulk delete |
| POST | `/api/route-points/bulk-delete/apply` | Apply it |
| POST | `/api/route-points/backfill-floor-from-map` | Maintenance backfill (global admin) |

### Route edges — `/api/route-edges`

| Method | Path | Notes |
|---|---|---|
| POST | `/api/route-edges` | Create |
| GET | `/api/route-edges` | List |
| GET | `/api/route-edges/{edge_id}` | Fetch one |
| PUT | `/api/route-edges/{edge_id}` | Update |
| DELETE | `/api/route-edges/{edge_id}` | Delete |
| POST | `/api/route-edges/auto-connect-destinations/preview` | Preview auto-connection of destinations |
| POST | `/api/route-edges/auto-connect-destinations/apply` | Apply it |
| POST | `/api/route-edges/legacy-connections/preview` | Preview legacy-edge repair |
| POST | `/api/route-edges/legacy-connections/apply` | Apply it |
| POST | `/api/route-edges/pending-attachments/retry` | Retry pending destination attachments |

### Vertical connectors — `/api/vertical-connectors`

| Method | Path |
|---|---|
| POST | `/api/vertical-connectors` |
| GET | `/api/vertical-connectors` |
| GET | `/api/vertical-connectors/{connector_id}` |
| PUT | `/api/vertical-connectors/{connector_id}` |
| DELETE | `/api/vertical-connectors/{connector_id}` |
| POST | `/api/vertical-connectors/{connector_id}/stops` |
| DELETE | `/api/vertical-connectors/{connector_id}/stops/{route_point_id}` |

### Location codes — `/api/location-codes`

| Method | Path | Notes |
|---|---|---|
| GET | `/api/location-codes/resolve/{code}` | **Public** — resolves a scanned/typed code to a starting point |
| POST | `/api/location-codes` | Create |
| POST | `/api/location-codes/generate` | Generate a code |
| GET | `/api/location-codes` | List (admin) |
| GET | `/api/location-codes/{code_id}` | Fetch one (admin) |
| PUT | `/api/location-codes/{code_id}` | Update |
| DELETE | `/api/location-codes/{code_id}` | Delete |

### Navigation

| Method | Path | Notes |
|---|---|---|
| POST | `/api/navigation/route` | Single-map route |
| POST | `/api/navigation/multi-floor-route` | Multi-floor route — the endpoint the app uses |
| POST | `/api/maps/{map_id}/navigation-build/preview` | Preview a full automatic navigation build for a map |

### Navigation cleanup — `/api/navigation-cleanup` (super admin)

| Method | Path |
|---|---|
| GET | `/api/navigation-cleanup/maps/{map_id}/full-reset/preview` |
| POST | `/api/navigation-cleanup/maps/{map_id}/full-reset/apply` |
| GET | `/api/navigation-cleanup/maps-overview` |
| POST | `/api/navigation-cleanup/multi/generated-cleanup/preview` |
| POST | `/api/navigation-cleanup/multi/generated-cleanup/apply` |
| POST | `/api/navigation-cleanup/multi/full-reset/preview` |
| POST | `/api/navigation-cleanup/multi/full-reset/apply` |

### Semantic map analysis

| Method | Path |
|---|---|
| POST | `/api/maps/{map_id}/semantic-analysis/start` |
| GET | `/api/maps/{map_id}/semantic-analysis/latest` |
| GET | `/api/maps/{map_id}/semantic-entities` |
| POST | `/api/maps/{map_id}/semantic-analysis/repair-floor-codes` |
| POST | `/api/maps/{map_id}/semantic-analysis/destinations/preview` |
| POST | `/api/maps/{map_id}/semantic-analysis/destinations/apply` |
| POST | `/api/maps/{map_id}/semantic-analysis/destinations/auto-place/preview` |
| POST | `/api/map-groups/{map_group_id}/semantic-analysis/start` |
| GET | `/api/semantic-analyses/{analysis_id}` |
| GET | `/api/semantic-analyses/{analysis_id}/result` |
| POST | `/api/semantic-analyses/{analysis_id}/retry` |
| POST | `/api/semantic-analyses/{analysis_id}/cancel` |
| PUT | `/api/semantic-analyses/{analysis_id}/reviewed-result` |
| POST | `/api/semantic-analyses/{analysis_id}/validate` |
| POST | `/api/semantic-analyses/{analysis_id}/publish` |
| GET | `/api/prompts/semantic-map-import/info` |

### Maintenance — `/api/maintenance` (global admin)

| Method | Path |
|---|---|
| POST | `/api/maintenance/backfill-buildings` |
| POST | `/api/maintenance/backfill-map-groups` |
| POST | `/api/maintenance/backfill-room-names` |
| POST | `/api/maintenance/translate-room-names` |

### Root

| Method | Path | Notes |
|---|---|---|
| GET | `/` | Health check — also used by the Docker `HEALTHCHECK` and the ECS service |

---

## Authentication and authorization

**Authentication.** Passwords are hashed with bcrypt via passlib. `POST /api/auth/login`,
`/register` and `/signup` return a JWT signed with `JWT_SECRET_KEY` using `JWT_ALGORITHM`
(default `HS256`) and expiring after `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`. The frontend stores it under
the `quickroute_token` localStorage key and `apiRequest()` attaches it as
`Authorization: Bearer <token>` on every call, clearing the stored session on a 401.

**Account creation.** Ordinary visitors register directly as `regular_user`. Every privileged account
is created from an **invitation code**: the code carries the role and its scope, and the signup flow
copies them verbatim from the reserved code — never from client input. A code's scope can never
exceed its issuer's own.

**Roles** (`backend/models/user_model.py`):

| Role | Scope |
|---|---|
| `super_admin` | Everything, unconditionally |
| `global_manager` | Project-wide by default; can be narrowed to an explicit list of buildings |
| `building_manager` | Only assigned buildings, optionally narrowed further to specific map groups or maps |
| `regular_user` | No admin access; the visitor navigation flow only |

**Authorization.** `backend/core/auth_deps.py` is the single source of truth. It provides the
dependencies used across the routers — `get_current_user`, `get_current_user_optional`,
`require_any_admin`, `require_global_admin`, `require_super_admin` — plus scope checks whose
precedence for a `building_manager` is `map_ids` > `map_group_ids` > `building_ids`. The frontend's
`RequireRole`, `RequireGlobalAdmin` and `RequireSuperAdmin` guards mirror this for navigation only;
the server enforces it.

---

## Testing

Backend — pytest, with `asyncio_mode = auto`:

```bash
cd backend
pip install -r requirements.txt -r requirements-test.txt
pytest tests/ -q
```

The suite (50 modules) runs against an in-memory `mongomock_motor` database and makes no real
Anthropic, OpenAI or MongoDB calls.

Frontend — 59 dependency-free Node scripts placed beside the modules they cover:

```bash
cd frontend
node src/utils/roleRouting.test.mjs                            # a single file
for f in $(find src -name "*.test.mjs"); do node "$f"; done    # all of them
```

---

## Deployment

Production runs the backend as a container and the frontend as static files on a CDN.

- **Backend** — `backend/Dockerfile` builds a Python 3.12-slim image (OpenCV runtime libs +
  `tesseract-ocr`), runs uvicorn as a non-root user on port 8000, and health-checks `GET /`.
  `quickroute-express-service.json` is the ECS Express service definition: 1024 CPU units, 2048 MB
  memory, container port 8000, health-check path `/`, CloudWatch log group `/ecs/quickroute-backend`,
  and autoscaling from 1 to 2 tasks at 60% average CPU. `MAP_STORAGE_BACKEND=s3` switches map storage
  to a private S3 bucket; `MONGO_URI`, `JWT_SECRET_KEY` and `ANTHROPIC_API_KEY` are injected from SSM
  Parameter Store rather than baked into the image.
- **Frontend** — `npm run build` produces static files that are synced to an S3 bucket and served
  through CloudFront. `frontend/cloudfront-distribution.json` and `frontend/frontend-bucket-policy.json`
  hold that configuration.

## CI/CD — GitHub Actions

`.github/workflows/deploy-aws.yml` — *Deploy QuickRoute to AWS*. It runs on pushes to the
`aws-deploy` branch that touch `backend/**`, `frontend/**` or the workflow file, and on manual
`workflow_dispatch`. A concurrency group serializes production deploys.

The single `deploy` job, on `ubuntu-latest`:

1. Checks out the repository.
2. Assumes an AWS IAM role via **OIDC** (`id-token: write`) — no long-lived AWS keys in GitHub.
3. Logs in to Amazon ECR.
4. Builds the backend image for `linux/amd64` from `./backend`, tagged with the commit SHA, and
   pushes it.
5. Deploys it with `aws ecs update-express-gateway-service`.
6. Polls for up to 30 minutes until the active image matches, running count equals desired count, and
   the primary rollout state is `COMPLETED`; on timeout it dumps the service description and fails.
7. Verifies the backend by curling its health endpoint.
8. Sets up Node.js 22, installs frontend dependencies (`npm ci` when a lockfile exists), and builds
   with `VITE_API_BASE_URL` supplied by the workflow.
9. Syncs `frontend/dist` to the S3 bucket with `--delete`.
10. Creates a CloudFront invalidation for `/*` and waits for it to complete.
11. Verifies the frontend by curling the CloudFront URL.

## AWS services used

| Service | Role |
|---|---|
| Amazon ECR | Registry for the backend container image |
| Amazon ECS (Express gateway service) | Runs the backend container, with autoscaling |
| Amazon S3 | Static frontend hosting bucket, and (optionally) the map-file storage bucket |
| Amazon CloudFront | CDN in front of the frontend bucket, invalidated on each deploy |
| AWS IAM | Deploy role assumed via GitHub OIDC; separate ECS execution, infrastructure and task roles |
| AWS Systems Manager Parameter Store | Injects `MONGO_URI`, `JWT_SECRET_KEY` and `ANTHROPIC_API_KEY` into the ECS task |
| Amazon CloudWatch Logs | Backend logs — `app.py` logs structured lines to stdout for collection |

---

## Usage guide

### As a visitor

1. Scan a QuickRoute QR label, or open `/start` and type the location code printed on it.
2. Confirm the building, then pick a destination from the list.
3. Follow the step-by-step directions; switch language at any time between English, Arabic and Hebrew.

### As an administrator

1. Sign in at `/login` (or create an account at `/signup` with an invitation code).
2. **`/admin`** — overview dashboard.
3. **`/admin/sites`** — create a building, then a map group for it, and upload one map per floor.
4. **`/admin/map-analysis`** — start or review the semantic analysis of an uploaded floor plan,
   correct the extracted entities, validate and publish them.
5. **`/admin/map`** — calibrate the map scale, generate the corridor graph, place and auto-connect
   destinations, and edit route points and edges by hand where needed.
6. **`/admin/rooms`** and **`/admin/routes`** — manage destinations and the navigation graph directly.
7. **`/admin/location-codes`** — create the location codes and print the QR labels visitors scan.
8. **`/admin/invitation-codes`** and **`/admin/users`** — issue scoped invitation codes and manage
   accounts.
9. **`/admin/navigation-cleanup`** — preview and apply resets of generated navigation data
   (super admin).

---

## Example workflow

Publishing navigation for a new two-floor clinic:

1. A `global_manager` signs in and creates the building **Clinic North** under `/admin/sites`.
2. They create a map group for it and upload both floor plans at once (`POST /api/map-groups`), one
   PDF per floor.
3. Each upload is preserved, normalized and — with `AUTO_ANALYZE_MAPS=true` — queued for semantic
   analysis; the worker sends each plan to Claude and stores a structured result.
4. Under `/admin/map-analysis` the admin reviews the extracted rooms and corridors, fixes two
   mislabelled rooms, validates and publishes the result.
5. On `/admin/map` they calibrate the scale by drawing a line of known real-world length, then copy
   that calibration to the second floor.
6. They generate the corridor graph (preview → apply), auto-place the published destinations, and run
   auto-connect so every destination attaches to the corridor network.
7. They add a vertical connector for the elevator and register its stop on each floor; the transition
   edges are regenerated automatically.
8. `GET /api/map-groups/{group_id}/validate-navigation` confirms the two floors are connected.
9. They create a location code for the main entrance and print its QR label.
10. A visitor scans that label, chooses "Radiology — Floor 2", and receives directions through the
    ground-floor corridor, up the elevator, and along the second-floor corridor to the door.

---

## Legacy endpoints

`backend/routes/navigation_routes.py` still exposes five unprefixed, unauthenticated endpoints that
read the sample JSON files in `backend/data/` — `GET /buildings`, `GET /buildings/{building_id}/rooms`,
`GET /rooms/{room_id}`, `GET /graph` and `GET /route`. They are marked `deprecated=True`, no part of
the UI calls them, and they are not part of the live system; the real equivalents are
`/api/locations/buildings`, `/api/rooms` and `/api/navigation/multi-floor-route`. They are kept only
so that no old client breaks unexpectedly.

Old frontend paths are likewise preserved: `LEGACY_ROUTE_REDIRECTS` in `frontend/src/config/routes.js`
redirects the historic numeric routes (`/screen/01` … `/screen/18`, `/map`) to their canonical
replacements while carrying the query string and hash through, so a QR label printed before the
rename still resolves its `?locationCode=`.

---

## Contributors

Per the repository's commit history:

- adyanissa
- layalzuobi

## License

No license file is present in this repository, so no license terms are asserted here.
