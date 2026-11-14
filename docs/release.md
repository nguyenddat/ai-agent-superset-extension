# Extension release and recovery

Rebuild the Superset image with `docker compose up -d --build superset` before shipping; the image must contain `openpyxl` for XLSX import and export. Run `uv run scripts/ship.py` from the repository root. It runs local checks for both extensions, builds both bundles, takes a custom-format `pg_dump` of the Superset metadata database, backs up both installed bundles, copies both new bundles, and verifies startup. Use `--smoke` for read-only API checks after deployment. `--skip-check` is a manual bypass of local tests and typechecks; it is not a passing release gate.

Each deployment saves `superset-metadata.dump` and any previous `.supx` files in a new `.release-backups/<UTC timestamp>-<pid>/` directory. The script validates the dump with `pg_restore --list` before copying either bundle. Keep this directory until recovery has been rehearsed and the release has been accepted.

If copying or startup fails, the script restores the previous bundle files and starts Superset. This **does not reverse database migrations**. A migration can make an old bundle incompatible with the metadata database. In that case, stop writes to Superset and restore the metadata dump in an isolated stack using PostgreSQL `pg_restore` after taking a separate snapshot of the failed state. Verify the old bundles and database together in that isolated stack, including migration-dependent writes, before applying the recovery to the working stack. Do not run a destructive metadata restore from the deploy script.

The two bundle copies, Superset restart, and database migration are not atomic. The live rollback and metadata restore procedure still require rehearsal with Docker and a disposable copy of the metadata volume.
