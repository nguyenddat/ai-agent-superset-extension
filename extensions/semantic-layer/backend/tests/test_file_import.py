import ast
import base64
import io
import threading
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from catalog_source import MODULES_PATH, compile_into, module_function
from test_expert_rule_service import _current_rule_group_service, _current_rule_service
from test_pii_flags import _dictionary_constants

from text_to_bi.superset_semantic_layer.common.exceptions import SemanticLayerError
from text_to_bi.superset_semantic_layer.common.utils import table_file
from text_to_bi.superset_semantic_layer.common.utils.table_file import TemplateColumn, read_table, write_table
from text_to_bi.superset_semantic_layer.common.utils.type_formatter import json_list
from text_to_bi.superset_semantic_layer.modules.data_dictionary.exceptions import DataDictionaryValidationError
from text_to_bi.superset_semantic_layer.modules.data_dictionary.services import srv_column_semantics as column_semantics
from text_to_bi.superset_semantic_layer.modules.data_dictionary.services.srv_grain import checked_temporal_kind
from text_to_bi.superset_semantic_layer.modules.data_dictionary.services.srv_pii import checked_pii_flag
from text_to_bi.superset_semantic_layer.modules.expert_rule_management.exceptions import ExpertRuleValidationError
from text_to_bi.superset_semantic_layer.modules.expert_rule_management.services import srv_expert_rule as rule_service
from text_to_bi.superset_semantic_layer.modules.expert_rule_management.services import srv_expert_rule_file as rule_file
from text_to_bi.superset_semantic_layer.modules.glossary_management.exceptions import GlossaryValidationError
from text_to_bi.superset_semantic_layer.modules.glossary_management.services import srv_glossary_file as glossary_file
from text_to_bi.superset_semantic_layer.modules.glossary_management.services.srv_glossary_term import GlossaryTermService

TERM_FILE_PATH = MODULES_PATH / "glossary_management" / "services" / "srv_glossary_file.py"
DICTIONARY_FILE_PATH = MODULES_PATH / "data_dictionary" / "services" / "srv_dictionary_file.py"
TABLE_HELPERS = {
    name: getattr(table_file, name)
    for name in (
        "ImportRow", "TemplateColumn", "dataset_named", "flag_text", "join_list", "parse_flag", "read_table",
        "refusal_message", "split_list", "write_table", "write_template",
    )
}


class FileError(SemanticLayerError):
    status = 400


def _file(headers, rows) -> dict[str, str]:
    columns = [TemplateColumn(header, True, "", "") for header in headers]
    return write_table(columns, rows, "file", FileError)


def _module_nodes(path) -> list[ast.stmt]:
    return [
        node
        for node in ast.parse(path.read_text(encoding="utf-8")).body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Assign))
    ]


# The shared file reader and writer.


def test_excel_table_reads_headers_case_insensitively_and_preserves_multiline_cells():
    columns = [TemplateColumn("name", True, "", ""), TemplateColumn("definition", True, "", ""),
               TemplateColumn("links", False, "", ""), TemplateColumn("group", False, "", "")]
    payload = write_table(columns, [["Revenue", "Recognized\nrevenue.", "dataset:sales", ""], ["Cost", "Spent", "", ""]], "terms", FileError)
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(base64.b64decode(payload["content"])))
    workbook[table_file.DATA_SHEET]["A1"] = " Name "
    buffer = io.BytesIO()
    workbook.save(buffer)
    payload["content"] = base64.b64encode(buffer.getvalue()).decode("ascii")
    assert read_table(payload, columns, FileError) == [
        (2, {"name": "Revenue", "definition": "Recognized\nrevenue.", "links": "dataset:sales", "group": ""}),
        (3, {"name": "Cost", "definition": "Spent", "links": "", "group": ""}),
    ]


@pytest.mark.parametrize(
    "payload, message",
    [
        (None, "Chọn một file Excel"),
        ({"content": "%%%"}, "Không đọc được nội dung file"),
        (_file(("name", "color"), [["A", "red"]]), "cột không hỗ trợ"),
        (_file(("definition",), [["A"]]), "File thiếu cột: name"),
        (_file(("name", "Name"), [["A", "B"]]), "bị lặp tên"),
        (write_table([TemplateColumn("name", True, "", ""), TemplateColumn("definition", True, "", "")], [], "empty", FileError), "File không có dòng dữ liệu"),
        (write_table([TemplateColumn("name", True, "", ""), TemplateColumn("definition", True, "", "")], [[str(index), "x"] for index in range(1_001)], "many", FileError), "hơn 1000 dòng"),
        ({"filename": "a.csv", "content": "A" * 1_400_000}, "vượt quá 1 MB"),
    ],
)
def test_a_file_that_cannot_be_imported_is_refused_with_a_vietnamese_reason(payload, message):
    with pytest.raises(FileError, match=message):
        read_table(payload, [TemplateColumn("name", True, "", ""), TemplateColumn("definition", True, "", "")], FileError)


def test_a_written_excel_file_reads_back_the_same_rows():
    columns = [TemplateColumn("name", True, "", ""), TemplateColumn("conditions", True, "", "")]
    exported = write_table(columns, [["Nắng nóng", "a | equals | x\nb | is_null"]], "rule", FileError)

    assert exported["filename"] == "rule.xlsx" and exported["media_type"] == table_file.XLSX_MEDIA_TYPE
    rows = read_table(exported, columns, FileError)
    assert rows == [(2, {"name": "Nắng nóng", "conditions": "a | equals | x\nb | is_null"})]
