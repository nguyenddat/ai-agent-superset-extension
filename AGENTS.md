# Text To BI project guide

## Project overview

This repository runs a local Text to BI stack around Apache Superset 6.1.0 and ships one Superset extension,
`superset-text-to-bi` (`extensions/text-to-bi/`). The extension ports the standalone Next.js/FastAPI app (sibling repo
`ai-agent-superset-standalone`) into Superset: Flask-AppBuilder REST APIs on the backend and a React 17 page at
`/text-to-bi/` on the frontend. The stack also has a PostgreSQL warehouse with sample weather data, a Superset
metadata database, Redis, a Celery worker and Qdrant. The two older extensions (AI Agent and Semantic Layer) were
removed; their code is only in git history.

## Read the handbook first

`docs/handbook/` holds what the team agreed on for writing code here. Read it before changing code, and follow it over
habits from other projects:

- `docs/handbook/quy-uoc-code.md`: code conventions (120-character lines, naming, imports, no docstrings, tests) and
  Conventional Commits messages, `<type>(<scope>): <description>`.
- `docs/handbook/kien-truc.md`: the backend layers (`common`, `core`, `modules`), modules split by business area, the
  `superset` module for Superset's own datasets and users, and the layout inside a module.
- `docs/handbook/hanh-vi.md`: exceptions and status codes, route decorator order, transactions, permissions and CSRF.
- `docs/handbook/text-to-bi-<module>.md` and `text-to-bi-<module>-api.md`: behaviour and endpoints of each module.

When a change alters one of these rules, update the handbook in the same commit.

## Main directories

- `extensions/text-to-bi/` is the product:
  - `extension.json`: publisher `text-to-bi`, name `superset-text-to-bi`, version `0.1.0`.
  - `backend/src/text_to_bi/superset_text_to_bi/`: `entrypoint.py` registers every API class and the page view;
    `common/` (base models, exceptions, charts, utils), `core/` (config, error handling, routing, CSRF, validation),
    `agent_package/` (LLM calls, tool agent, prompts) and `modules/` (`auth`, `business_model`, `conversation`,
    `data_dictionary`, `data_lineage`, `expert_rule_management`, `glossary_management`, `metric_management`,
    `own_knowledge`, `superset`, `text2sql`). `backend/tests/` holds the pytest suite.
  - `frontend/src/`: `index.tsx` (Module Federation entry; adds the navbar menus and mounts the page), `app.tsx`,
    `components/` (shadcn `base-nova` on Base UI; `components/ui/` are the primitives), `lib/` (`navigation`, `api`,
    `access`, `theme`, `sse`, `react-compat`), `features/<module>/` and `styles/globals.css`.
- `extensions/superset-text-to-bi-0.1.0.supx` and its `.provenance.json` are the current bundle and the source hashes it
  was built from. Keep only the current bundle here.
- `scripts/` holds the build, deploy and check workflow (see below).
- `simulation/` holds the simulated environment the extension runs against:
  - `simulation/data_wh/scripts/` defines the warehouse schema: `001_init_bang_co_so.sql` creates the `dm_*` and
    normalized `tb_*` tables; `002_init_bang_dashboard.sql` creates dashboard tables from that business layer.
  - `simulation/airflow/` contains the Open-Meteo ingestion DAG and its runtime files.
  - `simulation/superset/` contains the Superset image, `superset_config.py`, and the admin, warehouse, metric,
    dashboard and governance bootstrap scripts that `superset-init` runs.
- `docs/handbook/` holds conventions, architecture and module behaviour; `docs/specs/` holds feature specifications;
  `docs/reports/` holds the reports written for the client (Word and PDF).

## Python environment

Use the uv-managed virtual environment `.venv` at the repository root for local Python commands and tooling. The root
`pyproject.toml` and `uv.lock` define it: Python 3.12, the backend's AI dependencies (LangChain, LangGraph, pydantic),
and the `dev` group with `apache-superset-extensions-cli` (`superset-extensions`), `pytest`, `ruff` and `playwright`.
Pytest's `pythonpath` points at `extensions/text-to-bi/backend/src`.

