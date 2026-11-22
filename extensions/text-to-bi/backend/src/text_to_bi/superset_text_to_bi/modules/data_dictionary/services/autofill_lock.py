import threading
from typing import Any

from sqlalchemy import text

# Arbitrary namespace shared by every Superset worker; the second key is the dataset id.
AUTOFILL_LOCK_NAMESPACE = 74_116_302

_local_running: set[int] = set()
_local_lock = threading.Lock()


class AutofillLease:
    def __init__(self, dataset_id: int, connection: Any | None = None) -> None:
        self.dataset_id = dataset_id
        self.connection = connection
        self.released = False

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        connection, self.connection = self.connection, None
        if connection is None:
            with _local_lock:
                _local_running.discard(self.dataset_id)
            return
        try:
            connection.execute(
                text("SELECT pg_advisory_unlock(:namespace, :dataset_id)"),
                {"namespace": AUTOFILL_LOCK_NAMESPACE, "dataset_id": self.dataset_id},
            )
        except Exception:
            # A connection that may still hold the lock must not go back to the pool.
            connection.invalidate()
            raise
        finally:
            connection.close()


# Superset runs several workers, so PostgreSQL holds the lock on a connection of its own for as long as the stream
# runs. Any other database means a single local process (tests, SQLite), where a process-wide set is enough.
def claim_autofill(engine: Any, dataset_id: int) -> AutofillLease | None:
    if engine.dialect.name != "postgresql":
        with _local_lock:
            if dataset_id in _local_running:
                return None
            _local_running.add(dataset_id)
        return AutofillLease(dataset_id)
    connection = engine.connect()
    try:
        connection = connection.execution_options(isolation_level="AUTOCOMMIT")
        acquired = connection.execute(
            text("SELECT pg_try_advisory_lock(:namespace, :dataset_id)"),
            {"namespace": AUTOFILL_LOCK_NAMESPACE, "dataset_id": dataset_id},
        ).scalar()
    except Exception:
        connection.invalidate()
        connection.close()
        raise
    if acquired:
        return AutofillLease(dataset_id, connection)
    connection.close()
    return None
