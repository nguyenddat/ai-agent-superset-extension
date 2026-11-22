"""Idempotent auth-module bootstrap using Superset's existing security tables."""

import threading

from sqlalchemy import text
from superset.extensions import db

from .services.srv_roles import ensure_text_to_bi_roles

AUTH_ROLE_LOCK_KEY = 74_116_302
_roles_ready = False
_roles_lock = threading.Lock()


def ensure_auth_roles() -> None:
    """Seed extension roles and permissions; does not create or alter tables."""
    global _roles_ready
    if _roles_ready:
        return
    with _roles_lock:
        if not _roles_ready:
            if db.engine.dialect.name != "postgresql":
                ensure_text_to_bi_roles()
            else:
                with db.engine.connect() as lock_connection:
                    lock_connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": AUTH_ROLE_LOCK_KEY})
                    try:
                        ensure_text_to_bi_roles()
                    finally:
                        lock_connection.execute(
                            text("SELECT pg_advisory_unlock(:key)"), {"key": AUTH_ROLE_LOCK_KEY}
                        )
            _roles_ready = True
