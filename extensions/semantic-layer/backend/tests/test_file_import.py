import ast
import base64
import sys
import threading
import types
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from catalog_source import MODULES_PATH, compile_into, module_function
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base
from test_expert_rule_service import _lifecycle_session
from test_glossary_service import _sqlite_service
from test_pii_flags import _dictionary_constants

from text_to_bi.superset_semantic_layer.common.exceptions import SemanticLayerError
from text_to_bi.superset_semantic_layer.common.utils import table_file
from text_to_bi.superset_semantic_layer.common.utils.table_file import read_table, write_table
from text_to_bi.superset_semantic_layer.common.utils.type_formatter import json_list
from text_to_bi.superset_semantic_layer.modules.data_dictionary.exceptions import DataDictionaryValidationError
from text_to_bi.superset_semantic_layer.modules.data_dictionary.services import column_semantics
from text_to_bi.superset_semantic_layer.modules.data_dictionary.services.pii import checked_pii_flag
from text_to_bi.superset_semantic_layer.modules.data_dictionary.services.time_semantics import checked_temporal_kind
from text_to_bi.superset_semantic_layer.modules.expert_rules.exceptions import ExpertRuleValidationError
from text_to_bi.superset_semantic_layer.modules.expert_rules.services import expert_rule as rule_service
from text_to_bi.superset_semantic_layer.modules.expert_rules.services import rule_file
from text_to_bi.superset_semantic_layer.modules.glossary.exceptions import GlossaryValidationError
from text_to_bi.superset_semantic_layer.modules.glossary.services import validation

TERM_FILE_PATH = MODULES_PATH / "glossary" / "services" / "term_file.py"
DICTIONARY_FILE_PATH = MODULES_PATH / "data_dictionary" / "services" / "dictionary_file.py"
TABLE_HELPERS = {
    name: getattr(table_file, name)
    for name in (
        "ImportRow", "dataset_named", "flag_text", "join_list", "parse_flag", "read_table", "refusal_message",
        "split_list", "write_table",
    )
}


class FileError(SemanticLayerError):
    status = 400


def _csv(text: str, filename: str = "file.csv") -> dict[str, str]:
    return {"filename": filename, "content": base64.b64encode(text.encode("utf-8")).decode("ascii")}


def _file(headers, rows) -> dict[str, str]:
    return write_table(headers, rows, "csv", "file", FileError)


def _module_nodes(path) -> list[ast.stmt]:
    return [
        node
        for node in ast.parse(path.read_text(encoding="utf-8")).body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Assign))
    ]


# The shared file reader and writer.


def test_a_csv_is_read_with_its_byte_order_mark_any_delimiter_and_headers_in_any_case():
    text = "\ufeffName ; Definition;links\r\nRevenue;\"Recognized\nrevenue.\";dataset:sales\r\n;;\r\nCost;Spent;\r\n"
    rows = read_table(_csv(text), ("name", "definition", "links", "group"), ("name",), FileError)

    assert rows == [
        (2, {"name": "Revenue", "definition": "Recognized\nrevenue.", "links": "dataset:sales"}),
        (4, {"name": "Cost", "definition": "Spent", "links": ""}),
    ]


def test_a_windows_vietnamese_csv_is_read_too():
    # The code page writes "ệ" and "ộ" as "ê" and "ô" followed by a combining dot below.
    windows_text = "name\nNhiệt độ\n".encode("cp1258")
    payload = {"filename": "a.csv", "content": base64.b64encode(windows_text).decode()}
    assert read_table(payload, ("name",), ("name",), FileError) == [(2, {"name": "Nhiệt độ"})]


@pytest.mark.parametrize(
    "payload, message",
    [
        (None, "Chọn một file"),
        ({"filename": "a.csv", "content": "%%%"}, "Không đọc được nội dung file"),
        (_csv("\ufeff"), "File trống"),
        (_csv("name,color\nA,red\n"), "cột không hỗ trợ: color"),
        (_csv("definition\nA\n"), "File thiếu cột: name"),
        (_csv("name,Name\nA,B\n"), "lặp tên"),
        (_csv("name\n\n \n"), "không có dòng dữ liệu"),
        (_csv("name\n" + "A\n" * 1_001), "hơn 1000 dòng"),
        ({"filename": "a.csv", "content": "A" * 1_400_000}, "vượt quá 1 MB"),
    ],
)
def test_a_file_that_cannot_be_imported_is_refused_with_a_vietnamese_reason(payload, message):
    with pytest.raises(FileError, match=message):
        read_table(payload, ("name", "definition"), ("name",), FileError)


