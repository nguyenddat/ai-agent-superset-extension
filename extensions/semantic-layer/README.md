# Superset Semantic Layer extension

This extension adds two menus to Superset's top navigation bar for administrators. Both open the same page,
`/semantic-layer/?module=<module>`, rendered below the navbar with Superset's SPA template. A user with the
"Semantic Layer Viewer" role sees only Metrics, Business Glossary and Expert Rules, read-only (see Roles below):

| Menu | Module | `module=` |
| --- | --- | --- |
| Mô hình dữ liệu | Data Dictionary: dataset and column metadata | `dictionary` |
| Mô hình dữ liệu | Semantic Model: business domains and data lineage | `semantic` |
| Quản trị nghiệp vụ | Metrics: business definitions, review and trial runs | `metrics` |
| Quản trị nghiệp vụ | Business Glossary: governed business terms | `glossary` |
| Quản trị nghiệp vụ | Expert Rules: governed business rules | `rules` |
| Quản trị nghiệp vụ | Phân quyền: assign the Semantic Layer roles to users | `access` |

### Roles

The extension creates two Superset roles the first time an administrator opens it (with its tables, under the same
migration lock), backed by FAB permissions on the view menu `Text to BI Semantic Layer`:

| Role | Permissions | Reaches |
| --- | --- | --- |
| Semantic Layer Viewer | `can_view`; `can_read` on the Semantic Layer and Expert Rule APIs | The page's read-only routes |
| Semantic Layer Query | `can_query`; `can_read` on both APIs; `can_read`, `can_write` on the AI Agent API | Consumer routes, metric runs, AI Agent chat |

`Admin` holds both and stays the only role that edits or approves. Superset's datasource permissions and row level
security still apply: lists leave out datasets the user cannot read, and per-dataset reads answer 403. The view menu
is declared admin-only when the extension loads, so `superset init` never hands the two permissions to Alpha or
Gamma; creating the roles also removes them from those built-in roles. A user still needs a base role such as Gamma
for Superset's own pages. "Phân quyền" lists active users and ticks each role on or off (`GET /role-assignments`,
`PUT /role-assignments/<user_id>` with `{"roles": [...]}`); a user's other roles are kept.

Metrics, glossary terms and expert rules move from draft to approved to revoked, and every step is logged with
its actor and reason. By default an administrator may approve their own work; set
`TEXT_TO_BI_REQUIRE_SECOND_REVIEWER = True` in `superset_config.py` to require a second administrator.

The three build on each other: metric → glossary term → expert rule. A term may link only approved metrics, and
it becomes outdated when a linked metric is revoked or its formula changes. A rule needs at least one approved term
and takes its metrics from the terms it names, so a revoked metric or term also leaves the rule outdated.

### Groups of terms and rules

Administrators gather glossary terms with the same meaning into term groups (`text_to_bi_glossary_term_group`) and
similar expert rules into rule groups (`text_to_bi_expert_rule_group`). The Glossary and Expert Rules lists show
each group as a collapsible section, with the ungrouped members last under "Chưa phân nhóm".

- A group has a name, unique without regard to case or spacing (a duplicate answers 409), and an optional
  description. Creating, renaming or deleting a group needs no review.
- The group belongs to the term or rule itself (`group_id` on `text_to_bi_glossary_term` and
  `text_to_bi_expert_rule`), not to a revision. Moving a member takes effect at once, creates no revision, leaves
  the content hash and the expert rule lifecycle version as they were, and keeps an approved term or rule serving,
  so a move never makes it outdated or invalidates a pending approval. Each move is logged in the member's audit
  trail as a `moved` event whose reason reads `old group → new group`.
- Deleting a group that still has members moves them to "ungrouped" (each with a `moved` event) and keeps their
  approval; nothing is refused.
- A term or rule is put in a group from its detail panel, from the editor (a `group_id` in the create or draft
  payload, applied outside the draft), or with `PUT .../glossary/<term_id>/group` and
  `PUT .../expert-rules/<rule_id>/group` with `{"group_id": <id or null>}`. Groups are created with
  `POST .../glossary/groups` and `POST .../expert-rules/groups`, and changed or deleted with `PUT` and `DELETE` on
  `.../groups/<group_id>`. The admin lists (`GET .../glossary`, `GET .../expert-rules`) return `groups` and each
  member's `group`.

### Bulk create and update from a file

"Nhập / xuất file" on the Glossary, Expert Rules and Data Dictionary pages downloads the current rows as CSV or XLSX
and takes the edited file back. `GET .../glossary/file?format=csv|xlsx` (and `.../expert-rules/file`,
`.../dictionary/file`) exports; `POST .../file/preview` with `{"filename", "content": <base64>}` validates every row
as the editors do and saves nothing; `POST .../file/import` re-runs that check and applies the whole file in one
transaction, or nothing when any row fails. Files are limited to 1 MB and 1000 rows (400 otherwise). Lists in a cell
are separated by `;`; a column left out of the file keeps the stored value.

