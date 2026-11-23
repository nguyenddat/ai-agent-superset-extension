from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from superset.extensions import db

F = TypeVar("F", bound=Callable[..., Any])


# For code LangGraph runs on its pool threads (every graph node while it streams "custom" events, and the tool agent's
# steps nested in them). db.session is scoped per thread and only removed when an app context ends in that thread,
# which a pool thread never does: the session it opened would keep its transaction, and the locks of every table it
# read, for as long as the worker lives. A migration's ALTER TABLE then waits on it, and every read of that table
# queues behind the ALTER. A session the call found already open belongs to its caller and is left alone.
def release_thread_session(func: F) -> F:
    @wraps(func)
    def run(*args: Any, **kwargs: Any) -> Any:
        opened_here = not db.session.registry.has()
        try:
            return func(*args, **kwargs)
        finally:
            if opened_here:
                db.session.remove()

    return run  # type: ignore[return-value]
