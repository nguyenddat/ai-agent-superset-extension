import sys
import types
from types import SimpleNamespace

import pytest


def _module(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__path__ = []
    sys.modules[name] = module
    return module


# Superset is not installed locally: the backend imports these names from it, and the tests give each its fake.
if "superset" not in sys.modules:
    superset_stub = _module("superset")
    superset_stub.db = SimpleNamespace(session=None, engine=None)
    superset_stub.appbuilder = SimpleNamespace(add_view_no_menu=lambda view: None, get_url_for_login="/login/")
    extensions = _module("superset.extensions")
    extensions.db = superset_stub.db
    superset_stub.extensions = extensions
    exceptions = _module("superset.exceptions")
    exceptions.SupersetSecurityException = type("SupersetSecurityException", (Exception,), {})
    views = _module("superset.views")
    views_base = _module("superset.views.base")

    class BaseSupersetView:
        def render_app_template(self):
            return "app"

    views_base.BaseSupersetView = BaseSupersetView
    superset_stub.views = views
    views.base = views_base

# Superset replaces superset_core's @api decorator at startup; here it leaves the API class as it is.
from superset_core.rest_api import decorators

decorators.api = lambda **_options: (lambda api_class: api_class)

import superset
from flask import Flask
from flask_appbuilder import Model
from flask_appbuilder.security.sqla.models import User
from sqlalchemy import Column, Integer, Table, create_engine, event, insert
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from support import ADMIN, Catalog, FakeSecurityManager, FakeUser

if not hasattr(superset, "security_manager") or not isinstance(superset.security_manager, FakeSecurityManager):
    superset.security_manager = FakeSecurityManager(Catalog())
superset.extensions.security_manager = superset.security_manager


@compiles(PostgresUUID, "sqlite")
def _uuid_on_sqlite(type_, compiler, **kwargs):
    return "CHAR(36)"


# The Superset tables the extension's foreign keys point at.
SUPERSET_TABLES = Table("tables", Model.metadata, Column("id", Integer, primary_key=True), extend_existing=True)


class Environment:
    def __init__(self, engine, session, catalog: Catalog, app: Flask) -> None:
        self.engine, self.session, self.catalog, self.app = engine, session, catalog, app
        self.security_manager: FakeSecurityManager = superset.security_manager

    def add_user(self, user_id: int, username: str, *role_names: str) -> FakeUser:
        roles = [self.security_manager.add_role(name) for name in role_names]
        user = FakeUser(user_id, username, roles)
        with self.engine.begin() as connection:
            connection.execute(insert(User.__table__).values(
                id=user_id, first_name=user.first_name, last_name=user.last_name, username=username,
                email=f"{username}@example.com", active=True,
            ))
        self.catalog.users[user_id] = user
        return user

    def sign_in(self, user: FakeUser) -> FakeUser:
        self.catalog.current_user = user
        return user

    def add_datasets(self, *datasets) -> None:
        self.catalog.add(*datasets)
        with self.engine.begin() as connection:
            for item in datasets:
                connection.execute(insert(SUPERSET_TABLES).values(id=item.id))

    def delete_dataset(self, dataset_id: int) -> None:
        self.catalog.datasets.pop(dataset_id)
        with self.engine.begin() as connection:
            connection.execute(SUPERSET_TABLES.delete().where(SUPERSET_TABLES.c.id == dataset_id))


@pytest.fixture
def env(monkeypatch):
    from flask_login import utils as login_utils
    from superset_core.common import daos

    from text_to_bi.superset_text_to_bi import migrations
    from text_to_bi.superset_text_to_bi.core import security as core_security
    from text_to_bi.superset_text_to_bi.modules.data_dictionary.services import autofill_lock

    base_engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})

    @event.listens_for(base_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    # SQLite has no schemas: the extension's tables land in the main database.
    engine = base_engine.execution_options(schema_translate_map={"text_to_bi": None})
    Model.metadata.create_all(engine, tables=[SUPERSET_TABLES, User.__table__])
    session = Session(engine)
    catalog = Catalog()
    superset.security_manager.__init__(catalog)
    monkeypatch.setattr(superset.db, "session", session)
    monkeypatch.setattr(superset.db, "engine", engine)
    monkeypatch.setattr(daos.DatasetDAO, "find_all", classmethod(lambda cls: catalog.visible()))
    monkeypatch.setattr(daos.DatasetDAO, "find_one_or_none", classmethod(lambda cls, **f: catalog.find_dataset(**f)))
    monkeypatch.setattr(daos.UserDAO, "find_one_or_none", classmethod(lambda cls, **f: catalog.find_user(**f)))
    monkeypatch.setattr(daos.UserDAO, "filter_by", classmethod(lambda cls, **f: catalog.active_users(**f)))
    monkeypatch.setattr(login_utils, "_get_user", lambda: catalog.current_user)
    monkeypatch.setattr(core_security, "validate_csrf", lambda token: None)
    monkeypatch.setattr(migrations, "_tables_ready", False)
    monkeypatch.setattr(migrations, "_migration_failed_at", None)
    autofill_lock._local_running.clear()

    migrations.ensure_tables()
    environment = Environment(engine, session, catalog, Flask("text-to-bi-tests"))
    environment.sign_in(environment.add_user(1, "admin", ADMIN))
    yield environment
    session.close()
    base_engine.dispose()