def test_an_xlsx_file_round_trips_when_openpyxl_is_installed():
    pytest.importorskip("openpyxl")
    columns = [TemplateColumn("name", True, "", ""), TemplateColumn("contains_pii", True, "", "")]
    exported = write_table(columns, [["Trạm", "true"]], "dictionary", FileError)
    assert exported["filename"] == "dictionary.xlsx"
    assert read_table(exported, columns, FileError) == [(2, {"name": "Trạm", "contains_pii": "true"})]


def test_list_flag_and_dataset_name_cells():
    assert table_file.split_list(" a; ;b ;") == ["a", "b"] and table_file.join_list(["a", "b"]) == "a; b"
    assert [table_file.parse_flag(word) for word in ("TRUE", "x", "có", "", "0", "Không", "maybe")] == [
        True, True, True, False, False, False, None,
    ]
    weather = SimpleNamespace(id=7)
    assert table_file.dataset_named("weather", {"weather": [weather]}, FileError) is weather
    with pytest.raises(FileError, match="Không có dataset «rain»"):
        table_file.dataset_named("rain", {"weather": [weather]}, FileError)
    with pytest.raises(FileError, match="2 dataset cùng tên"):
        table_file.dataset_named("weather", {"weather": [weather, SimpleNamespace(id=8)]}, FileError)


# Glossary terms: the real term service and file import on SQLite tables.


def _glossary(monkeypatch):
    terms, revisions, links, groups, events = {}, {}, {}, {}, []
    dataset = SimpleNamespace(id=7, table_name="daily_weather", columns=[], metrics=[])
    users = {7: SimpleNamespace(id=7, username="an"), 8: SimpleNamespace(id=8, username="bao")}

    class TermRepository:
        def read(self, term_id):
            return terms.get(term_id)

        def read_for_update(self, term_id):
            return self.read(term_id)

        def read_by_normalized_name(self, name):
            return next((term for term in terms.values() if term.normalized_name == name), None)

        def read_all(self):
            return list(terms.values())

        def add(self, term):
            term.id = max(terms, default=0) + 1
            term.group_id = term.group.id if term.group is not None else None
            terms[term.id] = term

    class RevisionRepository:
        def create(self, values):
            revision_id = max(revisions, default=0) + 1
            revision = SimpleNamespace(id=revision_id, **values)
            revision.term = terms[revision.term_id]
            revisions[revision_id] = revision
            return revision

        def read_current(self, term_id):
            return next((revision for revision in revisions.values() if revision.term_id == term_id and revision.is_current), None)

        def read_current_for_update(self, term_id):
            return self.read_current(term_id)

        def read_by_term(self, term_id):
            return [revision for revision in revisions.values() if revision.term_id == term_id]

        def read_serving(self, term_id):
            return next((revision for revision in revisions.values() if revision.term_id == term_id and revision.status == "approved"), None)

    class LinkRepository:
        def create(self, values, flush=True):
            links.setdefault(values["revision_id"], []).append(SimpleNamespace(**values))

        def read_by_revision(self, revision_id):
            return links.get(revision_id, [])

    class GroupRepository:
        def read_by_normalized_name(self, name):
            return next((group for group in groups.values() if group.normalized_name == name), None)

        def create(self, values):
            group = SimpleNamespace(id=max(groups, default=0) + 1, **values)
            groups[group.id] = group
            return group

        def read_all(self):
            return list(groups.values())

        def read(self, group_id):
            return groups.get(group_id)

        def update(self, group, values):
            for key, value in values.items():
                setattr(group, key, value)
            return group

    term_repository, revision_repository = TermRepository(), RevisionRepository()
    link_repository, group_repository = LinkRepository(), GroupRepository()
    class EventRepository:
        def create(self, values, flush=False):
            events.append(SimpleNamespace(**values))

        def read_author_id(self, revision):
            return next((event.actor_id for event in events if event.revision_id == revision.id and event.event_type in {"created", "updated"}), None)

        def read_latest_authoring(self, revision_id):
            return next((event for event in reversed(events) if event.revision_id == revision_id and event.event_type in {"created", "updated"}), None)

        def read_history(self, term_id):
            return [event for event in events if event.term_id == term_id]

    event_repository = EventRepository()
    from text_to_bi.superset_semantic_layer.modules.glossary_management.services import (
        srv_glossary_event,
        srv_glossary_group,
        srv_glossary_term,
    )
    monkeypatch.setattr(srv_glossary_term, "GlossaryTerm", lambda **values: SimpleNamespace(id=None, group_id=None, **values))
    monkeypatch.setattr(srv_glossary_group, "GlossaryTermGroup", lambda **values: SimpleNamespace(id=None, **values))

    for module in (srv_glossary_event, srv_glossary_term, srv_glossary_group, glossary_file):
        monkeypatch.setattr(module, "glossary_term_repository", lambda: term_repository, raising=False)
        monkeypatch.setattr(module, "glossary_revision_repository", lambda: revision_repository, raising=False)
        monkeypatch.setattr(module, "glossary_link_repository", lambda: link_repository, raising=False)
        monkeypatch.setattr(module, "glossary_group_repository", lambda: group_repository, raising=False)
        monkeypatch.setattr(module, "glossary_event_repository", lambda: event_repository, raising=False)
        monkeypatch.setattr(module, "glossary_event_repository", lambda: event_repository, raising=False)
    monkeypatch.setattr(srv_glossary_term, "get_user", lambda user_id: users.get(user_id))
    monkeypatch.setattr(srv_glossary_term, "get_dataset", lambda dataset_id: dataset if dataset_id == 7 else None)
    monkeypatch.setattr(srv_glossary_term, "metric_approved", lambda _dataset, _metric: True)
    monkeypatch.setattr(glossary_file, "get_user", lambda user_id: users.get(user_id))
    monkeypatch.setattr(glossary_file, "metric_approved", lambda _dataset, _metric: True)
    monkeypatch.setattr(glossary_file, "business_datasets_by_name", lambda: {"daily_weather": [dataset]})
    monkeypatch.setattr(glossary_file, "get_dataset", lambda dataset_id: dataset if dataset_id == 7 else None)
    monkeypatch.setattr(glossary_file, "security_manager", SimpleNamespace(find_user=lambda username: next((user for user in users.values() if user.username == username), None)))
    monkeypatch.setattr(glossary_file, "get_user", lambda user_id: users.get(user_id))

    class AuditRepository:
        def for_term(self, term_id):
            return event_repository.read_history(term_id)

    class CurrentRevisionRepository(RevisionRepository):
        def current_for(self, term_id):
            return self.read_current(term_id)

        def serving_for(self, term_id):
            return self.read_serving(term_id)

        def for_term(self, term_id):
            return self.read_by_term(term_id)

    class CurrentTermRepository(TermRepository):
        def by_canonical_name(self):
            return sorted(terms.values(), key=lambda term: term.canonical_name)

    class CurrentGroupRepository(GroupRepository):
        def by_name(self):
            return list(groups.values())

    service = SimpleNamespace(
        preview_term_import=glossary_file.preview_term_import,
        apply_term_import=glossary_file.apply_term_import,
        export_terms=glossary_file.export_terms,
        approve_revision=lambda term_id, expected, actor, reason, second: GlossaryTermService().approve(term_id, expected, actor, reason, second),
        glossary_term_repository=lambda: CurrentTermRepository(),
        glossary_term_revision_repository=lambda: CurrentRevisionRepository(),
        glossary_term_audit_event_repository=lambda: AuditRepository(),
        glossary_term_group_repository=lambda: CurrentGroupRepository(),
        LINK_FORMAT=glossary_file.LINK_FORMAT,
        get_dataset=lambda dataset_id: dataset if dataset_id == 7 else None,
    )
    return service, SimpleNamespace(commit=lambda: None, rollback=lambda: None)