| Entity | Columns (required in bold) | Natural key |
| --- | --- | --- |
| Glossary term | **canonical_name**, **definition**, synonyms, group, steward (username), **links** (`dataset:<table>`, `column:<table>.<column>`, `metric:<table>.<metric>`) | `canonical_name` without regard to case or spacing |
| Expert rule | **name**, **dataset**, group, **glossary_terms**, **conditions** (`<column> \| <operator> \| <value>` per line), exceptions (`when => outcome`), **examples** (`question => intent`) | `name` without regard to case or spacing |
| Data dictionary | **dataset**, **column** (blank for the dataset row), display_name, description, semantic_role, aggregations, synonyms, unit, business_term, contains_pii | dataset table name + column name |

A new term or rule is created as a draft; a content change adds a draft revision through the editor services, so
nothing is approved by an import and each change is audited as a single edit would be. A group-only change is a
`moved` event, and a missing group is created. Dictionary metadata has no review step and is saved directly.

## Semantic Model: base and aggregate tables

The business view of the Semantic Model groups both the base tables (`dm_*`, `tb_*`) and the aggregate tables built
from them (the dashboard `dim_*` / `fact_*` tables and the virtual datasets the AI Agent proposes) by business domain.
The Data Dictionary's classification decides the role: an aggregate tile has a dashed border and an `Agg` badge, and
tables not classified yet stay out of the view with a note. The domain dialog lists both kinds.

## Consumer API

Approved content reaches any consumer, such as a Text to BI agent, through read-only endpoints. Each returns only
approved, current content on datasets the caller may access in Superset, and never returns SQL expressions.

| Endpoint | Returns |
| --- | --- |
| `GET /extensions/text-to-bi/superset-semantic-layer/semantic-layer/semantic-catalog` | Approved metrics per dataset, groupable and filterable dimensions, approved relationships, row and filter limits |
| `GET /extensions/text-to-bi/superset-semantic-layer/semantic-layer/glossary/discovery` | Approved terms with definitions, synonyms and their fresh links to datasets, columns and metrics |
| `GET /extensions/text-to-bi/superset-semantic-layer/expert-rules/expert-rules/discover` | Approved rules: conditions, exceptions, example questions, and the dataset, metrics and terms they link to |
| `POST /extensions/text-to-bi/superset-semantic-layer/semantic-layer/dataset/<id>/metrics/<id>/semantic-query/execute` | Runs an approved metric through Superset's chart data API, with RLS |

Each catalog metric carries:

```json
{
  "metric_id": 41,
  "metric_name": "nhiet_do_cao_nhat",
  "verbose_name": "Nhiệt độ cao nhất",
  "description": "Mô tả trong Superset",
  "d3format": ",.1f",
  "business_definition": "Nhiệt độ cao nhất ghi nhận trong phạm vi lọc.",
  "unit": "°C",
  "steward_name": "Bao Reviewer",
  "glossary_terms": [{ "term_id": 3, "name": "Nắng nóng", "synonyms": ["nóng nhất"] }],
  "query_defaults": {
    "grain": "day", "row_kind_column": "loai_quan_sat", "row_kind_value": "DU_BAO_NGAY", "native_grain": "day",
    "time_column": "thoi_diem_quan_sat", "time_window": "last_7_day", "time_anchor": "latest_data",
    "default_filters": [{ "column": "thanh_pho_key", "operator": "IN", "value": [1, 2] }]
  }
}
```

`business_definition`, `unit` and `steward_name` are `null` until an administrator writes the metric's business
definition. A consumer joins expert rules to metrics through the rule's `metric_ids`.

Each catalog dataset and each of its dimensions also carries `contains_pii`, `true` when the Data Dictionary marks it
as holding personal data (PII). A column does not inherit its dataset's mark; a consumer checks both.

`query_defaults` (`null` when unset) is how the metric is read unless a query says otherwise: its grain, row kind,
time column and default time window, counted from now or from the latest data, and its default filters. They are part
of the reviewed metric: editing them in the Metrics tab leaves an approved metric outdated until it is proposed and
approved again. The execute endpoint applies them: a caller filter on a column replaces the default on that column,
`"time_grain"` groups the time column by another grain (never finer than the rows), and `"apply_defaults": false`
skips them all. The response's `applied_defaults` lists what was applied. See
[`docs/specs/metric-grain-moc-thoi-gian-bo-loc.md`](../../docs/specs/metric-grain-moc-thoi-gian-bo-loc.md).

