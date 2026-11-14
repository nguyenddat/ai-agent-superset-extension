from types import SimpleNamespace

import pytest

from text_to_bi.superset_ai_agent.common.public import public_payload, public_result
from text_to_bi.superset_ai_agent.modules.semantic_layer.exceptions import SemanticLayerRefusedError, SemanticLayerUnavailableError
from text_to_bi.superset_ai_agent.modules.semantic_layer.services import client, public_metadata
from text_to_bi.superset_ai_agent.modules.semantic_query.services import graph
from text_to_bi.superset_ai_agent.modules.semantic_query.services.catalog import assemble_catalog


def dataset(dataset_id=7, row_security=False):
    return {'id': dataset_id, 'name': f'base_{dataset_id}', 'schema': 'public', 'is_virtual': False, 'row_level_security': row_security,
            'database': {'id': 3, 'name': 'Warehouse', 'dialect': 'postgresql'},
            'dictionary': {'contains_pii': True, 'dataset_type': 'base', 'display_name': 'Base', 'description': None, 'grain': None, 'time_column': None, 'row_kind_column': None},
            'dictionary_columns': [{'column_name': 'id', 'display_name': 'Identifier', 'contains_pii': True}],
            'columns': [{'column_name': 'id', 'verbose_name': None, 'type': 'INTEGER', 'is_active': True, 'expression': None, 'is_dttm': False, 'groupby': True, 'filterable': True}],
            'grains': [], 'layer': None}


def metric(state='approved'):
    return {'dataset_id': 7, 'metric_id': 9, 'metric_name': 'count', 'label': 'Count', 'expression': 'COUNT(*)', 'description': None,
            'd3format': None, 'state': state, 'origin': 'manual', 'definition': 'Count rows', 'unit': None, 'steward_name': None, 'query_defaults': None}


@pytest.mark.parametrize('payload', [None, [], {'result': {}}, {'schema_version': True, 'result': {}}, {'schema_version': 2, 'result': {}}, {'schema_version': 1, 'result': []}])
def test_public_schema_rejects_unsupported_or_malformed_envelope(payload):
    with pytest.raises(ValueError):
        public_result(payload)


def test_public_envelope_round_trip():
    payload = public_payload({'datasets': []})
    assert payload == {'schema_version': 1, 'result': {'datasets': []}}
    assert public_result(payload) == {'datasets': []}


@pytest.mark.parametrize('state', ['candidate', 'draft', 'outdated', 'revoked', 'not_started', 'ineligible'])
def test_catalog_excludes_unapproved_metrics(state):
    result = assemble_catalog({'datasets': [dataset()]}, {'metrics': [metric(state)], 'limits': {'max_rows': 100}}, [], [])
    assert result['datasets'] == []


def test_catalog_preserves_approved_context_and_pii():
    term = {'term_id': 2, 'canonical_name': 'Count', 'synonyms': [], 'links': [{'kind': 'metric', 'metric_id': 9}]}
    result = assemble_catalog({'datasets': [dataset()]}, {'metrics': [metric()], 'limits': {'max_rows': 100}}, [], [term])
    entry = result['datasets'][0]
    assert entry['contains_pii'] is True
    assert entry['dimensions'][0]['label'] == 'Identifier'
    assert entry['dimensions'][0]['contains_pii'] is True
    assert entry['metrics'][0]['glossary_terms'][0]['term_id'] == 2
    assert result['limits']['joins_supported'] is False


def test_catalog_drops_relationship_when_either_end_is_not_visible():
    relationship = {'id': 1, 'from_dataset_id': 7, 'to_dataset_id': 8, 'from_column': 'id', 'to_column': 'id', 'cardinality': 'many_to_one'}
    result = assemble_catalog({'datasets': [dataset()]}, {'metrics': [], 'limits': {'max_rows': 100}}, [relationship], [])
    assert result['relationships'] == [] and result['datasets'] == []