def _term_file(*rows):
    return _file(("canonical_name", "definition", "synonyms", "group", "steward", "links"), rows)


def _actions(rows):
    return [(item.action, item.message) for item in rows]


def test_a_term_file_creates_drafts_with_their_group_and_steward_and_reads_back_unchanged(monkeypatch):
    service, session = _glossary(monkeypatch)
    upload = _term_file(
        ["Revenue", "Recognized revenue.", "sales; turnover", "Tài chính", "bao", "dataset:daily_weather"],
        ["Cost", "Money spent.", "", "Tài chính", "", "dataset:daily_weather"],
    )
    preview = service.preview_term_import(upload)
    assert _actions(preview) == [("create", "Tạo thuật ngữ mới, chờ duyệt. Tạo nhóm mới «Tài chính».")] * 2
    assert service.glossary_term_repository().by_canonical_name() == []

    service.apply_term_import(upload, 7)
    session.commit()

    terms = service.glossary_term_repository().by_canonical_name()
    assert [(term.canonical_name, term.steward_id, term.group.name) for term in terms] == [
        ("Cost", None, "Tài chính"),
        ("Revenue", 8, "Tài chính"),
    ]
    revisions = service.glossary_term_revision_repository()
    revenue = revisions.current_for(terms[1].id)
    assert (revenue.status, revenue.synonyms, revenue.revision_number) == ("draft", ["sales", "turnover"], 1)
    assert [event.event_type for event in service.glossary_term_audit_event_repository().for_term(terms[1].id)] == [
        "created"
    ]
    assert len(service.glossary_term_group_repository().by_name()) == 1

    exported = service.export_terms()
    preview = service.preview_term_import(exported)
    assert {item.action for item in preview} == {"unchanged"}, [(item.action, item.changes, item.message) for item in preview]


def test_a_term_file_edit_of_an_approved_term_adds_a_draft_and_keeps_the_approved_revision_serving(monkeypatch):
    service, session = _glossary(monkeypatch)
    service.apply_term_import(_term_file(["Revenue", "Recognized revenue.", "", "", "", "dataset:daily_weather"]), 7)
    term_id = service.glossary_term_repository().by_canonical_name()[0].id
    service.approve_revision(term_id, 1, 8, None, False)
    session.commit()

    upload = _term_file(["revenue", "Revenue net of returns.", "", "", "", "dataset:daily_weather"])
    [item] = service.preview_term_import(upload)
    assert (item.action, item.changes) == ("update", ["definition"])
    assert "bản đã duyệt vẫn được dùng" in item.message
    service.apply_term_import(upload, 7)
    session.commit()

    revisions = service.glossary_term_revision_repository()
    assert (revisions.current_for(term_id).revision_number, revisions.current_for(term_id).status) == (2, "draft")
    assert revisions.serving_for(term_id).revision_number == 1
    events = service.glossary_term_audit_event_repository().for_term(term_id)
    assert [event.event_type for event in events] == ["created", "approved", "updated"]