```sh
uv sync
uv run pytest extensions/text-to-bi/backend/tests
uv run ruff check extensions/text-to-bi/backend scripts
```

Run Python tools through `uv run` from the repository root. `extensions/text-to-bi/backend/` has its own
`pyproject.toml` for bundling and for Ruff's Python 3.10 target, so running `uv run` inside it creates a separate,
empty `.venv` there; from the root, or with `--project <repository root>`, it finds the root project. Add or change
dependencies with `uv add` / `uv add --dev` so `uv.lock` stays current.

The frontend uses npm in `extensions/text-to-bi/frontend/`: `npm ci`, `npm run typecheck`, `npm run build` (webpack;
the bundle step runs it for you).

Superset's runtime runs inside the Docker image on Python 3.10. The local environment is for development commands and
packaging.

## Stack commands

Run these from the repository root:

```sh
docker compose up --build -d
docker compose ps
docker compose logs -f superset
```

Superset is at `http://localhost:8089` (`SUPERSET_PORT`), admin `admin`/`admin` by default. Services:

- `superset`: gunicorn, one `gthread` worker with 16 threads.
- `superset-worker`: Celery; runs the Text2SQL ingestion task `text_to_bi.text2sql.process_ingestion_job`
  (`superset_config.py` adds `modules.text2sql.worker` to the Celery imports). `redis` is its broker.
