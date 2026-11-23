# Text to BI

Text to BI is a local Apache Superset 6.1.0 stack with one Superset extension, **Superset Text to BI**
(`superset-text-to-bi`), that adds natural-language questions over data and the business knowledge the AI agent
relies on: a data dictionary, business model, lineage, governed metrics, glossary terms and expert rules. It is a port
of the standalone Next.js/FastAPI app into Superset: Flask-AppBuilder REST APIs plus a React page served at
`/text-to-bi/`.

The repository used to ship two more extensions (AI Agent and Semantic Layer); both were removed and their features
now live in text-to-bi.

## What it adds to Superset

Three menus in Superset's top navbar. Each section opens on the same page, `/text-to-bi/?section=<segment>`.

| Menu | Section | `section` | Who can open it |
| --- | --- | --- | --- |
| AI Agent | Hỏi dữ liệu: ask in natural language, get an answer, table and chart | `chat` | query permission |
| AI Agent | Tri thức riêng: review what users taught the agent, promote it to shared knowledge | `own-knowledge` | Admin |
| Mô hình dữ liệu | Từ điển: describe tables and columns of Superset datasets | `dictionary` | view permission |
| Mô hình dữ liệu | Mô hình: business domains and data layers | `model` | view permission |
| Mô hình dữ liệu | Dòng dữ liệu: which table builds which, down to columns | `lineage` | view permission |
| Quản trị dữ liệu | Tổng quan: how complete the business knowledge is | (empty) | view permission |
| Quản trị dữ liệu | Metric | `metrics` | view permission |
| Quản trị dữ liệu | Thuật ngữ | `glossary` | view permission |
| Quản trị dữ liệu | Quy tắc | `rules` | view permission |

Permissions live on the FAB view menu `Text to BI` (`can_view`, `can_edit`, `can_review`, `can_query`). The extension
creates four roles that bundle them: `Text to BI Viewer`, `Text to BI Editor`, `Text to BI Steward` and
`Text to BI Query`. Admin can open everything. Superset's own dataset access still applies on top of these roles.
A menu only appears when the user can open at least one of its sections.

The API is mounted below `/extensions/text-to-bi/superset-text-to-bi/<resource>`, for example `auth/me`,
`data-dictionary/summary` or `text2sql/chat/stream`.

## Repository layout

```text
.
├── extensions/
│   ├── text-to-bi/                       Superset Text to BI extension source
│   │   ├── extension.json                Publisher, name and version of the bundle
│   │   ├── backend/
│   │   │   ├── pyproject.toml            Runtime dependencies and bundle file list (Python 3.10)
│   │   │   ├── src/text_to_bi/superset_text_to_bi/
│   │   │   │   ├── entrypoint.py         Registers every API, the page view and the ingestion task
│   │   │   │   ├── migrations.py         Creates and upgrades the extension tables
│   │   │   │   ├── common/  core/        Shared base classes and utilities; config, database, security, routing
│   │   │   │   ├── agent_package/        Chat models, embeddings, prompts, tool agent
│   │   │   │   └── modules/              auth, business_model, conversation, data_dictionary, data_lineage,
│   │   │   │                             expert_rule_management, glossary_management, metric_management,
│   │   │   │                             own_knowledge, superset, text2sql
│   │   │   └── tests/
│   │   └── frontend/                     React 17 page, see frontend/README.md
│   ├── superset-text-to-bi-0.1.0.supx    Current bundle
│   └── superset-text-to-bi-0.1.0.provenance.json
├── scripts/                              Build, check, deploy and diagnostic scripts (tests/ inside)
├── simulation/
│   ├── data_wh/scripts/                  Warehouse schema and seed data
│   ├── airflow/                          Open-Meteo ingestion DAG
│   └── superset/                         Superset image, superset_config.py and bootstrap scripts
├── docs/                                 handbook/, specs/, release.md, reviews/, reports/
├── docker-compose.yml
├── .env.example
└── pyproject.toml                        Local uv environment for tests, Ruff and bundling
```

## Requirements