def test_a_term_file_that_only_changes_the_group_moves_the_term_without_review(monkeypatch):
    service, session = _glossary(monkeypatch)
    service.apply_term_import(_term_file(["Revenue", "Recognized revenue.", "", "", "", "dataset:daily_weather"]), 7)
    term_id = service.glossary_term_repository().by_canonical_name()[0].id
    service.approve_revision(term_id, 1, 8, None, False)
    session.commit()

    upload = _term_file(["Revenue", "Recognized revenue.", "", "Doanh thu", "", "dataset:daily_weather"])
    [item] = service.preview_term_import(upload)
    assert (item.action, item.changes) == ("update", ["group"])
    service.apply_term_import(upload, 8)
    session.commit()

    revisions = service.glossary_term_revision_repository()
    assert [revision.revision_number for revision in revisions.for_term(term_id)] == [1]
    assert revisions.serving_for(term_id).status == "approved"
    events = service.glossary_term_audit_event_repository().for_term(term_id)
    assert (events[-1].event_type, events[-1].reason) == ("moved", "Chưa phân nhóm → Doanh thu")


def test_an_unchanged_term_reads_back_after_its_metric_lost_approval_but_an_edit_of_it_is_refused(monkeypatch):
    service, session = _glossary(monkeypatch)
    namespace = SimpleNamespace(get_dataset=service.get_dataset)
    namespace.get_dataset(7).metrics.append(SimpleNamespace(id=21, metric_name="rain_days", expression="SUM(1)"))
    row = ["Rainy day", "A day with rain.", "", "", "", "metric:daily_weather.rain_days"]
    service.apply_term_import(_term_file(row), 7)
    session.commit()
    monkeypatch.setattr(glossary_file, "metric_approved", lambda _dataset, _metric: False)

    assert _actions(service.preview_term_import(service.export_terms())) == [("unchanged", None)]
    moved = [*row[:3], "Mưa", *row[4:]]
    assert [item.action for item in service.preview_term_import(_term_file(moved))] == ["update"]
    edited = [row[0], "Any day with rain.", *row[2:]]
    refused = ("error", "Thuật ngữ chỉ được liên kết metric đã duyệt.")
    assert _actions(service.preview_term_import(_term_file(edited))) == [refused]
    new_term = ["Wet day", "A wet day.", "", "", "", "metric:daily_weather.rain_days"]
    assert _actions(service.preview_term_import(_term_file(new_term))) == [refused]


def test_a_term_file_with_a_failing_row_reports_every_reason_and_saves_nothing(monkeypatch):
    service, session = _glossary(monkeypatch)
    upload = _term_file(
        ["Revenue", "Recognized revenue.", "", "", "", "dataset:daily_weather"],
        ["revenue", "Again.", "", "", "", "dataset:daily_weather"],
        ["Cost", "", "", "", "", "dataset:daily_weather"],
        ["Rain", "Rainfall.", "", "", "", "dataset:monthly_rain"],
        ["Heat", "Hot days.", "", "", "nobody", "column:daily_weather.temperature"],
        ["Wind", "Wind speed.", "", "", "", "table daily_weather"],
        ["Snow", "Snowfall.", "", "", "", ""],
    )
    assert _actions(service.preview_term_import(upload)) == [
        ("create", "Tạo thuật ngữ mới, chờ duyệt."),
        ("error", "Thuật ngữ trùng với dòng 2."),
        ("error", "Thiếu định nghĩa."),
        ("error", "Không có dataset «monthly_rain»."),
        ("error", "Không có người dùng «nobody»."),
        ("error", "Liên kết «table daily_weather» phải có dạng " + service.LINK_FORMAT + "."),
        ("error", "Cần ít nhất một liên kết."),
    ]
    with pytest.raises(GlossaryValidationError, match="File có 6 dòng lỗi"):
        service.apply_term_import(upload, 7)
    session.rollback()
    assert service.glossary_term_repository().by_canonical_name() == []


# Expert rules: the real rule service and file import on SQLite tables.


