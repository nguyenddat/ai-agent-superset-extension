import json
from uuid import UUID

from flask_appbuilder.api import expose, permission_name, protect, safe
from superset.extensions import db
from superset_core.rest_api.api import RestApi
from superset_core.rest_api.decorators import api

from text_to_bi.superset_text_to_bi.core.database import handle_errors, rollback_on_error
from text_to_bi.superset_text_to_bi.core.routing import API_CLASS_PERMISSION, OPENAPI_TAG
from text_to_bi.superset_text_to_bi.core.security import csrf_protected
from text_to_bi.superset_text_to_bi.core.validation import request_body
from text_to_bi.superset_text_to_bi.modules.auth.services.srv_access import (
    can_access_dataset,
    require_admin,
    require_edit,
    require_view,
)
from text_to_bi.superset_text_to_bi.modules.data_dictionary.migrations import ensure_data_dictionary_tables
from text_to_bi.superset_text_to_bi.modules.data_dictionary.repositories.repo_superset_catalog import (
    SupersetDatabaseRepository,
    SupersetDatasetRepository,
)
from text_to_bi.superset_text_to_bi.modules.data_lineage.migrations import ensure_data_lineage_tables
from text_to_bi.superset_text_to_bi.modules.management_payload import json_payload
from text_to_bi.superset_text_to_bi.modules.superset.services.srv_dataset import (
    datasets_on_database,
    get_database,
    require_dataset,
)

from ..dependencies import business_model_service
from ..exceptions import BusinessModelNotFoundError
from ..migrations import ensure_business_model_tables
from ..schemas import CanvasIn, DatasetLayerIn, DomainIn, LayerIn, LayerOrderIn


@api(
    id="text_to_bi_business_model_api", name="Text to BI business model API",
    description="Manages business domains, data layers, and business canvas.", resource_name="business-model",
)
class BusinessModelAPI(RestApi):
    openapi_spec_tag = OPENAPI_TAG
    class_permission_name = API_CLASS_PERMISSION

    @staticmethod
    def _layer_out(row):
        return {"id": str(row.id), "name": row.name, "description": row.description, "color": row.color,
                "level": row.level, "sort_order": row.sort_order}

    @expose("/layers/", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_layers(self):
        require_view()
        ensure_business_model_tables()
        rows = business_model_service().list_layers()
        return self.response(200, layers=[self._layer_out(row) for row in rows])

    @expose("/layers/", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_layer(self):
        require_admin()
        ensure_business_model_tables()
        row = business_model_service().create_layer(request_body(LayerIn).model_dump())
        db.session.commit()
        return self.response(201, layer=self._layer_out(row))

    @expose("/layers/order", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def reorder_layers(self):
        require_admin()
        ensure_business_model_tables()
        order = [[UUID(value) for value in level] for level in request_body(LayerOrderIn).levels]
        rows = business_model_service().reorder_layers(order)
        db.session.commit()
        return self.response(200, layers=[self._layer_out(row) for row in rows])

    @expose("/layers/<layer_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_layer(self, layer_id: str):
        require_admin()
        ensure_business_model_tables()
        values = request_body(LayerIn).model_dump()
        row = business_model_service().update_layer(UUID(layer_id), values)
        db.session.commit()
        return self.response(200, layer=self._layer_out(row))

    @expose("/layers/<layer_id>", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def delete_layer(self, layer_id: str):
        require_admin()
        ensure_business_model_tables()
        business_model_service().delete_layer(UUID(layer_id))
        db.session.commit()
        return self.response(200, message="Data layer deleted.")

    @expose("/domains/", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def list_domains(self):
        require_view()
        ensure_business_model_tables()
        dataset_repository = SupersetDatasetRepository(db.session)
        database_repository = SupersetDatabaseRepository(db.session)
        allowed = {
            dataset.id for database in database_repository.read_all()
            for dataset in dataset_repository.read_by_database_id(database.id) if can_access_dataset(dataset)
        }
        rows = business_model_service().list_domains(allowed_dataset_ids=allowed)
        return self.response(200, domains=json_payload(rows))

    @expose("/domains/", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def create_domain(self):
        require_admin()
        ensure_data_dictionary_tables()
        ensure_business_model_tables()
        row = business_model_service().create_domain(request_body(DomainIn).model_dump())
        db.session.commit()
        return self.response(201, domain=json_payload(row))

    @expose("/domains/<domain_id>", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def update_domain(self, domain_id: str):
        require_admin()
        ensure_data_dictionary_tables()
        ensure_business_model_tables()
        values = request_body(DomainIn).model_dump()
        row = business_model_service().update_domain(UUID(domain_id), values)
        db.session.commit()
        return self.response(200, domain=json_payload(row))

    @expose("/domains/<domain_id>", methods=("DELETE",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def delete_domain(self, domain_id: str):
        require_admin()
        ensure_data_dictionary_tables()
        ensure_business_model_tables()
        business_model_service().delete_domain(UUID(domain_id))
        db.session.commit()
        return self.response(200, message="Business domain deleted.")

    @expose("/datasets/<int:dataset_id>/layer", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def assign_layer(self, dataset_id: int):
        dataset = require_dataset(dataset_id)
        require_edit(dataset)
        ensure_data_dictionary_tables()
        ensure_business_model_tables()
        body = request_body(DatasetLayerIn)
        layer_id = UUID(body.layer_id) if body.layer_id else None
        result = business_model_service().assign_layer(dataset.id, layer_id)
        db.session.commit()
        return self.response(200, assignment=result)

    @expose("/databases/<int:database_id>/canvas", methods=("PUT",))
    @protect()
    @safe
    @permission_name("write")
    @csrf_protected
    @rollback_on_error
    @handle_errors
    def save_canvas(self, database_id: int):
        require_admin()
        ensure_business_model_tables()
        layout = request_body(CanvasIn).layout
        row = business_model_service().save_canvas(database_id, layout)
        db.session.commit()
        return self.response(200, canvas={"database_id": database_id, "layout": json.loads(row.layout)})

    @expose("/databases/<int:database_id>", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    @handle_errors
    def get_business_model(self, database_id: int):
        require_view()
        ensure_data_dictionary_tables()
        ensure_business_model_tables()
        ensure_data_lineage_tables()
        if get_database(database_id) is None:
            raise BusinessModelNotFoundError("Database not found.")
        datasets = datasets_on_database(database_id)
        visible = []
        for dataset in datasets:
            if can_access_dataset(dataset):
                visible.append(dataset)
        result = business_model_service().get_model(database_id, visible)
        return self.response(200, **json_payload(result))
