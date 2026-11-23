# Extension release and recovery

The repository ships one Superset extension, `superset-text-to-bi` (`extensions/text-to-bi`). Every script below
runs from the repository root and handles only that extension.

## Before shipping

- Fill in `.env` from `.env.example` (at least `OPENROUTER_API_KEY` for AI autofill and Text2SQL).
- Run `npm ci` in `extensions/text-to-bi/frontend` once; `uv run scripts/doctor.py` checks the local tools, the frontend
  `node_modules` and the Docker setup.
- Rebuild the Superset image with `docker compose up -d --build superset` whenever `simulation/superset/Dockerfile`
  changes. The image carries the backend's runtime packages (LangChain, LangGraph, Presidio, spaCy, openpyxl…);
  `deploy.py` refuses to copy the bundle when `openpyxl` is missing.

## Ship

`uv run scripts/ship.py [--skip-check] [--smoke]` runs three steps:

1. `check.py`: Ruff and pytest on `extensions/text-to-bi/backend`, Ruff and pytest on `scripts/`, and the frontend
   `npm run typecheck` (`--no-frontend` when run directly skips it).
2. `build.py`: bundles `extensions/superset-text-to-bi-0.1.0.supx` with the Superset extensions CLI and writes
   `superset-text-to-bi-0.1.0.provenance.json` with the bundle hash and the hash of every source file.
3. `deploy.py`: refuses a bundle whose sources changed since the build, requires the `superset` service to be running,
   takes a custom-format `pg_dump` of the Superset metadata database (`superset-db`) and validates it with
   `pg_restore --list`, backs up the installed bundle, copies the new bundle into the `superset_extensions` volume at
   `/app/superset_home/extensions/`, checks its hash, restarts `superset`, and waits until the log shows
   `Loaded extension 'text-to-bi.superset-text-to-bi'` with no traceback or load error.

`--smoke` then runs `smoke.py`, which signs in as the Superset admin and calls read-only endpoints (`/auth/me`,
data dictionary, business model, conversations, own knowledge, Text2SQL chart types, and, when Superset has a dataset,
the dataset and database reads of the dictionary, business model, lineage, metrics, glossary and expert rules). `--skip-check` bypasses step 1;
it is a manual bypass, not a passing release gate.

**Current state:** step 1 fails at the backend pytest run. Only `tests/test_common.py` passes;
`test_data_dictionary_api.py`, `test_data_dictionary_autofill.py` and `test_migrations.py` fail at collection and
`test_auth.py` fails in its fixtures, because `tests/conftest.py` has no stubs for `superset.connectors` and
`superset.models.core`. Until that is fixed, a release needs `--skip-check` plus a manual run of the other checks.

## After deploying

- `deploy.py` restarts only `superset`. `superset-worker` shares the extensions volume and runs the Text2SQL ingestion
  task; restart it too with `docker compose restart superset-worker`.
- Table migrations do not run at deploy time. The first request that touches a module's tables runs its
  `ensure_*_tables()` function, so the metadata snapshot is taken before any migration of the new release.
- `uv run scripts/compat.py` compiles and imports every backend module inside the Superset container (Python 3.10,
  real Superset 6.1) and compares the deployed bundle with the host bundle. `uv run scripts/logs.py [--since 10m]
  [--follow]` shows the Superset log lines about the extension and errors.
- After a change to metadata that the Text2SQL index reads, an admin can rebuild the Qdrant collection with
  `POST /extensions/text-to-bi/superset-text-to-bi/text2sql/ingestion/sync` and body `{"database_id": <id>}`; there
  is no UI for it yet.

## Backups and recovery

Each deployment saves `superset-metadata.dump` and the previous `.supx` in a new
`.release-backups/<UTC timestamp>-<pid>/` directory. Keep this directory until recovery has been rehearsed and the
release has been accepted.

If copying or startup fails, the script restores the previous bundle (or removes the new one when none was installed)
and starts Superset again. This **does not reverse table migrations**: a migration run by the new release can make the
old bundle incompatible with the metadata database. In that case, stop writes to Superset, take a separate snapshot of
the failed state, and restore the metadata dump with PostgreSQL `pg_restore` in an isolated stack. Verify the old
bundle and database together there, including migration-dependent writes, before applying the recovery to the working
stack. Do not run a destructive metadata restore from the deploy script.

The bundle copy, Superset restart and table migrations are not atomic. The live rollback and metadata restore
procedure still require rehearsal with Docker and a disposable copy of the metadata volume.
