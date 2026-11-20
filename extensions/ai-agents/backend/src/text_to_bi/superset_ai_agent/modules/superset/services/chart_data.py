import logging
from typing import Any

logger = logging.getLogger(__name__)


def read_chart_queries(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    from superset.charts.schemas import ChartDataQueryContextSchema
    from superset.commands.chart.data.get_data_command import ChartDataCommand

    try:
        command = ChartDataCommand(ChartDataQueryContextSchema().load(payload))
        command.validate()
        return command.run()["queries"]
    except Exception as error:
        if not any(
            word in error.__class__.__name__.lower() for word in ("access", "forbidden", "permission", "security")
        ):
            logger.exception("Reading query metadata values through Superset failed")
        return None
