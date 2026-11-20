from typing import Any

from sqlalchemy import text

from ..exceptions import AutoFillUnavailableError

AUTOFILL_LOCK_NAMESPACE = 74_116_203


class AutoFillLease:
    def __init__(self, connection: Any, dataset_id: int) -> None:
        self.connection = connection
        self.dataset_id = dataset_id

    def close(self) -> None:
        connection, self.connection = self.connection, None
        if connection is None:
            return
        try:
            connection.execute(
                text("SELECT pg_advisory_unlock(:namespace, :dataset_id)"),
                {"namespace": AUTOFILL_LOCK_NAMESPACE, "dataset_id": self.dataset_id}
            )
        except Exception:
            # Không trả connection còn giữ lock về pool khi lệnh unlock thất bại.
            connection.invalidate()
            raise
        finally:
            connection.close()


def claim_autofill(engine: Any, dataset_id: int) -> AutoFillLease | None:
    if engine.dialect.name != "postgresql":
        raise AutoFillUnavailableError("AutoFill cần PostgreSQL để khóa dataset giữa các worker.")
    connection = engine.connect()
    try:
        connection = connection.execution_options(isolation_level="AUTOCOMMIT")
        acquired = connection.execute(
            text("SELECT pg_try_advisory_lock(:namespace, :dataset_id)"),
            {"namespace": AUTOFILL_LOCK_NAMESPACE, "dataset_id": dataset_id}
        ).scalar()
        if acquired:
            return AutoFillLease(connection, dataset_id)
        connection.close()
        return None
    except Exception:
        connection.invalidate()
        connection.close()
        raise
