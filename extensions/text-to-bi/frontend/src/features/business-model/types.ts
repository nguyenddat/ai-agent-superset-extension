import type { TableKind } from "../data-dictionary/types"

// The contract of the extension's business-model API (modules/business_model): the standalone app's types,
// rewritten for Superset, where a model covers one database and its tables are Superset datasets (integer ids).

export type DataLayer = {
  id: string
  name: string
  description: string | null
  color: string | null
  level: number
  sort_order: number
}

export type LayerInput = {
  name: string
  description: string | null
  color: string | null
  level?: number
  sort_order?: number
}

export type BusinessDomain = {
  id: string
  name: string
  description: string | null
  color: string | null
  dataset_ids: number[]
}

export type DomainInput = {
  name: string
  description: string | null
  color: string | null
  dataset_ids: number[]
}

// A dataset of the model's database the user may read; standalone's ModelTable.
export type ModelDataset = {
  dataset_id: number
  schema: string | null
  table_name: string
  // The dictionary's display name, else the table name.
  display_name: string
  table_kind: TableKind | null
  layer_id: string | null
  // Whether the dataset has a saved dictionary (standalone's is_saved).
  is_classified: boolean
}

export type ModelTable = ModelDataset

// ---- Lineage, embedded in the model and also served by GET /data-lineage/graph?database_id= ----

export type LineageEdgeKind = "flow" | "relation" | "transform"
export type DependencyRole = "value" | "group" | "join" | "filter"
export type TransformationOrigin = "manual" | "sql_job" | "view_sql"

// A column of the source referencing a column of the target, read from the data dictionary.
export type RelationColumn = { source: string; target: string }

export type ColumnDependency = {
  source_dataset_id: number
  source_column_name: string
  target_column_name: string | null
  role: DependencyRole
}

type EdgeBase = {
  source: number
  target: number
  label: string | null
  // An override colour set on the canvas; null draws the edge in its kind's colour.
  color: string | null
}

// Inferred from dictionary column references.
export type RelationEdge = EdgeBase & { kind: "relation"; origin: "dictionary"; columns: RelationColumn[] }

// Drawn by hand on the canvas; never carries columns.
export type ManualEdge = EdgeBase & { kind: LineageEdgeKind; origin: "manual"; columns: never[] }

// One edge per source dataset of a saved transformation; its label is the transformation's name.
export type TransformationEdge = EdgeBase & {
  kind: "transform"
  origin: TransformationOrigin
  columns: ColumnDependency[]
  transformation_id: string
}

export type LineageEdge = RelationEdge | ManualEdge | TransformationEdge

// A manual edge and a manual transformation share origin "manual"; only a transformation edge has an id.
export const isTransformationEdge = (edge: LineageEdge): edge is TransformationEdge => "transformation_id" in edge

export type LineageDataset = { id: number; name: string; schema: string | null; description: string | null }

export type EdgeStyle = "orthogonal" | "straight" | "curved"
export type Point = [number, number]

// The lineage canvas as PUT /data-lineage/canvas validates it: keys use nodeKey and edgeKey below.
export type LineageCanvasLayout = {
  nodes: Record<string, Point>
  edges: Record<string, { style: EdgeStyle; coords: number[]; waypoints: Point[]; label: Point | null; ports: Point }>
}

export const nodeKey = (datasetId: number) => `table-${datasetId}`
export const edgeKey = (edge: Pick<LineageEdge, "kind" | "source" | "target">) =>
  `${edge.kind}-${edge.source}-${edge.target}`

export type LineageGraph = {
  database_id: number
  datasets: LineageDataset[]
  edges: LineageEdge[]
  canvas: LineageCanvasLayout | null
}

export type BusinessModel = {
  database_id: number
  layers: DataLayer[]
  domains: BusinessDomain[]
  datasets: ModelDataset[]
  // Free-form layout saved by PUT /business-model/databases/<id>/canvas; {} when never saved.
  business_canvas: Record<string, unknown>
  lineage: LineageGraph
}