- Docker Desktop with Docker Compose
- [uv](https://docs.astral.sh/uv/) for the local Python 3.12 environment
- Node.js and npm, used to build the frontend
- An OpenRouter API key for the chat, embeddings and dictionary AutoFill

## Quick start

From the repository root:

```sh
cp .env.example .env          # then set OPENROUTER_API_KEY
uv sync
docker compose up --build -d
uv run scripts/build.py
uv run scripts/deploy.py
```

Then open <http://localhost:8089/text-to-bi/> and sign in as `admin` / `admin`.

- `build.py` bundles the extension with `superset-extensions bundle` (which runs `npm ci` when `node_modules` is
  missing and `npm run build`), writes `extensions/superset-text-to-bi-0.1.0.supx` and records source hashes in the
  `.provenance.json` next to it.
- `deploy.py` copies the bundle into the `superset_extensions` volume at `/app/superset_home/extensions/` and restarts
  `superset`. A fresh volume is empty, so this step is needed after the first `docker compose up`. Bundles are copied
  rather than bind-mounted because bind mounts from the host served stale `.supx` files under Docker Desktop's
  Hyper-V file sharing.
- `deploy.py` restarts only `superset`. `superset-worker` reads the same volume, so restart it too
  (`docker compose restart superset-worker`) after deploying a change that affects background indexing.

Set `SUPERSET_PORT` in `.env` to use another host port.

### What the stack runs

| Service | Purpose |
| --- | --- |
| `warehouse-db` | PostgreSQL 16 database `data_wh` (`dm_*`, `tb_*`, `dim_*`, `fact_*` tables), published on host port 5433 |
| `superset-db` | PostgreSQL 16 for Superset metadata and the extension tables |
| `redis` | Celery broker and result backend |
| `qdrant` | Vector index for the chat, on `127.0.0.1:6333` |
| `superset-init` | `superset db upgrade`, `superset init`, admin user and the bootstrap scripts, then exits |
| `superset` | Superset web app (gunicorn) on <http://localhost:8089> |
| `superset-worker` | Celery worker that runs the extension's index jobs |
| `airflow` | Loads weather data for Vietnamese cities from Open-Meteo every hour (DAG `weather_warehouse_ingest`) |

`superset-init` creates the `Weather Warehouse` connection, registers every table in the warehouse `public` schema
as a dataset, and builds the "Tổng quan thời tiết" and "Tổng quan AI Agent" dashboards. Rerun
`docker compose run --rm superset-init` after the warehouse schema changes. The "Tổng quan AI Agent" dashboard reads
`text_to_bi_agent_question`, which only the removed AI Agent extension wrote, so it stays empty.

From the host, the warehouse is reachable at:

```text
postgresql+psycopg2://bi:bi_dev_password@localhost:5433/data_wh
```

## Configuration and secrets

All local settings live in one `.env` at the repository root (ignored by Git). Compose uses it to fill
`docker-compose.yml` and loads it into the Superset containers. `.env.example` lists every variable; commented lines
show the default Compose uses when a variable is unset. Before exposing the stack beyond a development machine, set
at least `SUPERSET_SECRET_KEY`, `SUPERSET_ADMIN_PASSWORD`, `SUPERSET_DB_PASSWORD`, `WAREHOUSE_DB_PASSWORD`,
`TEXT_TO_BI_REPORTING_DB_PASSWORD`, `AIRFLOW_SECRET_KEY` and `AIRFLOW_ADMIN_PASSWORD`.

Recreate the containers with `docker compose up -d` after changing `.env`. Never commit API keys, passwords or `.env`.

## AI chat: OpenRouter and the Qdrant index

The chat (Hỏi dữ liệu) needs two things:

1. `OPENROUTER_API_KEY` in `.env`. `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL` and the `TEXT2SQL_EMBEDDING_*` variables
   are optional.
2. A Qdrant index for the database being asked about (collection `text2sql_semantics_v1` by default). Build or rebuild
   it as an admin with `POST /extensions/text-to-bi/superset-text-to-bi/text2sql/ingestion/sync` and the body
   `{"database_id": <id>}`. There is no UI for this yet. After that, changes to dictionary, metric, glossary, rule and
   own-knowledge records queue index jobs that `superset-worker` processes.

Answers stream as Server-Sent Events from `POST .../text2sql/chat/stream`.

## Daily development loop

All scripts run from the repository root with `uv run scripts/<name>.py`; `--help` prints each one's usage.

| Script | What it does |
| --- | --- |
| `ship.py [--skip-check] [--smoke]` | Runs `check.py`, then `build.py` and `deploy.py`; `--smoke` runs `smoke.py` afterwards |
| `check.py [--no-frontend]` | Ruff and pytest for the backend and for `scripts/`, plus the frontend `npm run typecheck` |
| `build.py` | Builds the bundle and its provenance file |
| `deploy.py` | Snapshots Superset metadata with `pg_dump`, backs up the installed bundle under `.release-backups/`, copies the new bundle, restarts Superset and checks its logs; restores the old bundle on failure (migrations are not rolled back) |
| `smoke.py` | Logs in as the admin and checks that read-only endpoints answer 200 with JSON; changes no data |
| `logs.py [--since 10m] [--follow] [--all]` | Superset log lines about the extension, extension loading and errors |
| `compat.py` | Compares the source, the host bundle and the deployed bundle, then compiles and imports every backend module inside the Superset container (Python 3.10, real Superset 6.1) |
| `doctor.py` | Checks local tools, the Docker engine, running services and Superset `/health` |

The usual loop is `uv run scripts/ship.py --smoke`, then `logs.py` if something fails. See
[docs/release.md](docs/release.md) for backups and recovery.

Known gap: in `extensions/text-to-bi/backend/tests`, `test_data_dictionary_api.py`, `test_data_dictionary_autofill.py`
and `test_migrations.py` fail at collection and every test in `test_auth.py` errors in its setup, because `tests/conftest.py` has no stubs for
`superset.connectors` and `superset.models.core`. Until those stubs exist, the pytest step of `check.py` fails, so
`ship.py` stops before building unless you pass `--skip-check`.

## Documentation

- [docs/handbook/](docs/handbook/README.md): code conventions (`quy-uoc-code.md`), backend architecture
  (`kien-truc.md`), shared API behaviour (`hanh-vi.md`), and one guide plus one API reference per module
  (`text-to-bi-<module>.md`, `text-to-bi-<module>-api.md`).
- [docs/specs/](docs/specs/): feature specifications.
- [extensions/text-to-bi/frontend/README.md](extensions/text-to-bi/frontend/README.md): frontend stack and folders.

## Project conventions

- Keep one current `.supx` bundle (and its provenance file) in `extensions/`.
- Do not commit `.env`, credentials, `node_modules`, build output or local database files.
- Python follows the repository Ruff configuration: 120-character lines, import sorting; the backend targets
  Python 3.10 because Superset 6.1 runs it there.
