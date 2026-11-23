import type { DictionarySummary, DictionaryTableSummary } from "./types"

export type DatasetOption = DictionaryTableSummary & { database_name: string; schema_name: string | null }
// Shaped as Base UI Combobox groups: an `items` array marks a group.
export type DatasetGroup = { value: string; items: DatasetOption[] }

const schemaLabel = (schema: string | null) => schema ?? "(không có schema)"

// Superset may hold several databases where the standalone app has one connection: one group per database and
// schema, leaving the database name out when there is only one.
export function datasetGroups(summary: DictionarySummary): DatasetGroup[] {
  const single = summary.databases.length === 1
  return summary.databases.flatMap((database) =>
    database.schemas.map((schema) => ({
      value: single ? schemaLabel(schema.schema_name) : `${database.database_name} · ${schemaLabel(schema.schema_name)}`,
      items: schema.tables.map((table) => ({
        ...table,
        database_name: database.database_name,
        schema_name: schema.schema_name,
      })),
    })),
  )
}

export const allDatasets = (summary: DictionarySummary) => datasetGroups(summary).flatMap((group) => group.items)

export const datasetSearchText = (dataset: DatasetOption) =>
  `${dataset.display_name} ${dataset.schema_name ?? ""}.${dataset.table_name} ${dataset.database_name}`
