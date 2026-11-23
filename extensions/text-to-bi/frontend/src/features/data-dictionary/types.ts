export type SemanticRole = "key" | "measure" | "dimension" | "label" | "time" | "row_kind" | "attribute"
export type TemporalKind = "date" | "timestamp"
export type ColumnAggregation = "SUM" | "AVG" | "MIN" | "MAX" | "COUNT" | "COUNT_DISTINCT"
export type TableKind = "base" | "aggregate"
export type TableLayout = "wide" | "indicator_values" | "indicator_catalog"
export type DatasetKind = "physical" | "virtual"

export type TimeGrainValue = "instant" | "hour" | "day" | "week" | "month" | "quarter" | "year"
export type IndicatorAggregationValue = "SUM" | "AVG" | "MIN" | "MAX" | "COUNT" | "NONE"

// A column is known by its name: Superset may drop and recreate `table_columns` rows when a dataset is synced.
export type ColumnRole = {
  role: string
  qualifier: string | null
  column_name: string
}

export type TimeGrain = {
  row_kind_value: string | null
  label: string | null
  time_grain: TimeGrainValue
}

export type IndicatorAggregation = {
  source_code: string
  aggregation: IndicatorAggregationValue
}

export type ReferencedColumn = {
  dataset_id: number
  schema_name: string | null
  table_name: string
  column_name: string
}

export type ColumnDictionary = {
  column_name: string
  verbose_name: string | null
  data_type: string
  is_dttm: boolean
  is_calculated: boolean
  is_saved: boolean
  display_name: string
  description: string | null
  business_term: string | null
  semantic_role: SemanticRole
  semantic_role_is_default: boolean
  temporal_kind: TemporalKind | null
  unit: string | null
  format: string | null
  is_primary_key: boolean | null
  is_unique: boolean
  referenced_column: ReferencedColumn | null
  contains_pii: boolean
  aggregations: ColumnAggregation[]
  synonyms: string[]
  updated_at: string | null
}

export type TableDictionary = {
  dataset_id: number
  database_id: number | null
  database_name: string
  schema_name: string | null
  table_name: string
  dataset_kind: DatasetKind
  can_edit: boolean
  is_saved: boolean
  display_name: string
  description: string | null
  grain_description: string | null
  table_kind: TableKind | null
  layout: TableLayout
  indicator_catalog: { dataset_id: number; schema_name: string | null; table_name: string; display_name: string } | null
  contains_pii: boolean
  updated_at: string | null
  column_roles: ColumnRole[]
  time_grains: TimeGrain[]
  indicator_aggregations: IndicatorAggregation[]
  columns: ColumnDictionary[]
}

export type DictionaryTableSummary = {
  dataset_id: number
  table_name: string
  dataset_kind: DatasetKind
  is_saved: boolean
  display_name: string
  layout: TableLayout
  column_count: number
  described_column_count: number
}

export type DictionarySummary = {
  table_count: number
  described_table_count: number
  databases: {
    database_id: number | null
    database_name: string
    schemas: { schema_name: string | null; tables: DictionaryTableSummary[] }[]
  }[]
}

type StatsTable = {
  dataset_id: number
  database_name: string
  schema_name: string | null
  table_name: string
  display_name: string
  is_saved: boolean
}

export type DictionaryStats = {
  table_count: number
  described_table_count: number
  column_count: number
  described_column_count: number
  schemas: {
    database_id: number | null
    database_name: string
    schema_name: string | null
    table_count: number
    described_table_count: number
  }[]
  most_columns: (StatsTable & { column_count: number; described_column_count: number })[]
  most_referenced: (StatsTable & { referencing_table_count: number })[]
}

export type TableFields = Pick<
  TableDictionary,
  | "display_name"
  | "description"
  | "grain_description"
  | "table_kind"
  | "contains_pii"
  | "layout"
  | "column_roles"
  | "time_grains"
  | "indicator_aggregations"
> & { indicator_catalog_dataset_id: number | null }

export type ColumnFields = Pick<
  ColumnDictionary,
  | "display_name"
  | "description"
  | "business_term"
  | "temporal_kind"
  | "unit"
  | "format"
  | "is_primary_key"
  | "is_unique"
  | "contains_pii"
  | "aggregations"
  | "synonyms"
  | "referenced_column"
> & { semantic_role: SemanticRole | null }

export type AutofillEvent =
  | { event: "status"; data: { processed: number; total: number; message: string } }
  | { event: "columns"; data: { columns: ColumnDictionary[]; processed: number; total: number } }
  | { event: "table"; data: TableDictionary }
  | { event: "done"; data: { processed: number; total: number; failed_columns: number; table_filled: boolean } }
  | { event: "error"; data: { code: string; message: string } }
