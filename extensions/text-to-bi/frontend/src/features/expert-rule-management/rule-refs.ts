import { useMemo } from "react"

import { useEligibleTerms, useRuleMetrics, useRuleOptions, useRuleTerms } from "./api"
import { metricKey } from "./labels"
import type { OptionColumn, RuleMetric, RuleTerm } from "./types"

// The dataset a rule belongs to; it stands in for standalone's table, so the screens keep their table wording.
export type TableRef = {
  dataset_id: number
  name: string
  displayName: string
  schemaName: string
  columns: OptionColumn[]
  glossary_terms: { id: string; name: string }[]
  metrics: RuleMetric[]
}

export type RuleRefs = {
  table: TableRef
  columnByName: Map<string, OptionColumn>
  termById: Map<string, RuleTerm>
  metricByKey: Map<string, RuleMetric>
}

export type DatasetInfo = { name: string; displayName: string; schemaName: string | null }

// The rule options name every column, eligible term and metric; the glossary and metric lists name links that are
// no longer eligible. The options list every approved term, but the backend only accepts one whose approved revision
// still links to the dataset, which the glossary's discovery list tells.
export function useRuleRefs(datasetId: number, dataset: DatasetInfo) {
  const options = useRuleOptions(datasetId)
  const eligible = useEligibleTerms(datasetId)
  const glossary = useRuleTerms(datasetId)
  const metrics = useRuleMetrics(datasetId)
  const error = options.error ?? eligible.error ?? glossary.error ?? metrics.error

  const refs = useMemo<RuleRefs | null>(() => {
    if (!options.data || !eligible.data || !glossary.data || !metrics.data) return null
    const linked = new Set(eligible.data.filter((term) => term.links.length > 0).map((term) => term.id))
    const table: TableRef = {
      dataset_id: datasetId,
      name: dataset.name,
      displayName: dataset.displayName,
      schemaName: dataset.schemaName ?? "",
      columns: options.data.columns,
      glossary_terms: options.data.glossary_terms.filter((term) => linked.has(term.id)),
      // A manual metric must be approved before a rule can pin it; Superset's own metrics always count as approved.
      metrics: options.data.metrics.filter((metric) => metric.status === "approved"),
    }
    return {
      table,
      columnByName: new Map(table.columns.map((column) => [column.name, column])),
      termById: new Map(glossary.data.map((term) => [term.id, term])),
      metricByKey: new Map(metrics.data.map((metric) => [metricKey(metric), metric])),
    }
  }, [options.data, eligible.data, glossary.data, metrics.data, datasetId, dataset])

  return { refs, error }
}