Each discovered term and rule also carries its `group` (`{"id": 2, "name": "Nhiệt độ"}`, or `null` when ungrouped),
so a consumer can read terms of one meaning, or similar rules, together.

## Structure

```text
semantic-layer/
├── extension.json
├── backend/
│   ├── pyproject.toml
│   └── src/text_to_bi/superset_semantic_layer/
│       ├── entrypoint.py               # registers SemanticLayerAPI, SemanticLayerView and ExpertRuleAPI
│       ├── migrations.py               # creates and upgrades every module's tables, once per process
│       ├── core/config.py              # environment settings: OpenRouter key, base URL and model
│       ├── core/security.py            # admin role, dataset permission, CSRF, second reviewer rule
│       ├── core/database.py            # handle_errors and rollback_on_error: errors to responses, rollback
│       ├── core/exceptions.py          # errors of the shared checks (admin, access, CSRF, request body)
│       ├── common/base_model.py        # BaseModel / AuditedModel: Superset's declarative base, table names from class
│       ├── common/base_repo.py         # BaseRepository: get, list, add, update, delete
│       ├── common/exceptions/          # abstract app errors carrying a status and a default message
│       ├── common/utils/type_formatter.py  # ISO dates and moments, JSON texts, SSE events
│       ├── modules/<module>/           # one business area each: data_dictionary, business_model, glossary,
│       │   │                           # expert_rules, semantic_query, agent_ladder, superset; each holds:
│       │   ├── models/                 # its tables in Superset's metadata database
│       │   ├── repositories/           # one repository per model: every query on those tables
│       │   ├── dependencies.py         # repository factories bound to the request's session
│       │   ├── exceptions.py           # its errors, derived from common/exceptions
│       │   ├── services/               # business rules and the helpers other modules call
│       │   └── routes/                 # route mixins (ExpertRuleAPI for expert_rules), one per business area
│       ├── modules/superset/           # Superset's own datasets, databases and users: lookups, no tables of its own
│       ├── modules/data_dictionary/autofill/  # the AI AutoFill agent, its chat model and prompts
│       └── modules/catalog/routes/     # semantic_layer.py: SemanticLayerAPI assembled from the module
│                                       # mixins; view.py: the Semantic Layer page
└── frontend/
    ├── src/integration/installSemanticLayer.tsx
    ├── src/features/semantic-layer/
    ├── src/index.tsx
    ├── package.json
    ├── tsconfig.json
    └── webpack.config.js
```

The backend access endpoint answers `is_admin`, `can_view` and `can_query` before the
frontend adds the navigation bar items. A user without the view permission receives a
forbidden response and does not see the entry point. Datasets are fetched using
Superset's database and dataset APIs, which continue to enforce Superset access.

This first increment shows the Superset dataset-level semantic metadata. It does
not yet read a MetricFlow project or infer metric-to-metric dependencies from
SQL expressions.

The Data Dictionary edits dataset metadata (display name, description, grain,
and the column used to create records) alongside per-column metadata. Both are
stored in the extension's metadata tables and saved together from the panel.
Columns are paginated in the Data Dictionary. The AI AutoFill action streams
and saves unfilled dataset metadata plus column display names, units, and
business terms in batches. It leaves populated fields untouched. Further manual
edits still require an explicit save. Dataset classification (`base` or
`aggregate`) is selected manually and is not generated by AutoFill.

The backend owns `text_to_bi_dataset_dictionary` and
`text_to_bi_column_dictionary` tables. A dataset dictionary row uses the matching
Superset dataset ID as its `id` (`id -> tables.id`). Column dictionary rows point
to the dataset dictionary through `dataset_id -> text_to_bi_dataset_dictionary.id`,
and `referenced_column` points to another column dictionary row. Audit timestamps
follow Superset's nullable audit mixin. The tables are created idempotently the
first time an administrator opens the extension, after Superset's core schema is
available. Existing column dictionary installations are upgraded from `table_id`
to `dataset_id` in place, with a dataset dictionary row backfilled for each
existing dataset reference.

### Personal data (PII)

A dataset dictionary row and a column dictionary row each carry `contains_pii` (boolean, not null, default false),
which marks a table or column that holds personal data such as names, phone numbers or e-mail addresses. An
administrator ticks "Chứa dữ liệu nhạy cảm (PII)" in the Data Dictionary's "Thông tin chung" tab for the dataset, and
the "PII" checkbox in a column's row or details; a marked column shows a "PII" badge. The marks are saved with the
rest of the dictionary: `GET`/`PUT /dataset/<id>/dictionary` read and write `contains_pii` on the dataset and on each
column, and a value that is not `true` or `false` is refused with 400. Rows from before the column existed are not
marked.

### Column transformations and the lineage

