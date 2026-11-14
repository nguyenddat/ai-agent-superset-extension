from flask import current_app

SEMANTIC_QUERY_MAX_ROWS = 1_000


def semantic_query_row_cap() -> int:
    """Use the deployment cap without accepting a client-selected result limit."""
    configured = current_app.config.get("SEMANTIC_QUERY_MAX_ROWS", SEMANTIC_QUERY_MAX_ROWS)
    return min(max(int(configured), 1), SEMANTIC_QUERY_MAX_ROWS)
