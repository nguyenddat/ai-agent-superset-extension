import sys
import types
from types import SimpleNamespace


def _module(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__path__ = []
    sys.modules[name] = module
    return module


if "superset" not in sys.modules:
    superset = _module("superset")
    superset.db = SimpleNamespace(session=None)
    superset.security_manager = SimpleNamespace()
    helpers = _module("superset.models.helpers")

    class AuditMixinNullable:
        pass

    helpers.AuditMixinNullable = AuditMixinNullable
    exceptions = _module("superset.exceptions")

    class SupersetSecurityException(Exception):
        pass

    exceptions.SupersetSecurityException = SupersetSecurityException
    connectors = _module("superset.connectors")
    sqla = _module("superset.connectors.sqla")
    models = _module("superset.connectors.sqla.models")

    class SqlaTable:
        pass

    models.SqlaTable = SqlaTable
    superset.connectors = connectors
    connectors.sqla = sqla
    sqla.models = models