def test_a_written_csv_reads_back_the_same_rows_and_opens_in_excel_as_utf8():
    headers = ("name", "conditions")
    exported = write_table(headers, [["Nắng nóng", "a | equals | x\nb | is_null"]], "csv", "rule", FileError)

    assert exported["filename"] == "rule.csv" and exported["media_type"].startswith("text/csv")
    assert base64.b64decode(exported["content"]).startswith(b"\xef\xbb\xbf")
    rows = read_table(exported, headers, headers, FileError)
    assert rows == [(2, {"name": "Nắng nóng", "conditions": "a | equals | x\nb | is_null"})]
    with pytest.raises(FileError, match="csv hoặc xlsx"):
        write_table(headers, [], "pdf", "rule", FileError)


def test_an_xlsx_file_round_trips_when_openpyxl_is_installed():
    pytest.importorskip("openpyxl")
    headers = ("name", "contains_pii")
    exported = write_table(headers, [["Trạm", "true"]], "xlsx", "dictionary", FileError)
    assert exported["filename"] == "dictionary.xlsx"
    assert read_table(exported, headers, headers, FileError) == [(2, {"name": "Trạm", "contains_pii": "true"})]


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


def _glossary():
    service, session = _sqlite_service()
    namespace = service.create_draft.__globals__
    stewards = {7: SimpleNamespace(id=7, username="an"), 8: SimpleNamespace(id=8, username="bao")}
    by_username = {user.username: user for user in stewards.values()}
    namespace.update(
        {
            **TABLE_HELPERS,
            "SemanticLayerError": SemanticLayerError,
            "dataclass": dataclass,
            "normalized_name": validation.normalized_name,
            "business_datasets_by_name": lambda: {"daily_weather": [namespace["get_dataset"](7)]},
            "security_manager": SimpleNamespace(
                get_user_by_id=stewards.get,
                find_user=lambda username: by_username.get(username),
            ),
        }
    )
    compile_into(namespace, *_module_nodes(TERM_FILE_PATH))
    return SimpleNamespace(**namespace), session


def _term_file(*rows):
    return _file(("canonical_name", "definition", "synonyms", "group", "steward", "links"), rows)


def _actions(rows):
    return [(item.action, item.message) for item in rows]


def test_a_term_file_creates_drafts_with_their_group_and_steward_and_reads_back_unchanged():
    service, session = _glossary()
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

    exported = service.export_terms("csv")
    assert {item.action for item in service.preview_term_import(exported)} == {"unchanged"}


def test_a_term_file_edit_of_an_approved_term_adds_a_draft_and_keeps_the_approved_revision_serving():
    service, session = _glossary()
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


def test_a_term_file_that_only_changes_the_group_moves_the_term_without_review():
    service, session = _glossary()
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


