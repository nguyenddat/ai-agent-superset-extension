# Business model

Module `business_model` (`extensions/text-to-bi/backend/src/text_to_bi/superset_text_to_bi/modules/business_model/`)
groups Superset datasets into business domains and data layers, per Superset database. Metrics, glossary terms and
expert rules reuse the same domains. Endpoints are listed in [Business Model API](text-to-bi-business-model-api.md).

## Data

All tables live in the `text_to_bi` schema. Datasets and databases are referenced by their Superset IDs; the module
keeps no copy of them.

| Model | Table | Content |
| --- | --- | --- |
| `DataLayer` | `data_layers` | Unique name, description, color, `level`, `sort_order` |
| `DatasetLayer` | `dataset_layers` | One layer per dataset (`tables.id`); deleting a layer sets `layer_id` to null |
| `BusinessDomain` | `business_domains` | Unique name, description, color |
| `business_domain_tables` | `business_domain_tables` | Domain membership, keyed by `table_dictionaries.id` |
| `BusinessCanvas` | `business_canvases` | Free-form JSON layout, one row per Superset database |

Domain membership points at the data dictionary's `TableDictionary` rows, so adding a dataset that has no dictionary
row yet creates one with the table name as display name. Deleting a Superset dataset or database cascades to its
layer assignment, dictionary row (and so its memberships) and canvas.

`ensure_business_model_tables()` first runs `ensure_data_dictionary_tables()`, then creates the five tables with
`checkfirst` under advisory lock `74_116_301` (shared with the top-level migration, `data_dictionary` and `data_lineage`), then re-runs
`ensure_expert_rule_tables()` so the domain association tables owned by other modules exist once `business_domains`
does.

## Rules

- Names are trimmed and must be 1 to 255 characters; layer names and domain names are each unique (409 on conflict).
  Colors must be `#RRGGBB`.
- Creating, editing, reordering and deleting layers and domains, and saving the canvas, need the Superset `Admin`
  role. A domain write also needs the edit right (`can_edit` plus Superset dataset access) on every dataset it lists.
- `dataset_ids` replaces the whole membership; a dataset may appear only once.
- Assigning a layer to a dataset needs the edit right on that dataset, not the Admin role.
- Reordering takes every layer exactly once, grouped by level; the group index becomes `level` and the position in the
  group becomes `sort_order`.
- Reads need the `can_view` permission. `GET /domains/` returns only memberships among datasets the caller can access
  in Superset; `GET /databases/<id>` returns only those datasets.
- `GET /databases/<id>` also embeds the lineage graph from `DataLineageService.graph`, the same payload as
  `GET /data-lineage/graph`. Lineage data stays owned by `data_lineage`.

## UI

Navbar menu **Mô hình dữ liệu**, section **Mô hình** (`/text-to-bi/?section=model&database=<id>`), in
`frontend/src/features/business-model/`. Anyone with `can_view` sees it; only admins edit.

- A database picker chooses the Superset database. The sidebar lists domains and tables; clicking one focuses it on
  the canvas.
- The canvas draws each domain as a region and each table as a circle placed in the regions it belongs to (a table in
  two domains sits in their overlap). Lineage edges between tables can be shown or hidden. A table's layer appears as
  a colored dot. Double-clicking a table opens it in **Từ điển**.
- An admin drags a table from the sidebar or the canvas into a region, or into an overlap to join several domains.
  The canvas updates at once, each changed domain is written with `PUT /domains/<id>` (keeping its members on other
  databases), and a toast confirms the move with a **Hoàn tác** action that writes the previous membership back. A
  failed write shows an error toast and reloads the model.
- A dialog creates, edits or deletes a domain and picks its tables.
- The **Tổng quan** section shows the card "Bảng đã phân miền nghiệp vụ": how many of the database's tables belong to
  a domain, broken down by domain.

Layers, layer assignment and the business canvas layout have no editing screen yet: they are managed through the API,
and the UI only reads layers.
