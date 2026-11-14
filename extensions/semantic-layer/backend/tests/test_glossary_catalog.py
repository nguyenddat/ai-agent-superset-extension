import ast
from types import SimpleNamespace

from catalog_source import MODULES_PATH, api_methods, compile_into, module_function

REVISION_REPOSITORY_PATH = MODULES_PATH / "glossary_management" / "repositories" / "repo_glossary_revision.py"


def _route_method(name):
    return api_methods()[name]


def _discovery_method():
    return _route_method("read_glossary_discovery")


def _discovery_source():
    """The endpoint, the helper it shares with the semantic catalog, and the repository query that filters rows."""
    repository = ast.parse(REVISION_REPOSITORY_PATH.read_text(encoding="utf-8"))
    functions = (node for node in ast.walk(repository) if isinstance(node, ast.FunctionDef))
    serving = next(node for node in functions if node.name == "read_all_serving")
    nodes = (_discovery_method(), module_function("discoverable_glossary_terms"), serving)
    return "\n".join(ast.unparse(node) for node in nodes)


def _call_name(node):
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


class _DiscoveryResponseAPI:
    def response(self, status, **payload):
        return status, payload


def _discovery_handler(revisions, datasets, links_by_revision, allowed_dataset_ids):
    """Execute the real discovery handler, without importing Superset."""
    method = _discovery_method()
    method.decorator_list = []
    helper = module_function("discoverable_glossary_terms")
    api = ast.ClassDef(
        name="HarnessAPI", bases=[ast.Name(id="RestApi", ctx=ast.Load())], keywords=[], body=[method], decorator_list=[]
    )

    namespace = {
        "RestApi": _DiscoveryResponseAPI,
        "Any": object,
        "SqlaTable": object,
        "db": SimpleNamespace(session=SimpleNamespace(get=lambda _model, key: datasets.get(key))),
        "get_dataset": lambda dataset_id: datasets.get(dataset_id),
        # Which revision serves each term is the repository's choice, tested in the service suite.
        "glossary_revision_repository": lambda: SimpleNamespace(read_all_serving=lambda: revisions),
        "ensure_dictionary_tables": lambda: None,
        "require_semantic_layer_query": lambda: None,
        "public_payload": lambda payload: payload,
        "can_access_dataset": lambda dataset: dataset.id in allowed_dataset_ids,
        "link_fingerprint": lambda dataset, kind, target=None: f"{dataset.id}:{kind}:{getattr(target, 'id', '')}",
        "read_links": lambda revision_id: links_by_revision.get(revision_id, []),
        "link_target": lambda link, _dataset: link.target,
        "metric_approved": lambda _dataset, _metric: True,
    }
    compile_into(namespace, helper, api)
    return namespace["HarnessAPI"]()


def test_discovery_is_authenticated_read_only_and_not_admin_gated():
    method = _discovery_method()
    decorators = [_call_name(item) for item in method.decorator_list]
    expose = next(item for item in method.decorator_list if _call_name(item) == "expose")
    assert ast.unparse(expose.args[0]) == "f'{prefix}/discovery'"
    assert next(keyword.value.elts[0].value for keyword in expose.keywords if keyword.arg == "methods") == "GET"
    assert "protect" in decorators and "safe" in decorators and "permission_name" in decorators
    assert "is_admin" not in ast.unparse(method)


def test_discovery_filters_to_serving_live_links_before_serialization():
    source = _discovery_source()
    assert "ReviewStatus.APPROVED" in source and "read_all_serving()" in source
    assert "fingerprint" in source.lower()
    assert "can_access_dataset" in source
    assert "links" in source


def test_discovery_contract_redacts_denied_dataset_b_and_hides_terms_without_allowed_links():
    """The handler must redact at link level; merely filtering term rows leaks B's identifiers."""
    source = _discovery_source()
    # The serializer must construct a filtered link collection and gate the term on it.
    assert "visible_links" in source or "authorized_links" in source or "allowed_links" in source
    assert "if not" in source and "links" in source
    # Discovery is a consumer projection: no unsafe provenance/source fields may be emitted.
    assert "source_reference" not in source and "source_hash" not in source


def test_discovery_cannot_accept_a_client_selected_dataset_or_link_id_scope():
    """A valid ID from dataset B must never widen discovery for a caller allowed only dataset A."""
    source = _discovery_source()
    assert "request.args" not in source
    assert "request.get_json" not in source


def test_discovery_executes_link_level_redaction_and_omits_terms_without_visible_links():
    allowed = SimpleNamespace(id=7)
    denied = SimpleNamespace(id=8)
    group = SimpleNamespace(id=4, name="Nhiệt độ")
    first = SimpleNamespace(
        id=101, term_id=1, definition="Allowed", synonyms=[], term=SimpleNamespace(canonical_name="A", group=group)
    )
    second = SimpleNamespace(
        id=102, term_id=2, definition="Denied", synonyms=[], term=SimpleNamespace(canonical_name="B", group=None)
    )
    allowed_link = SimpleNamespace(
        kind="dataset", dataset_id=7, column_name=None, metric_id=None, target=None, fingerprint="7:dataset:"
    )
    denied_link = SimpleNamespace(
        kind="dataset", dataset_id=8, column_name=None, metric_id=None, target=None, fingerprint="8:dataset:"
    )
    api = _discovery_handler([first, second], {7: allowed, 8: denied}, {101: [allowed_link], 102: [denied_link]}, {7})

    status, body = api.read_glossary_discovery()

    assert status == 200
    assert body == {
        "terms": [
            {
                "term_id": 1,
                "canonical_name": "A",
                # The group lets a consumer read terms of the same meaning together.
                "group": {"id": 4, "name": "Nhiệt độ"},
                "definition": "Allowed",
                "synonyms": [],
                "links": [{"kind": "dataset", "dataset_id": 7, "column_name": None, "metric_id": None}],
            }
        ]
    }
    assert "B" not in repr(body) and "8" not in repr(body)


def test_drafts_ai_candidates_revoked_and_stale_objects_are_not_consumer_knowledge():
    source = _discovery_source()
    assert "draft" not in source or "!= 'draft'" in source or '!= "draft"' in source
    assert "revoked" not in source or "!= 'revoked'" in source or '!= "revoked"' in source
    # Only an approved serving revision reaches consumers.
    assert "ReviewStatus.APPROVED" in source and "read_all_serving()" in source