def test_a_term_file_with_a_failing_row_reports_every_reason_and_saves_nothing():
    service, session = _glossary()
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
    session, rule_model, revision_model, audit_model = _lifecycle_session(monkeypatch)
    base = declarative_base()

    class GlossaryTerm(base):
        __tablename__ = "glossary_term"
        id = Column(Integer, primary_key=True)
        canonical_name = Column(String, nullable=False)
        normalized_name = Column(String, nullable=False)

    base.metadata.create_all(session.get_bind())
    glossary_models = types.ModuleType("text_to_bi.superset_semantic_layer.modules.glossary.models")
    glossary_models.GlossaryTerm = GlossaryTerm
    monkeypatch.setitem(sys.modules, glossary_models.__name__, glossary_models)
    # The term repository binds its model when imported, so import it again with this table.
    monkeypatch.delitem(sys.modules, f"{glossary_models.__name__[:-7]}.repositories.glossary_term", False)
    session.add_all(
        [
            GlossaryTerm(id=3, canonical_name="Nắng nóng", normalized_name="nắng nóng"),
            GlossaryTerm(id=4, canonical_name="Bản nháp", normalized_name="bản nháp"),
        ]
    )
    session.commit()
    dataset = SimpleNamespace(id=7, table_name="daily_weather")
    columns = [
        SimpleNamespace(id=70, dataset_id=7, column_name="observation_status"),
        SimpleNamespace(id=71, dataset_id=7, column_name="temperature"),
    ]

    def column_resolver(dataset_id):
        def resolve(reference):
            if isinstance(reference, str):
                return [column for column in columns if column.column_name == reference]
            return next((column for column in columns if column.id == reference), None)

        return resolve

    references = rule_file.RuleReferences(
        datasets={"daily_weather": [dataset]},
        dataset=lambda key: dataset if key == 7 else None,
        # Only term 3 is approved and linked to the dataset; term 4 waits for review.
        glossary=lambda key: SimpleNamespace(status="approved", is_current=True, dataset_id=7) if key == 3 else None,
        metric=lambda key: SimpleNamespace(status="approved", is_current=True, dataset_id=7) if key == 9 else None,
        fingerprint=lambda kind, target_id, dataset_id: f"{kind}:{target_id}:{dataset_id}",
        column_resolver=column_resolver,
        term_metrics=lambda payload: {**payload, "metric_ids": [9]},
    )
    return SimpleNamespace(
        session=session, references=references, rule=rule_model, revision=revision_model, audit=audit_model
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
    [item] = rule_file.preview_rule_import(rules.session, upload, rules.references)
    assert (item.action, item.message, item.key) == ("create", "Tạo rule mới, chờ duyệt.", "Loại quan sát tạm")
    assert rules.session.query(rules.rule).count() == 0

    rule_file.apply_rule_import(rules.session, upload, rules.references, 11)
    rules.session.commit()

    revision = rules.session.query(rules.revision).one()
    assert (revision.status, revision.revision_number) == ("draft", 1)
    assert revision.conditions == [
        {"field_ref": {"column_dictionary_id": 70}, "operator": "equals", "value_type": "string", "value": "final"},
        {"field_ref": {"column_dictionary_id": 71}, "operator": "greater_than", "value_type": "number", "value": 35},
    ]
    assert revision.exceptions == [{"when": "Trạm đang bảo trì", "outcome": "xem xét thủ công"}]
    assert revision.examples == [{"question": "Nhiệt độ cao nhất hôm nay?", "intent": "tổng hợp"}]
    assert [event.event_type for event in rules.session.query(rules.audit)] == ["created"]

    exported = rule_file.export_rules(rules.session, rules.references, "csv")
    assert read_table(exported, RULE_HEADERS, RULE_HEADERS, FileError)[0][1]["conditions"] == RULE_ROW[4]
    [item] = rule_file.preview_rule_import(rules.session, exported, rules.references)
    assert item.action == "unchanged"


def test_a_rule_file_edit_of_an_approved_rule_adds_a_draft_and_never_approves_it(monkeypatch):
    rules = _rules(monkeypatch)
    rule_file.apply_rule_import(rules.session, _rule_file(RULE_ROW), rules.references, 11)
    created = rules.session.query(rules.revision).one()
    rule_service.approve_rule(rules.session, created, 1, 12)
    rules.session.commit()

    edited = [*RULE_ROW[:4], 'observation_status | in | ["final", "checked"]', "", RULE_ROW[6]]
    [item] = rule_file.preview_rule_import(rules.session, _rule_file(edited), rules.references)
    assert (item.action, item.changes) == ("update", ["conditions", "exceptions"])
    assert item.message.startswith("Tạo bản nháp mới chờ duyệt")
    rule_file.apply_rule_import(rules.session, _rule_file(edited), rules.references, 11)
    rules.session.commit()

    revisions = rules.session.query(rules.revision).order_by(rules.revision.revision_number).all()
    assert [(revision.status, revision.is_current) for revision in revisions] == [("approved", False), ("draft", True)]
    assert revisions[1].conditions[0]["value"] == ["final", "checked"] and revisions[1].exceptions == []
    events = rules.session.query(rules.audit).order_by(rules.audit.id)
    assert [event.event_type for event in events] == ["created", "approved", "updated"]


def test_a_rule_file_that_only_changes_the_group_moves_the_rule_and_keeps_its_approval(monkeypatch):
    rules = _rules(monkeypatch)
    rule_file.apply_rule_import(rules.session, _rule_file(RULE_ROW), rules.references, 11)
    rule_service.approve_rule(rules.session, rules.session.query(rules.revision).one(), 1, 12)
    rules.session.commit()

    grouped = [RULE_ROW[0], RULE_ROW[1], "Lọc bản ghi", *RULE_ROW[3:]]
    [item] = rule_file.preview_rule_import(rules.session, _rule_file(grouped), rules.references)
    assert (item.action, item.changes) == ("update", ["group"])
    assert item.message == "Chỉ chuyển nhóm; trạng thái duyệt giữ nguyên. Tạo nhóm mới «Lọc bản ghi»."
    rule_file.apply_rule_import(rules.session, _rule_file(grouped), rules.references, 12)
    rules.session.commit()

    revision = rules.session.query(rules.revision).one()
    assert (revision.status, revision.lifecycle_version) == ("approved", 2)
    assert rules.session.query(rules.rule).one().group.name == "Lọc bản ghi"
    assert [event.event_type for event in rules.session.query(rules.audit)][-1] == "moved"


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
    reasons = [item.message for item in rule_file.preview_rule_import(rules.session, upload, rules.references)]
    assert reasons[0] == "Tạo rule mới, chờ duyệt."
    assert reasons[1:] == [
        "Rule trùng tên với dòng 2.",
        "Không có dataset «monthly_rain».",
        "Thuật ngữ phải đã được duyệt và có liên kết tới dataset của rule.",
        "Cột «humidity» không có trong Data Dictionary của dataset «daily_weather».",
        f"Toán tử «about» không hợp lệ; dùng một trong: {', '.join(sorted(rule_service._CONDITION_OPERATORS))}.",
        "Ví dụ «Câu hỏi không có cách hiểu» phải có dạng <câu hỏi> => <cách hiểu>.",
        "Ngoại lệ (khi nào) chứa cú pháp SQL, đường dẫn hoặc thông tin bí mật.",
        "Không có thuật ngữ «Không có».",
    ]
    with pytest.raises(ExpertRuleValidationError, match="File có 8 dòng lỗi"):
        rule_file.apply_rule_import(rules.session, upload, rules.references, 11)
    rules.session.rollback()
    assert rules.session.query(rules.rule).count() == 0


def test_a_rule_file_cannot_move_a_rule_to_another_dataset(monkeypatch):
    rules = _rules(monkeypatch)
    rule_file.apply_rule_import(rules.session, _rule_file(RULE_ROW), rules.references, 11)
    rules.session.commit()
    other = SimpleNamespace(id=8, table_name="daily_rain")
    references = rule_file.RuleReferences(
        **{**rules.references.__dict__, "datasets": {**rules.references.datasets, "daily_rain": [other]}}
    )
    upload = _rule_file([RULE_ROW[0], "daily_rain", *RULE_ROW[2:]])
    [item] = rule_file.preview_rule_import(rules.session, upload, references)
    assert item.action == "error"
    assert item.message == "Rule đã gắn với một dataset khác; không thể chuyển rule sang dataset khác."


# Data Dictionary metadata: the import over in-memory dictionary rows.


class _Repository:
    def __init__(self, rows):
        self.rows = rows

    def get(self, dataset_id):
        return self.rows.get(dataset_id)

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
    dataset_row = SimpleNamespace(display_name="dm_tram", description=None, contains_pii=False)

    def column(name, role):
        return SimpleNamespace(
            column_name=name, display_name=name, description=None, semantic_role=role, aggregations=None,
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
        "get_dataset": lambda dataset_id: None,
        "business_datasets_by_name": lambda: {"dm_tram": [dataset]},
        "seed_dictionary": seeded.append,
        "column_dictionary_repository": lambda: columns,
        "dataset_dictionary_repository": lambda: _Repository({7: dataset_row}),
    }
    compile_into(
        namespace, *_dictionary_constants(), module_function("validate_dictionary_payload"),
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
    assert seeded == [service.business_datasets_by_name()["dm_tram"][0]]
    assert dataset_row.display_name == "dm_tram"

    service.apply_dictionary_import(upload)

    assert (dataset_row.display_name, dataset_row.description, dataset_row.contains_pii) == (
        "Trạm quan trắc", "Danh mục trạm.", True,
    )
    station = columns[(7, "ten_tram")]
    assert (station.display_name, json_list(station.synonyms), station.contains_pii) == (
        "Tên trạm", ["trạm", "điểm đo"], True,
    )
    assert (json_list(columns[(7, "nhiet_do")].aggregations), columns[(7, "nhiet_do")].unit) == (["AVG", "MAX"], "°C")
    exported = service.export_dictionary("csv")
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
    MODULES_PATH / "glossary" / "routes" / "glossary.py": (
        "/glossary/file", "export_glossary_file", "preview_glossary_file", "import_glossary_file",
    ),
    MODULES_PATH / "data_dictionary" / "routes" / "dictionary.py": (
        "/dictionary/file", "export_dictionary_file", "preview_dictionary_file", "import_dictionary_file",
    ),
    MODULES_PATH / "expert_rules" / "routes" / "expert_rules.py": (
        "/expert-rules/file", "export_file", "preview_file", "import_file",
    ),
}


def _decorator_name(node):
    node = node.func if isinstance(node, ast.Call) else node
    return node.id if isinstance(node, ast.Name) else node.attr


@pytest.mark.parametrize("path", FILE_ROUTES)
def test_the_file_routes_are_admin_only_and_only_the_import_writes_and_commits_once(path):
    base, *names = FILE_ROUTES[path]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    methods = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    for name, suffix, verb in zip(names, ("", "/preview", "/import"), ("GET", "POST", "POST")):
        method = methods[name]
        decorators = [_decorator_name(item) for item in method.decorator_list]
        expose = method.decorator_list[0]
        assert expose.args[0].value == base + suffix
        assert verb in ast.unparse(expose.keywords[0].value)
        assert decorators[-1] == "handle_errors" and "protect" in decorators
        source = ast.unparse(method)
        assert "require_admin()" in source
        assert ("csrf_protected" in decorators) == (verb == "POST")
        assert ("rollback_on_error" in decorators) == (suffix == "/import")
        assert source.count("db.session.commit()") == (1 if suffix == "/import" else 0)
