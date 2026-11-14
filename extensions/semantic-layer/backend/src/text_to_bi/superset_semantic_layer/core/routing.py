from typing import TYPE_CHECKING

# Route classes are mixins that SemanticLayerAPI joins onto Flask-AppBuilder's BaseApi. Only the type checker sees
# BaseApi here, so `self.response` resolves; at runtime the mixin stays a plain class and BaseApi comes in once.
if TYPE_CHECKING:
    from flask_appbuilder.api import BaseApi as RouteMixin
else:
    RouteMixin = object

__all__ = ["RouteMixin"]