def _rules(monkeypatch):
    rules_service, rule_rows, revisions, links, events = _current_rule_service(monkeypatch)
    groups_service, groups = _current_rule_group_service(rules_service)
    rules_service.groups = groups_service
    dataset = SimpleNamespace(id=7, table_name="daily_weather")
    columns = [
        SimpleNamespace(id=70, dataset_id=7, column_name="observation_status"),
        SimpleNamespace(id=71, dataset_id=7, column_name="temperature"),
    ]
    terms = {
        "nắng nóng": SimpleNamespace(id=3, canonical_name="Nắng nóng"),
        "bản nháp": SimpleNamespace(id=4, canonical_name="Bản nháp"),
    }
    term_repository = SimpleNamespace(
        read_by_normalized_name=lambda name: terms.get(name),
        read=lambda term_id: next((term for term in terms.values() if term.id == term_id), None),
    )

    class RevisionRepository:
        def read_all_current(self):
            return [revision for revision in revisions.values() if revision.is_current]

    revision_repository = RevisionRepository()
    rule_repository = rules_service.rules
    rule_repository.read_all = lambda: list(rule_rows.values())
    rule_repository.read_by_normalized_name = lambda name: next(
        (rule for rule in rule_rows.values() if rule.normalized_name == name), None
    )
    rules_service.revisions.read_all_current = revision_repository.read_all_current
    groups_repo = groups_service.groups
    links_repo = rules_service.links

    def column_resolver(dataset_id):
        def resolve(reference):
            if isinstance(reference, str):
                return [column for column in columns if column.column_name == reference]
            return next((column for column in columns if column.id == reference), None)

        return resolve

    monkeypatch.setattr(rule_service, "column_resolver", column_resolver)

    def term_metrics(payload):
        term_ids = payload.get("glossary_term_ids", [])
        return {**payload, "metric_ids": [9] if 3 in term_ids else []}

    def validate_links(values):
        if not values["glossary_term_ids"]:
            raise ExpertRuleValidationError("An expert rule needs at least one approved glossary term.")
        for term_id in values["glossary_term_ids"]:
            if term_id != 3:
                raise ExpertRuleValidationError("Invalid glossary link.")
        if any(metric_id != 9 for metric_id in values["metric_ids"]):
            raise ExpertRuleValidationError("Invalid metric link.")

    def rule_links(values):
        result = [
            {"kind": "glossary", "target_id": term_id, "dataset_id": values["dataset_id"], "fingerprint": "live"}
            for term_id in values["glossary_term_ids"]
        ]
        result.extend(
            {"kind": "metric", "target_id": metric_id, "dataset_id": values["dataset_id"], "fingerprint": "live"}
            for metric_id in values["metric_ids"]
        )
        return result

    monkeypatch.setattr(rule_service, "rule_links", rule_links)
    monkeypatch.setattr(rule_file, "business_datasets_by_name", lambda: {"daily_weather": [dataset]})
    monkeypatch.setattr(rule_file, "get_dataset", lambda dataset_id: dataset if dataset_id == 7 else None)
    monkeypatch.setattr(rule_file, "column_resolver", column_resolver)
    monkeypatch.setattr(rule_file, "with_term_metrics", term_metrics)
    monkeypatch.setattr(rule_file, "validate_semantic_links", validate_links)
    monkeypatch.setattr(rule_file, "expert_rule_repository", lambda: rule_repository)
    monkeypatch.setattr(rule_file, "expert_rule_revision_repository", lambda: rules_service.revisions)
    monkeypatch.setattr(rule_file, "expert_rule_link_repository", lambda: links_repo)
    monkeypatch.setattr(rule_file, "expert_rule_group_repository", lambda: groups_repo)
    monkeypatch.setattr(rule_file, "glossary_term_repository", lambda: term_repository)
    monkeypatch.setattr(rule_file, "ExpertRuleService", lambda: rules_service)
    monkeypatch.setattr(rule_file, "ExpertRuleGroupService", lambda: groups_service)
    return SimpleNamespace(
        session=SimpleNamespace(commit=lambda: None, rollback=lambda: None),
        service=rules_service,
        rule_rows=rule_rows,
        revisions=revisions,
        links=links,
        events=events,
        groups=groups,
        dataset=dataset,
        columns=columns,
        term_repository=term_repository,
    )


RULE_HEADERS = ("name", "dataset", "group", "glossary_terms", "conditions", "exceptions", "examples")
RULE_ROW = [
    "Loại quan sát tạm",
    "daily_weather",
    "",
    "Nắng nóng",
    "observation_status | equals | final\ntemperature | greater_than | 35",
    "Trạm đang bảo trì => xem xét thủ công",
    "Nhiệt độ cao nhất hôm nay? => tổng hợp",
]


def _rule_file(*rows):
    return _file(RULE_HEADERS, rows)


def test_a_rule_file_creates_a_draft_with_typed_conditions_and_reads_back_unchanged(monkeypatch):
    rules = _rules(monkeypatch)
    upload = _rule_file(RULE_ROW)
    [item] = rule_file.preview_rule_import(upload)
    assert (item.action, item.message, item.key) == ("create", "Tạo rule mới, chờ duyệt.", "Loại quan sát tạm")
    assert len(rules.rule_rows) == 0

    rule_file.apply_rule_import(upload, 11)
    rules.session.commit()

    revision = next(iter(rules.revisions.values()))
    assert (revision.status, revision.revision_number) == ("draft", 1)
    assert revision.conditions == [
        {"field_ref": {"column_dictionary_id": 70}, "operator": "equals", "value_type": "string", "value": "final"},
        {"field_ref": {"column_dictionary_id": 71}, "operator": "greater_than", "value_type": "number", "value": 35},
    ]
    assert revision.exceptions == [{"when": "Trạm đang bảo trì", "outcome": "xem xét thủ công"}]
    assert revision.examples == [{"question": "Nhiệt độ cao nhất hôm nay?", "intent": "tổng hợp"}]
    assert [event.event_type for event in rules.events] == ["created"]

    exported = rule_file.export_rules()
    assert read_table(exported, rule_file.RULE_COLUMNS, ExpertRuleValidationError)[0][1]["conditions"] == RULE_ROW[4]
    [item] = rule_file.preview_rule_import(exported)
    assert item.action == "unchanged"


