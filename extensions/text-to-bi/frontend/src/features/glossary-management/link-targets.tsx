import { useMemo } from "react"
import { Columns3Icon, SigmaIcon, Table2Icon, type LucideIcon } from "lucide-react"

import type { ComboboxOption } from "@/components/combobox"
import { pageHref } from "@/lib/navigation"

import { useTableDictionary } from "../data-dictionary/api"
import type { DatasetOption } from "../data-dictionary/dataset-groups"
import { linkKey } from "./labels"
import type { DatasetMetric, GlossaryLink, LinkKind } from "./types"

export const LINK_KINDS: Record<LinkKind, { label: string; icon: LucideIcon }> = {
  table: { label: "Bảng", icon: Table2Icon },
  column: { label: "Cột", icon: Columns3Icon },
  metric: { label: "Metric", icon: SigmaIcon },
  superset_metric: { label: "Metric", icon: SigmaIcon },
}

export type LinkTarget = {
  link: GlossaryLink
  label: string
  detail: string
  href: string
  inactive: boolean
}

export const metricTitle = (metric: Pick<DatasetMetric, "label" | "name">) => metric.label?.trim() || metric.name

const metricKind = (metric: DatasetMetric): LinkKind => (metric.origin === "manual" ? "metric" : "superset_metric")

// The backend accepts a manual metric only while it is approved and active; Superset's own metrics always count.
const metricLive = (metric: DatasetMetric) =>
  metric.origin === "superset" || (metric.is_active && metric.status === "approved")

// A term lives on one dataset, so the targets are that dataset, its columns (from its dictionary, cached with the
// dictionary section) and its metrics. Inactive mirrors the backend's own check of whether a link still resolves.
export function useLinkTargets(dataset: DatasetOption, metrics: DatasetMetric[]) {
  const datasetId = dataset.dataset_id
  const dictionary = useTableDictionary(datasetId)

  return useMemo(() => {
    const tablePath = `${dataset.schema_name ? `${dataset.schema_name}.` : ""}${dataset.table_name}`
    const dictionaryHref = pageHref({ section: "dictionary", dataset: datasetId })
    const metricsHref = pageHref({ section: "metrics", dataset: datasetId })
    const columns = dictionary.data?.columns ?? []
    const columnByName = new Map(columns.map((column) => [column.column_name, column]))
    const metricByKey = new Map(
      metrics.map((metric) => [linkKey({ kind: metricKind(metric), target_key: metric.id }), metric]),
    )

    function resolve(link: GlossaryLink): LinkTarget | null {
      if (link.kind === "table") {
        if (link.target_key !== String(datasetId)) return null
        return { link, label: dataset.display_name, detail: tablePath, href: dictionaryHref, inactive: false }
      }
      if (link.kind === "column") {
        // The key is the column name, so it can still be shown once the column has left the dataset.
        if (!dictionary.data) return null
        const column = columnByName.get(link.target_key)
        return {
          link,
          label: column?.display_name || link.target_key,
          detail: `${dataset.table_name}.${link.target_key}`,
          href: dictionaryHref,
          inactive: !column,
        }
      }
      const metric = metricByKey.get(linkKey(link))
      if (!metric) return null
      return {
        link,
        label: metricTitle(metric),
        detail: `${dataset.table_name} · ${metric.name}`,
        href: metricsHref,
        inactive: !metricLive(metric),
      }
    }

    const icon = (kind: LinkKind) => {
      const Icon = LINK_KINDS[kind].icon
      return <Icon className="size-4 text-muted-foreground" />
    }
    const options: ComboboxOption[] = [
      {
        value: linkKey({ kind: "table", target_key: String(datasetId) }),
        label: dataset.display_name,
        description: tablePath,
        keywords: [dataset.table_name, dataset.schema_name ?? ""],
        group: "Bảng",
        icon: icon("table"),
      },
      ...metrics.filter(metricLive).map((metric) => ({
        value: linkKey({ kind: metricKind(metric), target_key: metric.id }),
        label: metricTitle(metric),
        description: `${dataset.display_name} · ${metric.name}${metric.origin === "superset" ? " · Superset" : ""}`,
        keywords: [metric.name, metric.expression],
        group: "Metric",
        icon: icon("metric"),
      })),
      ...columns.map((column) => ({
        value: linkKey({ kind: "column", target_key: column.column_name }),
        label: column.display_name || column.column_name,
        description: `${dataset.table_name}.${column.column_name} · ${column.data_type}`,
        keywords: [column.column_name, dataset.table_name, dataset.display_name],
        group: `Cột · ${dataset.display_name}`,
        icon: icon("column"),
      })),
    ]

    return {
      resolve,
      options,
      columnsLoading: !dictionary.data && !dictionary.error,
      columnsError: dictionary.error as Error | undefined,
    }
  }, [dataset, datasetId, metrics, dictionary.data, dictionary.error])
}

export type LinkTargets = ReturnType<typeof useLinkTargets>
