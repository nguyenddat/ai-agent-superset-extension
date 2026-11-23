import type {
  ColumnDependency,
  DependencyRole,
  LineageEdgeKind,
  TransformationOrigin,
} from "../business-model/types"

// The graph itself (GET /data-lineage/graph) is the business model's LineageGraph; these are the rest of the
// data-lineage API's contract (modules/data_lineage), where tables are Superset datasets and columns go by name.
export type { ColumnDependency, DependencyRole, TransformationOrigin }

export type TransformationInput = {
  target_dataset_id: number
  name: string
  description: string | null
  sql_text: string | null
  origin: TransformationOrigin
  source_dataset_ids: number[]
  dependencies: ColumnDependency[]
}

export type Transformation = TransformationInput & {
  id: string
  created_at: string
  updated_at: string
}

export type LineagePreview = {
  target_dataset_id: number
  source_dataset_ids: number[]
  dependencies: ColumnDependency[]
  warnings: string[]
  complete: boolean
}

// What PUT/DELETE /data-lineage/edges name an edge by.
export type EdgeRef = { source: number; target: number; kind: LineageEdgeKind }

// A column has no id of its own in Superset (a sync may recreate its row), so the canvas keys it by dataset and name.
export const columnId = (datasetId: number, columnName: string) => `${datasetId}:${columnName}`

// Standalone's column link, keyed by columnId, so tracing and drawing work the same on both sides.
export type ColumnLink = {
  source_column_id: string
  target_column_id: string | null
  role: DependencyRole
}

// One edge the lineage page draws: a transformation's source → target, or an edge drawn by hand on the canvas.
export type GraphEdge = {
  transformation_id: string | null
  source_table_id: number
  target_table_id: number
  kind: "transform" | "flow"
  origin: TransformationOrigin | "manual_edge"
  dependencies: ColumnLink[]
}

export type LineageColumn = {
  column_id: string
  table_id: number
  name: string
  data_type: string
  is_key: boolean
  display_name: string
}