def test_a_rule_file_edit_of_an_approved_rule_adds_a_draft_and_never_approves_it(monkeypatch):
    rules = _rules(monkeypatch)
    rule_file.apply_rule_import(_rule_file(RULE_ROW), 11)
    created = next(iter(rules.revisions.values()))
    rules.service.approve(created.rule_id, 1, 12, None, False)
    rules.session.commit()

    edited = [*RULE_ROW[:4], 'observation_status | in | ["final", "checked"]', "", RULE_ROW[6]]
    [item] = rule_file.preview_rule_import(_rule_file(edited))
    assert (item.action, item.changes) == ("update", ["conditions", "exceptions"])
    assert item.message.startswith("Tạo bản nháp mới chờ duyệt")
    rule_file.apply_rule_import(_rule_file(edited), 11)
    rules.session.commit()

    revisions = sorted(rules.revisions.values(), key=lambda revision: revision.revision_number)
    assert [(revision.status, revision.is_current) for revision in revisions] == [("approved", False), ("draft", True)]
    assert revisions[1].conditions[0]["value"] == ["final", "checked"] and revisions[1].exceptions == []
    assert [event.event_type for event in rules.events] == ["created", "approved", "updated"]


def test_a_rule_file_that_only_changes_the_group_moves_the_rule_and_keeps_its_approval(monkeypatch):
    rules = _rules(monkeypatch)
    rule_file.apply_rule_import(_rule_file(RULE_ROW), 11)
    revision = next(iter(rules.revisions.values()))
    rules.service.approve(revision.rule_id, 1, 12, None, False)
    rules.session.commit()

    grouped = [RULE_ROW[0], RULE_ROW[1], "Lọc bản ghi", *RULE_ROW[3:]]
    [item] = rule_file.preview_rule_import(_rule_file(grouped))
    assert (item.action, item.changes) == ("update", ["group"])
    assert item.message == "Chỉ chuyển nhóm; trạng thái duyệt giữ nguyên. Tạo nhóm mới «Lọc bản ghi»."
    rule_file.apply_rule_import(_rule_file(grouped), 12)
    rules.session.commit()

    revision = next(iter(rules.revisions.values()))
    assert (revision.status, revision.lifecycle_version) == ("approved", 2)
    assert next(iter(rules.rule_rows.values())).group.name == "Lọc bản ghi"
    assert [event.event_type for event in rules.events][-1] == "moved"


def test_a_rule_file_with_a_failing_row_reports_every_reason_and_saves_nothing(monkeypatch):
    rules = _rules(monkeypatch)
    upload = _rule_file(
        RULE_ROW,
        [RULE_ROW[0].upper(), *RULE_ROW[1:]],
        ["Rule B", "monthly_rain", *RULE_ROW[2:]],
        ["Rule C", *RULE_ROW[1:3], "Bản nháp", *RULE_ROW[4:]],
        ["Rule D", *RULE_ROW[1:4], "humidity | equals | 1", *RULE_ROW[5:]],
        ["Rule E", *RULE_ROW[1:4], "temperature | about | 1", *RULE_ROW[5:]],
        ["Rule F", *RULE_ROW[1:6], "Câu hỏi không có cách hiểu"],
        ["Rule G", *RULE_ROW[1:5], "Khi DROP TABLE x => bỏ qua", RULE_ROW[6]],
        ["Rule H", *RULE_ROW[1:3], "Không có", *RULE_ROW[4:]],
    )
    reasons = [item.message for item in rule_file.preview_rule_import(upload)]
    assert reasons[0] == "Tạo rule mới, chờ duyệt."
    assert reasons[1:] == [
        "Rule trùng tên với dòng 2.",
        "Không có dataset «monthly_rain».",
        "Thuật ngữ phải đã được duyệt và có liên kết tới dataset của rule.",
        "Cột «humidity» không có trong Data Dictionary của dataset «daily_weather».",
        f"Toán tử «about» không hợp lệ; dùng một trong: {', '.join(sorted(rule_file.CONDITION_OPERATORS))}.",
        "Ví dụ «Câu hỏi không có cách hiểu» phải có dạng <câu hỏi> => <cách hiểu>.",
        "Ngoại lệ (khi nào) chứa cú pháp SQL, đường dẫn hoặc thông tin bí mật.",
        "Không có thuật ngữ «Không có».",
    ]
    with pytest.raises(ExpertRuleValidationError, match="File có 8 dòng lỗi"):
        rule_file.apply_rule_import(upload, 11)
    rules.session.rollback()
    assert len(rules.rule_rows) == 0