@pytest.mark.parametrize('bad_rows', [[{'id': True}], [dataset(), dataset()], [{'id': 7, 'columns': []}]])
def test_adapter_rejects_malformed_dataset_metadata(monkeypatch, bad_rows):
    monkeypatch.setattr(public_metadata, 'get_public_json', lambda *_: {'datasets': bad_rows})
    with pytest.raises(SemanticLayerUnavailableError):
        public_metadata.dictionary_metadata('cookie')


def test_graph_excludes_rls_tables_and_their_edges(monkeypatch):
    monkeypatch.setattr(graph, 'dictionary_metadata', lambda *_: {'datasets': [dataset(), dataset(8, True)], 'database': {'id': 3}})
    monkeypatch.setattr(graph, 'relationship_metadata', lambda *_: [{'id': 1, 'from_dataset_id': 7, 'to_dataset_id': 8}])
    monkeypatch.setattr(graph, 'dataset_context', lambda row: (SimpleNamespace(id=row['id']), None, {}, [], None))
    monkeypatch.setattr(graph, 'coded_values', lambda *_: {})
    monkeypatch.setattr(graph, 'table_node', lambda source, *_: {'dataset_id': source.id})
    result = graph.read_schema_graph(3, 'cookie')
    assert result['tables'] == [{'dataset_id': 7}]
    assert result['edges'] == []
    assert result['excluded'][0]['dataset_id'] == 8


def test_metric_limits_cannot_be_boolean(monkeypatch):
    monkeypatch.setattr(public_metadata, 'get_public_json', lambda *_: {'metrics': [metric()], 'limits': {'max_rows': True}})
    with pytest.raises(SemanticLayerUnavailableError):
        public_metadata.metric_metadata('cookie')


def test_get_rejects_malformed_upstream_json_as_unavailable(monkeypatch):
    response = SimpleNamespace(status_code=200, json=lambda: (_ for _ in ()).throw(ValueError('invalid JSON')))
    monkeypatch.setattr(client.requests, 'get', lambda *_args, **_kwargs: response)
    with pytest.raises(SemanticLayerUnavailableError) as failure:
        client.get_json('/public', 'cookie')
    assert failure.value.status == 503


def test_post_maps_upstream_server_error_to_unavailable(monkeypatch):
    response = SimpleNamespace(status_code=500, headers={'Content-Type': 'application/json'}, json=lambda: {'message': 'private upstream detail'})
    monkeypatch.setattr(client.requests, 'post', lambda *_args, **_kwargs: response)
    with pytest.raises(SemanticLayerRefusedError) as failure:
        client.post_json('/public', {}, 'cookie', 'csrf', 'submit')
    assert failure.value.status == 503
    assert 'private upstream detail' not in str(failure.value)


def test_relationship_ids_are_unique_across_different_endpoints(monkeypatch):
    relationships = [
        {'id': 4, 'from_dataset_id': 7, 'to_dataset_id': 8, 'from_column': 'id', 'to_column': 'id', 'cardinality': 'many_to_one'},
        {'id': 4, 'from_dataset_id': 9, 'to_dataset_id': 10, 'from_column': 'id', 'to_column': 'id', 'cardinality': 'many_to_one'},
    ]
    monkeypatch.setattr(public_metadata, 'get_public_json', lambda *_: {'relationships': relationships})
    with pytest.raises(SemanticLayerUnavailableError) as failure:
        public_metadata.relationship_metadata('cookie')
    assert failure.value.status == 503


def test_dictionary_rejects_boolean_database_identifier(monkeypatch):
    malformed = dataset()
    malformed['database']['id'] = True
    monkeypatch.setattr(public_metadata, 'get_public_json', lambda *_: {'database': None, 'datasets': [malformed]})
    with pytest.raises(SemanticLayerUnavailableError) as failure:
        public_metadata.dictionary_metadata('cookie')
    assert failure.value.status == 503
