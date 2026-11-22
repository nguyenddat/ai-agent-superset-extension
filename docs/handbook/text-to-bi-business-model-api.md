# Business model API

The API is registered at `/api/v1/business-model/`. Read operations require Semantic Layer viewer access. Writes require administrator access and an `X-CSRFToken` header, except dataset layer assignment, which requires dataset edit access and the caller?s dataset ACL. Domain memberships are filtered by the caller?s Superset dataset access. All dataset IDs are Superset dataset IDs.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/layers/` | List layers ordered by level, sort order, and name. |
| POST | `/layers/` | Create layer with `name`, optional `description`, `color`, `level`, and `sort_order`. |
| PUT | `/layers/order` | Set layer order with `levels`, a list of lists of layer UUIDs. Every layer must appear exactly once. |
| PUT | `/layers/{layer_id}` | Update layer fields. |
| DELETE | `/layers/{layer_id}` | Delete a layer; dataset assignments become unassigned. |
| GET | `/domains/` | List domains with accessible dataset memberships. |
| POST | `/domains/` | Create domain with `name`, optional `description`, `color`, and `dataset_ids`. |
| PUT | `/domains/{domain_id}` | Update domain fields and replace its full `dataset_ids` membership. |
| DELETE | `/domains/{domain_id}` | Delete a domain and its memberships. |
| PUT | `/datasets/{dataset_id}/layer` | Assign `layer_id`, or `null` to remove the assignment. |
| GET | `/databases/{database_id}` | Read the combined business model for a Superset database. |
| PUT | `/databases/{database_id}/canvas` | Save the business canvas JSON `layout`. |

The combined read returns layers, domains, visible datasets, business canvas, and lineage. Lineage canvas, edge, and transformation data are read through the existing `data_lineage` service and remain owned by that module. Responses use the standard extension JSON envelope.