def test_a_rule_file_cannot_move_a_rule_to_another_dataset(monkeypatch):
    rules = _rules(monkeypatch)
    rule_file.apply_rule_import(_rule_file(RULE_ROW), 11)
    rules.session.commit()
    other = SimpleNamespace(id=8, table_name="daily_rain")
    monkeypatch.setattr(rule_file, "business_datasets_by_name", lambda: {"daily_weather": [rules.dataset], "daily_rain": [other]})
    upload = _rule_file([RULE_ROW[0], "daily_rain", *RULE_ROW[2:]])
    [item] = rule_file.preview_rule_import(upload)
    assert item.action == "error"
    assert item.message == "Rule đã gắn với một dataset khác; không thể chuyển rule sang dataset khác."


# Data Dictionary metadata: the import over in-memory dictionary rows.


class _Repository:
    def __init__(self, rows):
        self.rows = rows

    def get(self, dataset_id):
        return self.rows.get(dataset_id)

    def read(self, dataset_id):
        return self.rows.get(dataset_id)

    def read_by_column_name(self, dataset_id, column_name):
        return self.rows.get((dataset_id, column_name))

    def get_for_dataset_column(self, dataset_id, column_name):
        return self.rows.get((dataset_id, column_name))

    def list_for_dataset(self, dataset_id):
        return [row for key, row in self.rows.items() if isinstance(key, tuple) and key[0] == dataset_id]

    def update(self, record, values):
        for field, value in values.items():
            setattr(record, field, value)
        return record


def _dictionary():
    roles = {"ten_tram": "label", "nhiet_do": "measure", "luong_mua": "measure"}
    dataset = SimpleNamespace(id=7, table_name="dm_tram", columns=[SimpleNamespace(column_name=name) for name in roles])
    dataset_row = SimpleNamespace(id=7, display_name="dm_tram", description=None, contains_pii=False)

    def column(name, role):
        return SimpleNamespace(
            dataset_id=7, column_name=name, display_name=name, description=None, semantic_role=role, aggregations=None,
            synonyms=None, unit=None, business_term=None, contains_pii=False,
        )

    columns = _Repository({(7, name): column(name, role) for name, role in roles.items()})
    seeded = []
    namespace = {
        **TABLE_HELPERS,
        "SemanticLayerError": SemanticLayerError,
        "dataclass": dataclass,
        "json_list": json_list,
        "threading": threading,
        "ROLES": column_semantics.ROLES,
        "AGGREGATIONS": column_semantics.AGGREGATIONS,
        "checked_column_semantics": column_semantics.checked_column_semantics,
        "checked_temporal_kind": checked_temporal_kind,
        "checked_pii_flag": checked_pii_flag,
        "read_dictionary_snapshot": lambda selected_dataset: (
            dataset_row,
            [row for (dataset_id, _), row in columns.rows.items() if dataset_id == selected_dataset.id],
        ),
        "get_dataset": lambda dataset_id: None,
        "business_datasets_by_name": lambda: {"dm_tram": [dataset]},
        "seed_dictionary": seeded.append,
        "column_dictionary_repository": lambda: columns,
        "dataset_dictionary_repository": lambda: _Repository({7: dataset_row}),
    }
    compile_into(
        namespace, *_dictionary_constants(), module_function("validate_dictionary_payload"),
        module_function("_checked_reference"),
        *_module_nodes(DICTIONARY_FILE_PATH),
    )
    return SimpleNamespace(**namespace), dataset_row, columns.rows, seeded


DICTIONARY_HEADERS = ("dataset", "column", "display_name", "description", "semantic_role", "aggregations", "synonyms",
                      "unit", "business_term", "contains_pii")


def test_a_dictionary_file_updates_dataset_and_column_metadata_and_reads_back_unchanged():
    service, dataset_row, columns, seeded = _dictionary()
    upload = _file(
        DICTIONARY_HEADERS,
        [
            ["dm_tram", "", "Trạm quan trắc", "Danh mục trạm.", "", "", "", "", "", "có"],
            ["dm_tram", "ten_tram", "Tên trạm", "", "label", "", "trạm; điểm đo", "", "", "x"],
            ["dm_tram", "nhiet_do", "nhiet_do", "", "measure", "avg; max", "", "°C", "", "false"],
        ],
    )
    preview = service.preview_dictionary_import(upload)
    assert [(item.key, item.action, item.changes) for item in preview] == [
        ("dm_tram", "update", ["display_name", "description", "contains_pii"]),
        ("dm_tram.ten_tram", "update", ["display_name", "synonyms", "contains_pii"]),
        ("dm_tram.nhiet_do", "update", ["unit", "aggregations"]),
    ]
    assert seeded == []  # Preview reads missing metadata without seeding or writing.
    assert dataset_row.display_name == "dm_tram"

    service.apply_dictionary_import(upload)
    assert seeded == [service.business_datasets_by_name()["dm_tram"][0]]

    assert (dataset_row.display_name, dataset_row.description, dataset_row.contains_pii) == (
        "Trạm quan trắc", "Danh mục trạm.", True,
    )
    station = columns[(7, "ten_tram")]
    assert (station.display_name, json_list(station.synonyms), station.contains_pii) == (
        "Tên trạm", ["trạm", "điểm đo"], True,
    )
    assert (json_list(columns[(7, "nhiet_do")].aggregations), columns[(7, "nhiet_do")].unit) == (["AVG", "MAX"], "°C")
    exported = service.export_dictionary()
    assert {item.action for item in service.preview_dictionary_import(exported)} == {"unchanged"}