An administrator declares how a column is computed from columns of other tables, as a metric is computed from its
input columns: in the Data Dictionary, a column's details hold a "Biến đổi" section where the input columns are picked
from a searchable list grouped by table and the expression is written as free text (SQL or pseudo code, such as
`AVG(tb_gia_tri_quan_sat.gia_tri) theo ngày`). Nothing is inferred: no SQL, view, function or AI is read, and the
expression is shown as written, never parsed. The declaration is saved with "Lưu thay đổi": `PUT
/dataset/<id>/dictionary` takes `transformation` on a column as `{"expression": "...", "sources": [{"dataset_id": 13,
"column_name": "gia_tri"}]}` or `null` to remove it, and `GET` returns it the same way. At least one input column is
needed, each must exist in Superset, and a column cannot be its own input; a broken declaration is refused with 400.

It is stored in `text_to_bi_column_transformation` (one row per described column dictionary row, holding the
expression) and `text_to_bi_column_transformation_source` (its input column dictionary rows, in order); deleting a
column dictionary row deletes its transformation and its use as an input.

The Semantic Model's lineage draws two kinds of flow, each with its own style and a switch in the lineage tools:

- **Tham chiếu (PK/FK)**: the reference edges inferred from the FK declarations, as before (`flow` between levels,
  dashed `relation` within one), plus edges drawn by hand.
- **Biến đổi dữ liệu**: a thicker teal arrow (`transform`) from each source table to each table whose columns it feeds.
  Hovering or selecting the edge shows `target column ← expression`, and the edge panel lists every target column with
  its expression as code and all its input columns.

A transformation edge is hidden or recoloured like any inferred edge, and its override keeps its key when layers move.
The switches are remembered in the browser and do not move the cards.

### Metric formulas and their input columns

Both are read from a metric's SQL expression with sqlglot (28.10.1, the version Superset 6.1 ships), so any form
Superset accepts is covered: `DISTINCT`, `CASE … ELSE … END` (searched or `CASE x WHEN …`), `FILTER (WHERE …)`,
`COALESCE`, `NULLIF`, casts, arithmetic and ratios of aggregates, nested string and date functions, window functions,
and quoted or table-qualified columns. Superset SQL metrics cannot reference other metrics, so there is nothing to
follow there.

- **Input columns** (`business_model/services/metric_columns.py`, the `columns` of each metric in the business model)
  are the dataset columns the expression names. A column in a `CASE`/`IF` condition, the subject of `CASE x WHEN`, a
  `FILTER (WHERE …)` clause or a window's `PARTITION BY`/`ORDER BY` is a `filter`; any other is a `measure`. A
  templated expression is read again without its Jinja tags (each `{{ … }}` taken as NULL), so the columns of every
  branch count; one that still cannot be parsed gives `null`, and the lineage falls back to the whole dataset.
- **Pseudo code** (`semantic_query/services/formula_reading.py`, `pseudo_code` in `/metric-contracts` and in the
  business model's metrics) writes the expression with the Data Dictionary's column labels in brackets, aggregates and
  logic in Vietnamese words, and any other function as written in SQL. A ratio puts its divisor on a line of its own:

  ```text
  100.0 × ĐẾM(NẾU [Loại quan sát] = “DU_BAO_NGAY” VÀ [Tổng lượng mưa (mm)] > 0 THÌ 1)
  ÷ NULLIF(ĐẾM(NẾU [Loại quan sát] = “DU_BAO_NGAY” THÌ 1), 0)
  ```

  `SUM`, `AVG`, `COUNT`, `MAX`, `MIN` read `TỔNG`, `TRUNG_BÌNH`, `ĐẾM`, `LỚN_NHẤT`, `NHỎ_NHẤT`; `DISTINCT` reads
  `KHÁC NHAU`; `CASE` reads `NẾU … THÌ …, CÒN LẠI …`; `FILTER (WHERE c)` reads `CHỈ KHI c`; `OVER (PARTITION BY …
  ORDER BY … DESC)` reads `TRÊN (CHIA THEO … XẾP THEO … GIẢM DẦN)`; a cast reads `ĐỔI_KIỂU(x, kiểu)`; `AND`, `OR`,
  `NOT`, `IS NULL`, `IS NOT NULL`, `IN`, `BETWEEN`, `LIKE` read `VÀ`, `HOẶC`, `KHÔNG`, `TRỐNG`, `CÓ GIÁ TRỊ`,
  `THUỘC`, `TỪ … ĐẾN …`, `GIỐNG`. The Metrics tab shows the pseudo code under "Công thức" with a "Xem SQL" toggle
  for the raw expression, and a lineage metric shows it on hover; an expression that cannot be parsed shows its SQL.

## Build

Install frontend dependencies in `frontend/`, then bundle the extension from
this directory with `superset-extensions bundle`. The generated bundle is
`superset-semantic-layer-0.1.0.supx`.
