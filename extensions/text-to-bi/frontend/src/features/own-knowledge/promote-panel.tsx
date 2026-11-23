import { useMemo } from "react"
import { mutate } from "swr"

import { toast } from "@/components/toaster"
import { Skeleton } from "@/components/ui/skeleton"
import { ApiError } from "@/lib/api"
import { navigate, pageHref } from "@/lib/navigation"

import type { DatasetOption } from "../data-dictionary/dataset-groups"
import { approveRule } from "../expert-rule-management/api"
import { RuleEditor } from "../expert-rule-management/rule-editor"
import { useRuleRefs, type DatasetInfo } from "../expert-rule-management/rule-refs"
import type { ExpertRule } from "../expert-rule-management/types"
import { approveTerm, useDatasetMetrics } from "../glossary-management/api"
import { useLinkTargets } from "../glossary-management/link-targets"
import { TermEditor } from "../glossary-management/term-editor"
import type { DatasetMetric, GlossaryTerm } from "../glossary-management/types"
import { approveMetric } from "../metric-management/api"
import type { Metric } from "../metric-management/types"
import { entriesKey, promoteEntry } from "./api"
import type { PromoteRequest } from "./entry-detail"
import { KINDS } from "./labels"
import { MetricPromotionEditor } from "./metric-promotion"
import type { OwnEntry } from "./types"

// The catalog lists are the entry's dataset's: in the extension a term, metric or rule lives on one dataset, and the
// backend creates the promoted record on the entry's dataset.
type PromotePanelProps = {
  entry: OwnEntry
  dataset: DatasetOption
  request: PromoteRequest
  terms: GlossaryTerm[]
  metrics: Metric[]
  rules: ExpertRule[]
  onClose: () => void
  onDone: () => void
}

function PanelSkeleton() {
  return (
    <div className="flex flex-col gap-3 p-5">
      <Skeleton className="h-6 w-48" />
      <Skeleton className="h-40" />
    </div>
  )
}

export function PromotePanel(props: PromotePanelProps) {
  const { entry, request, onDone } = props
  const datasetId = entry.dataset_id
  const title = `Đưa “${entry.name}” vào kho`

  function promote<T>(input: object) {
    return promoteEntry<T>(entry, request.kind, { ...input }, request.note)
  }

  // Approval runs after promotion has landed, so a refused approval leaves a draft rather than undoing the promotion.
  async function finish(name: string, href: string, approve: (() => Promise<unknown>) | null) {
    let approved = false
    if (approve) {
      try {
        await approve()
        approved = true
        // Whether the AI still reads the user's own entry depends on the approval that just landed.
        await mutate(entriesKey)
      } catch (caught) {
        toast.error("Đã đưa vào kho nhưng chưa duyệt được", {
          description: caught instanceof ApiError ? caught.message : "Hãy duyệt ở tab của bản ghi.",
        })
      }
    }
    const tab = KINDS[request.kind].label
    toast.success("Đã đưa vào kho", {
      description: approved
        ? `${name} đã được duyệt, AI dùng ngay cho mọi người.`
        : `${name} đang chờ duyệt ở tab ${tab}.`,
      action: { label: `Mở tab ${tab}`, onClick: () => navigate(href) },
    })
    onDone()
  }

  if (request.kind === "glossary") {
    return (
      <GlossaryPromotion
        {...props}
        title={title}
        create={(input) => promote<GlossaryTerm>(input)}
        onSaved={(term) =>
          finish(
            term.canonical_name,
            pageHref({ section: "glossary", dataset: datasetId, term: term.id }),
            request.approve ? () => approveTerm(datasetId, term.id, term.current.number) : null,
          )
        }
      />
    )
  }
  if (request.kind === "metric") {
    return (
      <MetricPromotionEditor
        dataset={props.dataset}
        metrics={props.metrics}
        onClose={props.onClose}
        onSaved={(metric) =>
          finish(
            metric.label || metric.name,
            pageHref({ section: "metrics", dataset: datasetId }),
            request.approve ? () => approveMetric(datasetId, metric.id) : null,
          )
        }
        promotion={{
          title,
          seed: { label: entry.name, description: entry.definition },
          create: (input) => promote<Metric>(input),
        }}
      />
    )
  }
  return (
    <RulePromotion
      {...props}
      title={title}
      create={(input) => promote<ExpertRule>(input)}
      onSaved={(rule) =>
        finish(
          rule.name,
          pageHref({ section: "rules", dataset: datasetId, rule: rule.id }),
          request.approve ? () => approveRule(datasetId, rule.id, rule.current.number) : null,
        )
      }
    />
  )
}

type PromotionProps<T> = PromotePanelProps & {
  title: string
  create: (input: object) => Promise<T>
  onSaved: (record: T) => void
}

// Links may name the dataset's metrics, which the glossary reads in its own shape.
function GlossaryPromotion(props: PromotionProps<GlossaryTerm>) {
  const metrics = useDatasetMetrics(props.entry.dataset_id)
  if (metrics.error) return <p className="p-5 text-sm text-destructive">{metrics.error.message}</p>
  if (!metrics.data) return <PanelSkeleton />
  return <GlossaryForm {...props} datasetMetrics={metrics.data} />
}

function GlossaryForm({
  entry,
  dataset,
  terms,
  datasetMetrics,
  onClose,
  title,
  create,
  onSaved,
}: PromotionProps<GlossaryTerm> & { datasetMetrics: DatasetMetric[] }) {
  const targets = useLinkTargets(dataset, datasetMetrics)
  return (
    <TermEditor
      datasetId={entry.dataset_id}
      terms={terms}
      term={null}
      initialDomainId={null}
      targets={targets}
      onClose={onClose}
      onSaved={onSaved}
      onReload={onClose}
      promotion={{
        title,
        seed: {
          name: entry.name,
          definition: entry.definition,
          links: [{ kind: "table", target_key: String(entry.dataset_id) }],
        },
        create,
      }}
    />
  )
}

function RulePromotion({ entry, dataset, rules, onClose, title, create, onSaved }: PromotionProps<ExpertRule>) {
  const info = useMemo<DatasetInfo>(
    () => ({ name: dataset.table_name, displayName: dataset.display_name, schemaName: dataset.schema_name }),
    [dataset.table_name, dataset.display_name, dataset.schema_name],
  )
  const { refs, error } = useRuleRefs(entry.dataset_id, info)
  if (error) return <p className="p-5 text-sm text-destructive">{error.message}</p>
  if (!refs) return <PanelSkeleton />
  return (
    <RuleEditor
      datasetId={entry.dataset_id}
      rules={rules}
      refs={refs}
      rule={null}
      onClose={onClose}
      onSaved={onSaved}
      onReload={onClose}
      promotion={{ title, seed: { name: entry.name, description: entry.definition }, create }}
    />
  )
}