def test_a_dictionary_file_without_a_column_header_leaves_that_field_alone_and_a_role_change_drops_aggregations():
    service, _, columns, _ = _dictionary()
    columns[(7, "nhiet_do")].aggregations = '["SUM"]'
    upload = _file(("dataset", "column", "semantic_role"), [["dm_tram", "nhiet_do", "dimension"]])
    [item] = service.preview_dictionary_import(upload)
    assert (item.action, item.changes) == ("update", ["semantic_role"])
    service.apply_dictionary_import(upload)
    assert (columns[(7, "nhiet_do")].semantic_role, columns[(7, "nhiet_do")].aggregations) == ("dimension", None)


def test_a_dictionary_file_with_a_failing_row_reports_every_reason_and_changes_nothing():
    service, dataset_row, columns, _ = _dictionary()
    upload = _file(
        DICTIONARY_HEADERS,
        [
            ["dm_tram", "", "Trạm", "", "", "", "", "", "", "false"],
            ["dm_tram", "", "Trạm lần hai", "", "", "", "", "", "", "false"],
            ["dm_mua", "x", "X", "", "", "", "", "", "", "false"],
            ["dm_tram", "do_am", "Độ ẩm", "", "", "", "", "", "", "false"],
            ["dm_tram", "ten_tram", "", "", "", "", "", "", "", "false"],
            ["dm_tram", "nhiet_do", "Nhiệt độ", "", "metric", "", "", "", "", "false"],
            ["dm_tram", "luong_mua", "Lượng mưa", "", "", "MEDIAN", "", "", "", "false"],
        ],
    )
    upload_rows = service.preview_dictionary_import(upload)
    assert [item.message for item in upload_rows] == [
        None,
        "Trùng với dòng 2.",
        "Không có dataset «dm_mua».",
        "Dataset «dm_tram» không có cột «do_am».",
        "Tên hiển thị (display_name) không được để trống.",
        f"Vai trò «metric» không hợp lệ; dùng một trong: {', '.join(column_semantics.ROLES)}.",
        f"Phép tổng hợp không hợp lệ: MEDIAN; dùng: {', '.join(column_semantics.AGGREGATIONS)}.",
    ]
    nested = _file(("dataset", "column", "aggregations", "contains_pii"), [
        ["dm_tram", "ten_tram", "SUM", "false"],
        ["dm_tram", "", "SUM", "maybe"],
        ["dm_tram", "nhiet_do", "", "maybe"],
    ])
    assert [item.message for item in service.preview_dictionary_import(nested)] == [
        "Chỉ khai báo phép tổng hợp cho cột có vai trò measure.",
        "Dòng của dataset (cột «column» trống) chỉ có display_name, description, contains_pii; bỏ trống: aggregations.",
        "contains_pii «maybe» phải là true hoặc false.",
    ]
    with pytest.raises(DataDictionaryValidationError, match="File có 6 dòng lỗi"):
        service.apply_dictionary_import(upload)
    assert dataset_row.display_name == "dm_tram" and columns[(7, "ten_tram")].display_name == "ten_tram"


# The routes: an export, a preview that saves nothing and an import that commits once, each admin only.

FILE_ROUTES = {
    MODULES_PATH / "glossary_management" / "routes" / "route_glossary_file.py": (
        "/glossary/file", "export_glossary_file", "preview_glossary_file", "import_glossary_file",
    ),
    MODULES_PATH / "data_dictionary" / "routes" / "route_dictionary_file.py": (
        "/dictionary/file", "export_dictionary_file", "preview_dictionary_file", "import_dictionary_file",
    ),
    MODULES_PATH / "expert_rule_management" / "routes" / "route_expert_rule_file.py": (
        "/expert-rules/file", "export_expert_rule_file", "preview_expert_rule_file", "import_expert_rule_file",
    ),
}


def _decorator_name(node):
    node = node.func if isinstance(node, ast.Call) else node
    return node.id if isinstance(node, ast.Name) else node.attr


@pytest.mark.parametrize("path", FILE_ROUTES)
def test_the_file_routes_are_admin_only_and_only_the_import_writes_and_commits_once(path):
    base, *names = FILE_ROUTES[path]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    prefix_node = next((node.value for node in tree.body if isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == "prefix" for target in node.targets
    )), None)
    prefix = prefix_node.value if isinstance(prefix_node, ast.Constant) else base
    methods = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    for name, suffix, verb in zip(names, ("", "/preview", "/import"), ("GET", "POST", "POST")):
        method = methods[name]
        decorators = [_decorator_name(item) for item in method.decorator_list]
        expose = method.decorator_list[0]
        route = expose.args[0]
        route_path = route.value if isinstance(route, ast.Constant) else prefix if isinstance(route, ast.Name) else "".join(
            part.value if isinstance(part, ast.Constant) else prefix if isinstance(part.value, ast.Name) else ""
            for part in route.values
        )
        assert route_path == base + suffix
        assert verb in ast.unparse(expose.keywords[0].value)
        assert decorators[-1] == "handle_errors" and "protect" in decorators
        source = ast.unparse(method)
        assert "require_admin()" in source
        assert ("csrf_protected" in decorators) == (verb == "POST")
        if suffix == "/import":
            assert "rollback_on_error" in decorators
        assert source.count("db.session.commit()") == (1 if suffix == "/import" else 0)
