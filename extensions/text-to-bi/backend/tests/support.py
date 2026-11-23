import json
from types import SimpleNamespace
from typing import Any

from flask import Flask

ADMIN = "Admin"
VIEWER = "Text to BI Viewer"
EDITOR = "Text to BI Editor"
QUERY = "Text to BI Query"


def column(
    name: str, data_type: str = "VARCHAR(255)", *, is_dttm: bool = False, verbose_name: str | None = None,
    description: str | None = None, expression: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        column_name=name, type=data_type, is_dttm=is_dttm, verbose_name=verbose_name, description=description,
        expression=expression,
    )


def database(database_id: int, name: str, *, internal: bool = False) -> SimpleNamespace:
    extra = json.dumps({"text_to_bi_internal": True}) if internal else "{}"
    return SimpleNamespace(id=database_id, database_name=name, extra=extra, backend="postgresql")


def dataset(
    dataset_id: int, table_name: str, columns: list[SimpleNamespace], source: SimpleNamespace, *,
    schema: str | None = "public", description: str | None = None, sql: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=dataset_id, table_name=table_name, schema=schema, database_id=source.id, database=source,
        description=description, sql=sql, columns=columns,
    )


class FakeRole:
    def __init__(self, name: str) -> None:
        self.name = name
        self.permissions: list[tuple[str, str]] = []


class FakeUser:
    def __init__(self, user_id: int, username: str, roles: list[FakeRole]) -> None:
        self.id = user_id
        self.username = username
        self.first_name, self.last_name = username.title(), "Tester"
        self.roles = roles
        self.active = True
        self.is_authenticated = True

    def get_full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


# Superset's security manager as the extension uses it: roles and permissions, and dataset access.
class FakeSecurityManager:
    def __init__(self, catalog: "Catalog") -> None:
        self.catalog = catalog
        self.ADMIN_ONLY_VIEW_MENUS = frozenset({"Security"})
        self.roles = {name: FakeRole(name) for name in (ADMIN, "Alpha", "Gamma")}
        self.permission_views: dict[tuple[str, str], tuple[str, str]] = {}

    def add_role(self, name: str) -> FakeRole:
        return self.roles.setdefault(name, FakeRole(name))

    def find_role(self, name: str) -> FakeRole | None:
        return self.roles.get(name)

    def add_permission_view_menu(self, permission_name: str, view_menu_name: str) -> tuple[str, str]:
        key = (permission_name, view_menu_name)
        return self.permission_views.setdefault(key, key)

    def find_permission_view_menu(self, permission_name: str, view_menu_name: str) -> tuple[str, str] | None:
        return self.permission_views.get((permission_name, view_menu_name))

    def add_permission_role(self, role: FakeRole, permission_view: tuple[str, str]) -> None:
        if permission_view not in role.permissions:
            role.permissions.append(permission_view)

    def del_permission_role(self, role: FakeRole, permission_view: tuple[str, str]) -> None:
        if permission_view in role.permissions:
            role.permissions.remove(permission_view)

    def can_access(self, permission_name: str, view_menu_name: str) -> bool:
        user = self.catalog.current_user
        return any((permission_name, view_menu_name) in role.permissions for role in user.roles)

    def raise_for_access(self, datasource: Any) -> None:
        from superset.exceptions import SupersetSecurityException

        if datasource.id in self.catalog.denied:
            raise SupersetSecurityException("no access")


# Superset's metadata as the DAOs return it. `hidden` stands for Superset's datasource filter, which leaves a dataset
# out of every DAO lookup; `denied` only fails raise_for_access.
class Catalog:
    def __init__(self) -> None:
        self.datasets: dict[int, SimpleNamespace] = {}
        self.hidden: set[int] = set()
        self.denied: set[int] = set()
        self.users: dict[int, FakeUser] = {}
        self.current_user: Any = SimpleNamespace(is_authenticated=False, roles=[])

    def add(self, *datasets: SimpleNamespace) -> None:
        for item in datasets:
            self.datasets[item.id] = item

    def visible(self) -> list[SimpleNamespace]:
        return [item for item in self.datasets.values() if item.id not in self.hidden]

    def find_dataset(self, **filters: Any) -> SimpleNamespace | None:
        return next((item for item in self.visible() if item.id == filters["id"]), None)

    def find_user(self, **filters: Any) -> FakeUser | None:
        return self.users.get(filters["id"])

    def active_users(self, **filters: Any) -> list[FakeUser]:
        return [user for user in self.users.values() if user.active == filters.get("active", True)]


class ApiResponse:
    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        self.status = status
        self.json = payload


class FakeApi:
    def response(self, status: int, **payload: Any) -> ApiResponse:
        return ApiResponse(status, payload)


# Runs a route with every decorator below Flask-AppBuilder's @protect and @safe: CSRF, rollback, error handling and the
# dataset lookup run as they do in Superset.
def call_route(
    app: Flask, route: Any, method: str = "GET", json_body: Any = None, query: dict[str, Any] | None = None,
    **url_arguments: Any,
) -> Any:
    body = route.__wrapped__.__wrapped__
    with app.test_request_context(method=method, json=json_body, query_string=query or {}):
        result = body(FakeApi(), **url_arguments)
        if not isinstance(result, ApiResponse):
            text = "".join(result.response)
            result.close()
            return text
    return result


def parse_events(text: str) -> list[tuple[str, Any]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events
