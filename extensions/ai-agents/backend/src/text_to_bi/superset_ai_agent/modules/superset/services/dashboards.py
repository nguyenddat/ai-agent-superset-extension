from superset.commands.dashboard.exceptions import DashboardAccessDeniedError, DashboardNotFoundError
from superset.daos.dashboard import DashboardDAO

from ..dependencies import superset_dashboard_repository
from ..exceptions import DashboardAccessError


def dashboard_titles(dashboard_ids: set[int]) -> dict[int, str]:
    return superset_dashboard_repository().titles(dashboard_ids)


def require_dashboard_access(dashboard_id: int) -> None:
    try:
        DashboardDAO.get_by_id_or_slug(dashboard_id)
    except (DashboardNotFoundError, DashboardAccessDeniedError) as error:
        raise DashboardAccessError() from error