- `superset-init`: `superset db upgrade`, `superset init`, then the bootstrap scripts.
- `superset-db` (Superset metadata, which also holds the extension's `text_to_bi` schema) and `warehouse-db`
  (`data_wh`, host port 5433), both on persistent volumes.
- `qdrant` on `127.0.0.1:6333`: the Text2SQL semantic index, collection `text2sql_semantics_v1`.
- `airflow` on port 8080.

## Build, install and restart the extension

Use the scripts:

```sh
uv run scripts/ship.py --smoke
```

`ship.py` runs `check.py`, `build.py` and `deploy.py` (and `smoke.py` with `--smoke`). `build.py` runs
`superset-extensions bundle --output extensions/superset-text-to-bi-0.1.0.supx` inside `extensions/text-to-bi` (which
builds the frontend with webpack) and writes `superset-text-to-bi-0.1.0.provenance.json`. `deploy.py` refuses a bundle
whose provenance no longer matches the sources, so always bundle through `build.py`.

Superset reads the bundle from the `superset_extensions` named volume at `/app/superset_home/extensions`, shared by
`superset-init`, `superset` and `superset-worker`. The bundle is copied in with `docker compose cp` instead of
bind-mounted, because bind mounts from the host drive served stale `.supx` content under Docker Desktop's Hyper-V file
sharing. A fresh volume is empty, so deploy once after the first `docker compose up`. The manual equivalent of
`deploy.py` is:

```sh
docker compose cp extensions/superset-text-to-bi-0.1.0.supx superset:/app/superset_home/extensions/
docker compose restart superset
```

`deploy.py` restarts only `superset`. After changing code the Celery task runs (Text2SQL ingestion), also run
`docker compose restart superset-worker`. Rebuild the image (`docker compose up -d --build superset`) after changing
`simulation/superset/`; `deploy.py` stops early when the image lacks `openpyxl`.

## Development scripts

Run each script from the repository root with `uv run`; `--help` prints its options. Every script targets
`extensions/text-to-bi` (`scripts/_common.py`).

| Script | What it does |
| --- | --- |
| `scripts/doctor.py` | Checks uv, node, npm, docker, frontend `node_modules`, the Docker engine (must be Hyper-V, not WSL2), the `superset-db`, `warehouse-db` and `superset` services, and Superset `/health`. |
| `scripts/check.py` | Runs Ruff and pytest on the backend, Ruff and pytest on `scripts/`, and `npm run typecheck` on the frontend. `--no-frontend` skips the typecheck. |
| `scripts/build.py` | Bundles `extensions/superset-text-to-bi-0.1.0.supx` and records the bundle hash and source hashes in its `.provenance.json`. |
| `scripts/deploy.py` | Checks the bundle's provenance, snapshots the metadata database with `pg_dump` into `.release-backups/<timestamp>/`, backs up the installed bundle, copies the new one and verifies its sha256, restarts Superset, and checks the log for `Loaded extension 'text-to-bi.superset-text-to-bi'`. On failure it restores the previous bundle; migrations are not rolled back. |
| `scripts/ship.py` | Runs `check.py`, `build.py` and `deploy.py`. `--skip-check` skips the checks; `--smoke` runs `smoke.py` last. |
| `scripts/compat.py` | Checks the source against the real Superset 6.1 runtime: flags a stale host or deployed bundle, then compiles every backend module with the container's Python 3.10 and imports it inside a Superset app context. |
| `scripts/smoke.py` | Logs in through the Superset login form as the admin and calls read-only endpoints (`auth/me`, `data-dictionary/summary` and `stats`, `business-model/layers/` and `domains/`, `conversations/`, `own-knowledge/admin/entries`, `text2sql/chart-types`, plus the dataset and database reads of `data-dictionary`, `business-model`, `data-lineage`, `metrics`, `glossary` and `expert-rules` for the first Superset dataset when one exists), expecting 200 with JSON. It changes no data. |
| `scripts/logs.py` | Prints Superset log lines about the extension, `text_to_bi` and errors. `--since 10m`, `--follow` and `--all` adjust it. |

Typical loop after a change:

```sh
uv run scripts/check.py
uv run scripts/compat.py
uv run scripts/ship.py --smoke
```

The local pytest suite runs on Python 3.12 against stubbed `superset` modules (`backend/tests/conftest.py`), so it
cannot catch Superset API drift or Python 3.10 syntax; `compat.py` and `smoke.py` cover that and need the stack up.

`build.py` resolves each executable through `PATH` first, because `superset-extensions` starts npm with
`subprocess.run(["npm", ...])` and Windows cannot resolve `npm.cmd` that way. The scripts force UTF-8 output because the
CLI's emoji messages fail on the cp1252 console encoding. `smoke.py` logs in through `/login/` rather than the JWT API
because the extension reads the user from the flask-login session. Set `SUPERSET_URL` or `SUPERSET_PORT` when Superset is
not on `http://localhost:8089`, and `SUPERSET_ADMIN_USERNAME` / `SUPERSET_ADMIN_PASSWORD` when the admin is not
`admin`/`admin`.

## Page, APIs and access

The page is `/text-to-bi/?section=<segment>` (`TextToBIView`, `modules/auth/routes/route_page.py`). The frontend adds
three menus to Superset's navbar (`features/workspace/workspace-layout.tsx`, `src/index.tsx`):

- "AI Agent": `chat` ("Hỏi dữ liệu"), `own-knowledge` ("Tri thức riêng").
- "Mô hình dữ liệu": `dictionary` ("Từ điển"), `model` ("Mô hình"), `lineage` ("Dòng dữ liệu").
- "Quản trị dữ liệu": the empty segment ("Tổng quan"), `metrics`, `glossary`, `rules`.

The APIs live under `/extensions/text-to-bi/superset-text-to-bi/<resource>`, with resources `auth`, `business-model`,
`conversations`, `data-dictionary`, `data-lineage`, `expert-rules`, `glossary`, `metrics`, `own-knowledge` and
`text2sql`. All of them share the Flask-AppBuilder class permission `text_to_bi_api` (`can_read` for GET, `can_write`
for the rest); what a caller may do inside is decided by `modules/auth/services/srv_access.py`.

The auth module (`modules/auth/services/srv_roles.py`) seeds these roles on the view menu "Text to BI":

| Role | Permissions |
| --- | --- |
| `Text to BI Viewer` | `can_view`, API read |
| `Text to BI Editor` | `can_view`, `can_edit`, API read and write |
| `Text to BI Steward` | `can_view`, `can_edit`, `can_review`, API read and write |
| `Text to BI Query` | `can_query`, API read and write |

`Admin` gets all four permissions. The view menu and the API permission are declared admin-only, and the permissions are
revoked from `Alpha`, `Gamma`, `Public` and `sql_lab`, so Superset's role sync never hands them out. Dataset-level
checks also require Superset's own access to each dataset. In the frontend, `canOpenSection` lets `chat` open with
`can_query`, `own-knowledge` only for admins, and every other section with `can_view`. There is no role-assignment
screen in the page; admins use `PUT /auth/role-assignments/<user_id>` or Superset's user management.

## Database tables

Every extension table lives in the PostgreSQL schema `text_to_bi` of Superset's metadata database
(`common/base_model.py`: `TEXT_TO_BI_SCHEMA`); Superset's own tables (`tables`, `ab_user`, `ab_role`, …) are only read
or referenced. Each module creates its own tables in an idempotent `ensure_*` function in its `migrations.py`:

| Module | `ensure_*` | Tables |
| --- | --- | --- |
| `data_dictionary` | `ensure_data_dictionary_tables` | `table_dictionaries`, `table_column_roles`, `table_time_grains`, `indicator_aggregations`, `column_dictionaries`, `column_aggregations`, `column_synonyms` |
| `business_model` | `ensure_business_model_tables` | `business_domains`, `business_domain_tables`, `data_layers`, `dataset_layers`, `business_canvases` |
| `data_lineage` | `ensure_data_lineage_tables` | `lineage_canvases`, `lineage_edges`, `lineage_transformations`, `lineage_transformation_inputs`, `lineage_column_dependencies` |
| `metric_management` | `ensure_metric_tables` | `metrics`, `metric_domains` |
| `glossary_management` | `ensure_glossary_tables` | `glossary_terms`, `glossary_revisions`, `glossary_links`, `glossary_term_domains` |
| `expert_rule_management` | `ensure_expert_rule_tables` | `expert_rules`, `expert_rule_revisions`, `expert_rule_glossary_links`, `expert_rule_metric_links`, `expert_rule_domains` |
| `own_knowledge` | `ensure_own_knowledge_tables` | `own_knowledge_clarifications`, `own_knowledge_proposals`, `own_knowledge_entries` |
| `conversation` | `ensure_conversation_tables` | `conversations`, `conversation_turns`, `conversation_turn_feedback` |
| `text2sql` | `ensure_text2sql_tables` | `text2sql_chat_checkpoints`, `text2sql_ingestion_jobs` |
| `auth` | `ensure_auth_roles` | none; seeds the roles above in Superset's security tables |

An `ensure_*` function runs once per process under a `pg_advisory_lock`, creates the schema if needed and calls
`create_all(checkfirst=True)` for its tables; it first ensures the modules its foreign keys depend on.
`ensure_text2sql_tables` ensures the own-knowledge chain (rules, glossary, metrics, business model) and the conversation
tables. Routes call the `ensure_*` of the tables they touch before using them.

## Backend conventions

- Inside a module import relatively (`from ..models import Metric`); across modules and into `common`/`core` import
  absolutely from `text_to_bi.superset_text_to_bi...`. Relative imports come after absolute ones (Ruff `I`).
- Route classes use `@api(..., resource_name=...)` on `RestApi` with `class_permission_name = API_CLASS_PERMISSION`.
  Decorator order on a writing route: `@expose`, `@protect()`, `@safe`, `@permission_name("write")`,
  `@csrf_protected`, `@rollback_on_error`, `@handle_errors`. A GET route uses `@permission_name("read")` and drops
  `csrf_protected` and `rollback_on_error` but keeps `handle_errors`. `handle_errors` turns an `AppError`
  (`common/base_exceptions.py`) into its status with `{"code", "message"}` and rolls the session back.
- Read shared environment variables through `settings` in `core/config.py`, never `os.getenv` in a module.
- LangGraph runs graph nodes and agent tool steps on pool threads that never end an app context, so a `db.session`
  opened there stays idle in transaction and holds locks (this hung `ensure_*` migrations). Wrap every function that
  LangGraph runs on its threads and that may touch the database with `release_thread_session`
  (`common/utils/thread_session.py`), as `chat_service.py` and `agent_tools.py` do.
- A thread started from a request must keep the Superset user: use `with_request_user`
  (`modules/text2sql/services/chat_stream.py`), which copies the request context and `g.user`. The chat streams SSE at
  `POST /text2sql/chat/stream` this way.
- Write no docstrings; a short comment explains why. Scripts in `scripts/` keep their module docstring because
  `argparse` shows it as `--help`.
- Store timezone-aware datetimes normalized to UTC.

## Frontend conventions

- React 17 with Module Federation (`webpack.config.js`); React and ReactDOM come from Superset as shared singletons.
  `lib/react-compat.ts` shims `useSyncExternalStore` and `useId`, which React 17 lacks.
- Components are shadcn `base-nova` on Base UI, not Radix: compose with the `render` prop instead of `asChild`
  (`<Button render={<Link href=... />} />`).
- Under React 17 a trigger passed through another part's `render` loses its ref unless it uses `React.forwardRef`;
  write custom triggers and inputs with `forwardRef`.
- Pass `items` to a Base UI `Select` so the selected value shows its label instead of the raw value.
- Tailwind v4 is scoped to the extension: `globals.css` imports only theme and utilities (no preflight), base rules are
  written under `:where(.tb-page)`, and `AppShell` renders the `.tb-page` root that popups portal into. Do not add
  global CSS that reaches Superset's own pages.
- Call the APIs through `lib/api.ts` (`apiFetch`), which handles Superset's cookies and CSRF token; build links with
  `pageHref` from `lib/navigation.tsx`.

## Code style and commits

The full rules are in `docs/handbook/quy-uoc-code.md`. For Python and TypeScript alike, lines may be up to 120
characters; keep anything that fits on one line, and do not run `ruff format` or Prettier over existing code. Name things
for what they mean in the domain and do not abbreviate. Ruff checks line length (`E501`) and import order (`I`) from the
root `pyproject.toml` and `extensions/text-to-bi/backend/pyproject.toml`; the frontend has no formatter.

Commit messages are Conventional Commits, `<type>(<scope>): <description>`, with scopes such as `text-to-bi`,
`text2sql`, `scripts`, `simulation` and `docs`:

```text
feat(text-to-bi): add the lineage section to the data model menu
fix(text2sql): release the LangGraph thread session after each tool step
build(scripts): deploy only the text-to-bi bundle
docs(handbook): describe the own-knowledge review flow
```

## Known gaps

- `test_data_dictionary_api.py`, `test_data_dictionary_autofill.py` and `test_migrations.py` fail at collection and
  every test in `test_auth.py` errors in its setup, because `backend/tests/conftest.py` has no stubs for
  `superset.connectors` and `superset.models.core`. Only `test_common.py` runs.
- The Qdrant index is rebuilt with `POST /text2sql/ingestion/sync {"database_id": ...}` (admin only); there is no UI for
  it yet.
- Own-knowledge entries are created only through the agent API (`POST /own-knowledge/clarifications`, then its
  `/answer`), not by the chat; admins review them in "Tri thức riêng".
- The metric-promotion form duplicates the metric editor.
- `superset-init` still runs `bootstrap_governance.py`, which builds the "Tổng quan AI Agent" dashboard on the removed
  AI Agent's question-log tables.

## Local configuration and secrets

Local settings and secrets live in one `.env` at the repository root, next to `docker-compose.yml`; `.env.example`
lists its variables. Compose reads it to fill the `${...}` values in `docker-compose.yml` and loads it into
`superset-init`, `superset` and `superset-worker`. The extension reads `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`,
`OPENROUTER_MODEL`, `QDRANT_URL` and the `TEXT2SQL_*` variables through the `Settings` class in `core/config.py`
(pydantic-settings); add a new shared variable there. Keep credentials and API keys out of commits, bundles and
documentation. The Compose defaults are for local development; set real secrets in `.env` before exposing the stack,
then recreate the containers with `docker compose up -d`.
