import { useState } from "react"
import {
  ArchiveRestoreIcon,
  BanIcon,
  BookTextIcon,
  CheckIcon,
  ChevronDownIcon,
  CircleXIcon,
  PencilIcon,
  RefreshCwIcon,
  SigmaIcon,
  Trash2Icon,
  TriangleAlertIcon,
  XIcon,
} from "lucide-react"

import { DiffReview, type ChangeDecision, type DiffChange } from "@/components/diff-review"
import { toast } from "@/components/toaster"
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import type { Access } from "@/lib/access"
import { ApiError } from "@/lib/api"
import { Link, pageHref } from "@/lib/navigation"
import { cn } from "@/lib/utils"

import {
  approveRule,
  approveRuleContent,
  deleteRule,
  refreshRules,
  revokeRule,
  saveRuleDraft,
  useRuleRevisions,
} from "./api"
import { DomainBadges } from "@/features/business-model/domains"
import { dateFormat } from "@/lib/format"
import {
  contentOf,
  describeCondition,
  metricRefKey,
  metricTitle,
  ruleState,
  sameIds,
  sameValue,
  servingIsStale,
} from "./labels"
import type { RuleRefs } from "./rule-refs"
import { RuleStatus } from "./rule-status"
import type { ExpertRule, RevisionStatus, RuleContent, RuleRevision } from "./types"

type RuleDetailProps = {
  datasetId: number
  rule: ExpertRule
  refs: RuleRefs
  access: Access
  onClose: () => void
  onEdit: () => void
  onDeleted: () => void
}

type Busy = "approve" | "revoke" | "repin" | "delete"
type Confirm = "revoke" | "delete"
type ChangeId = keyof RuleContent

const CHANGE_LABELS: Record<ChangeId, string> = {
  description: "Mô tả",
  conditions: "Điều kiện",
  exceptions: "Ngoại lệ",
  examples: "Câu hỏi ví dụ",
  glossary_term_ids: "Thuật ngữ liên quan",
  metric_refs: "Metric",
}

const REVISION_STATUS: Record<RevisionStatus, string> = {
  draft: "Bản nháp",
  approved: "Đã duyệt",
  revoked: "Thu hồi",
}

// The approval check fails with this message when a pinned term or metric moved on since the draft was saved.
const STALE_PINS = "Liên kết hoặc điều kiện đã thay đổi"

// Shown on a control the user's role cannot use; the backend refuses the same action.
const NEEDS_EDIT = "Cần quyền sửa tri thức."
const NEEDS_REVIEW = "Cần quyền duyệt tri thức."

export function RuleDetail({ datasetId, rule, refs, access, onClose, onEdit, onDeleted }: RuleDetailProps) {
  const state = ruleState(rule)
  const { current, serving } = rule
  const table = refs.table
  const [busy, setBusy] = useState<Busy | null>(null)
  const [confirm, setConfirm] = useState<Confirm | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  // Decisions belong to one draft; a newer revision starts the review over.
  const [review, setReview] = useState<{ revision: number; decisions: Record<string, ChangeDecision> }>({
    revision: current.number,
    decisions: {},
  })
  const decisions = review.revision === current.number ? review.decisions : {}

  const columnName = (name: string) => (refs.columnByName.has(name) ? name : `${name} (đã xóa)`)
  const termName = (id: string) => refs.termById.get(id)?.canonical_name ?? "thuật ngữ đã xóa"
  const metricName = (key: string) => {
    const metric = refs.metricByKey.get(key)
    return metric ? metricTitle(metric) : "metric đã xóa"
  }
  const text: Record<ChangeId, (revision: RuleRevision) => string> = {
    description: (revision) => revision.description ?? "",
    conditions: (revision) =>
      revision.conditions
        .map((condition) => describeCondition(condition, columnName(condition.column_name)))
        .join("; "),
    exceptions: (revision) => revision.exceptions.map((item) => `Khi ${item.when} → ${item.outcome}`).join("; "),
    examples: (revision) => revision.examples.map((item) => `“${item.question}” → ${item.intent}`).join("; "),
    glossary_term_ids: (revision) => revision.glossary_term_ids.map(termName).join(", "),
    metric_refs: (revision) => revision.metric_refs.map((ref) => metricName(metricRefKey(ref))).join(", "),
  }
  const same: Record<ChangeId, (a: RuleRevision, b: RuleRevision) => boolean> = {
    description: (a, b) => a.description === b.description,
    conditions: (a, b) => sameValue(a.conditions, b.conditions),
    exceptions: (a, b) => sameValue(a.exceptions, b.exceptions),
    examples: (a, b) => sameValue(a.examples, b.examples),
    glossary_term_ids: (a, b) => sameIds(a.glossary_term_ids, b.glossary_term_ids),
    metric_refs: (a, b) => sameIds(a.metric_refs.map(metricRefKey), b.metric_refs.map(metricRefKey)),
  }

  const changes: DiffChange[] =
    state === "changed" && serving
      ? (Object.keys(CHANGE_LABELS) as ChangeId[])
          .filter((id) => !same[id](current, serving))
          .map((id) => ({ id, label: CHANGE_LABELS[id], before: text[id](serving), after: text[id](current) }))
      : []
  const rejected = changes
    .filter((change) => decisions[change.id] === "rejected")
    .map((change) => change.id as ChangeId)
  const keepsNothing = changes.length > 0 && rejected.length === changes.length
  const pinsMoved = state === "stale" || (error?.status === 409 && error.message.startsWith(STALE_PINS))
  // Keeping only part of a draft saves that part first, so it needs the right to edit as well as to review.
  const approveBlocked = !access.can_review ? NEEDS_REVIEW : rejected.length && !access.can_edit ? NEEDS_EDIT : null
  // Deleting a rule the AI may still be applying takes a reviewer, as revoking it would.
  const deleteBlocked = !access.can_edit ? NEEDS_EDIT : serving && !access.can_review ? NEEDS_REVIEW : null

  async function run(kind: Busy, action: () => Promise<unknown>, success: string) {
    setBusy(kind)
    setError(null)
    try {
      await action()
      toast.success(success, { description: rule.name })
      setConfirm(null)
      return true
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError(0, "Không thực hiện được thao tác."))
      return false
    } finally {
      setBusy(null)
    }
  }

  function approve() {
    if (!rejected.length || !serving) {
      return run("approve", () => approveRule(datasetId, rule.id, current.number), "Đã duyệt quy tắc")
    }
    const content = contentOf(current)
    for (const id of rejected) Object.assign(content, { [id]: serving[id] })
    return run(
      "approve",
      () => approveRuleContent(datasetId, rule, content),
      keepsNothing ? "Đã bỏ bản nháp, giữ bản đang dùng" : `Đã duyệt, bỏ ${rejected.length} thay đổi`,
    )
  }

  // Saving the same content again pins the terms' and metrics' current versions in a new draft.
  const resave = (kind: Busy, success: string) =>
    run(
      kind,
      () =>
        saveRuleDraft(datasetId, rule.id, {
          ...contentOf(current),
          business_domain_ids: rule.business_domains.map((domain) => domain.id),
          expected_revision: current.number,
        }),
      success,
    )

  const approveLabel = keepsNothing
    ? "Bỏ bản nháp"
    : rejected.length
      ? `Duyệt, bỏ ${rejected.length} thay đổi`
      : "Duyệt"

  return (
    <section aria-label={`Quy tắc ${rule.name}`} className="flex size-full min-h-0 flex-col bg-background">
      <header className="flex items-start justify-between gap-3 border-b px-5 py-4">
        <div className="flex min-w-0 flex-col gap-1.5">
          <h2 className="truncate text-lg font-semibold tracking-tight">{rule.name}</h2>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <RuleStatus rule={rule} explained />
            <span className="truncate text-sm text-muted-foreground">{table.displayName}</span>
            <DomainBadges domains={rule.business_domains} />
          </div>
        </div>
        <Button variant="ghost" size="icon-sm" aria-label="Đóng" onClick={onClose}>
          <XIcon />
        </Button>
      </header>

      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-6 px-5 py-5">
          {pinsMoved ? (
            <Alert variant="destructive">
              <TriangleAlertIcon />
              <AlertTitle>
                {state === "stale" ? "AI đang tạm ngừng áp dụng quy tắc" : "Thuật ngữ hoặc metric liên kết đã đổi"}
              </AlertTitle>
              <AlertDescription>
                Thuật ngữ hoặc metric liên kết đã có phiên bản mới từ lúc lưu. Làm mới liên kết để tạo bản nháp dùng
                phiên bản mới, rồi duyệt lại. Nếu một liên kết không còn hợp lệ, hãy sửa quy tắc.
              </AlertDescription>
              {access.can_edit ? (
                <AlertAction>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy !== null}
                    onClick={() => void resave("repin", "Đã làm mới liên kết thành bản nháp")}
                  >
                    {busy === "repin" ? (
                      <Spinner data-icon="inline-start" />
                    ) : (
                      <RefreshCwIcon data-icon="inline-start" />
                    )}
                    Làm mới liên kết
                  </Button>
                </AlertAction>
              ) : null}
            </Alert>
          ) : state === "changed" && servingIsStale(rule) ? (
            <Alert>
              <TriangleAlertIcon />
              <AlertDescription>
                Bản đang dùng #{serving!.number} không còn được áp dụng vì liên kết đã đổi. Duyệt bản nháp để AI áp dụng
                lại.
              </AlertDescription>
            </Alert>
          ) : null}

          {state === "changed" ? (
            changes.length ? (
              <DiffReview
                key={current.number}
                title={`So với bản đang dùng #${serving!.number}`}
                changes={changes}
                decisions={decisions}
                onDecisionsChange={(next) => setReview({ revision: current.number, decisions: next })}
              />
            ) : (
              <Alert>
                <RefreshCwIcon />
                <AlertDescription>
                  Nội dung giống bản đang dùng; bản nháp chỉ ghim phiên bản mới của thuật ngữ và metric liên kết.
                </AlertDescription>
              </Alert>
            )
          ) : null}

          {current.description ? (
            <RuleSection title="Mô tả">
              <p className="text-sm leading-relaxed whitespace-pre-wrap">{current.description}</p>
            </RuleSection>
          ) : null}

          <RuleSection title="Điều kiện">
            <ul className="flex flex-col divide-y overflow-hidden rounded-lg border">
              {current.conditions.map((condition, index) => (
                <li key={index} className="px-3 py-2 text-sm">
                  <span className="font-mono text-xs">{columnName(condition.column_name)}</span>{" "}
                  {describeCondition(condition, "").trim()}
                </li>
              ))}
            </ul>
          </RuleSection>

          {current.exceptions.length ? (
            <RuleSection title="Ngoại lệ">
              <ul className="flex flex-col gap-2">
                {current.exceptions.map((item, index) => (
                  <li key={index} className="rounded-lg border px-3 py-2 text-sm">
                    <span className="text-muted-foreground">Khi</span> {item.when}
                    <br />
                    <span className="text-muted-foreground">Thì</span> {item.outcome}
                  </li>
                ))}
              </ul>
            </RuleSection>
          ) : null}

          {current.examples.length ? (
            <RuleSection title="Câu hỏi ví dụ">
              <ul className="flex flex-col gap-2">
                {current.examples.map((item, index) => (
                  <li key={index} className="flex flex-col gap-0.5 rounded-lg border px-3 py-2 text-sm">
                    <span>“{item.question}”</span>
                    <span className="text-muted-foreground">{item.intent}</span>
                  </li>
                ))}
              </ul>
            </RuleSection>
          ) : null}

          <RuleSection title="Thuật ngữ liên quan">
            <div className="flex flex-wrap gap-1.5">
              {current.glossary_term_ids.map((id) => {
                const term = refs.termById.get(id)
                const live = !!term && term.current.status !== "revoked" && !!term.serving
                return (
                  <Badge
                    key={id}
                    variant={live ? "secondary" : "destructive"}
                    render={
                      <Link
                        href={pageHref({ section: "glossary", dataset: datasetId, term: id })}
                        title={live ? undefined : "AI không còn dùng thuật ngữ này"}
                      />
                    }
                  >
                    <BookTextIcon data-icon="inline-start" />
                    {termName(id)}
                  </Badge>
                )
              })}
            </div>
          </RuleSection>

          {current.metric_refs.length ? (
            <RuleSection title="Metric">
              <div className="flex flex-wrap gap-1.5">
                {current.metric_refs.map((ref) => {
                  const key = metricRefKey(ref)
                  const metric = refs.metricByKey.get(key)
                  // The backend resolves a manual metric only while it is active and approved.
                  const live = !!metric && metric.is_active && metric.status === "approved"
                  return (
                    <Badge
                      key={key}
                      variant={live ? "secondary" : "destructive"}
                      render={<Link href={pageHref({ section: "metrics", dataset: datasetId })} />}
                    >
                      <SigmaIcon data-icon="inline-start" />
                      {metricName(key)}
                    </Badge>
                  )
                })}
              </div>
            </RuleSection>
          ) : null}

          <Separator />

          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Bảng</dt>
            <dd className="truncate font-mono text-xs leading-5">
              {`${table.schemaName ? `${table.schemaName}.` : ""}${table.name}`}
            </dd>
            <dt className="text-muted-foreground">Bản hiện tại</dt>
            <dd>
              #{current.number} · {dateFormat.format(new Date(current.created_at))}
            </dd>
            <dt className="text-muted-foreground">AI đang dùng</dt>
            <dd>
              {serving ? `Bản #${serving.number}${rule.is_discoverable ? "" : " (tạm ngừng)"}` : "Không có bản nào"}
            </dd>
          </dl>

          <RevisionHistory ruleId={rule.id} revision={current.number} />

          {error && !pinsMoved ? (
            <Alert variant="destructive">
              <CircleXIcon />
              {error.status === 409 ? <AlertTitle>Không thực hiện được</AlertTitle> : null}
              <AlertDescription>{error.message}</AlertDescription>
              {error.status === 409 ? (
                <AlertAction>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={async () => {
                      await refreshRules(datasetId)
                      setError(null)
                    }}
                  >
                    Tải lại
                  </Button>
                </AlertAction>
              ) : null}
            </Alert>
          ) : null}
        </div>
      </ScrollArea>

      <footer className="flex flex-wrap items-center gap-2 border-t px-5 py-3">
        {confirm ? (
          <div className="flex w-full flex-wrap items-center gap-2">
            <span className="min-w-0 flex-1 text-sm">
              {confirm === "delete"
                ? "Xóa quy tắc cùng mọi phiên bản?"
                : state === "changed"
                  ? "Thu hồi? AI ngừng áp dụng ngay và bản nháp chưa duyệt bị bỏ."
                  : "Thu hồi? AI sẽ ngừng áp dụng quy tắc này ngay."}
            </span>
            <Button
              variant="destructive"
              size="sm"
              disabled={busy !== null}
              onClick={() =>
                confirm === "delete"
                  ? void run("delete", () => deleteRule(datasetId, rule.id), "Đã xóa quy tắc").then(
                      (done) => done && onDeleted(),
                    )
                  : void run("revoke", () => revokeRule(datasetId, rule.id, current.number), "Đã thu hồi quy tắc")
              }
            >
              {busy === confirm ? <Spinner data-icon="inline-start" /> : null}
              {confirm === "delete" ? "Xóa" : "Thu hồi"}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setConfirm(null)}>
              Giữ lại
            </Button>
          </div>
        ) : (
          <>
            {access.can_edit ? (
              <Button
                variant="ghost"
                size="sm"
                className="text-destructive"
                disabled={!!deleteBlocked}
                title={deleteBlocked ?? undefined}
                onClick={() => setConfirm("delete")}
              >
                <Trash2Icon data-icon="inline-start" />
                Xóa
              </Button>
            ) : null}
            <div className="ml-auto flex flex-wrap justify-end gap-2">
              {serving && access.can_review ? (
                <Button variant="outline" onClick={() => setConfirm("revoke")}>
                  <BanIcon data-icon="inline-start" />
                  Thu hồi
                </Button>
              ) : null}
              {state === "revoked" && access.can_edit ? (
                <Button
                  variant="outline"
                  disabled={busy !== null}
                  onClick={() => void resave("repin", "Đã khôi phục thành bản nháp")}
                >
                  {busy === "repin" ? (
                    <Spinner data-icon="inline-start" />
                  ) : (
                    <ArchiveRestoreIcon data-icon="inline-start" />
                  )}
                  Khôi phục
                </Button>
              ) : null}
              {access.can_edit ? (
                <Button variant={state === "active" || state === "revoked" ? "default" : "outline"} onClick={onEdit}>
                  <PencilIcon data-icon="inline-start" />
                  Sửa
                </Button>
              ) : null}
              {(state === "draft" || state === "changed") && access.can_review ? (
                <Button
                  variant={keepsNothing ? "outline" : "default"}
                  disabled={busy !== null || !!approveBlocked}
                  title={approveBlocked ?? undefined}
                  onClick={() => void approve()}
                >
                  {busy === "approve" ? <Spinner data-icon="inline-start" /> : <CheckIcon data-icon="inline-start" />}
                  {approveLabel}
                </Button>
              ) : null}
            </div>
          </>
        )}
      </footer>
    </section>
  )
}

function RuleSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <h3 className="text-sm font-medium">{title}</h3>
      {children}
    </div>
  )
}

function RevisionHistory({ ruleId, revision }: { ruleId: string; revision: number }) {
  const [open, setOpen] = useState(false)
  const { data, error } = useRuleRevisions(open ? ruleId : null, revision)

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger render={<Button variant="ghost" size="sm" className="-ml-2" />}>
        <ChevronDownIcon data-icon="inline-start" className={cn("transition-transform", !open && "-rotate-90")} />
        Lịch sử {revision} phiên bản
      </CollapsibleTrigger>
      <CollapsibleContent>
        {error ? (
          <p className="pt-2 text-sm text-destructive">{error.message}</p>
        ) : !data ? (
          <Skeleton className="mt-2 h-24" />
        ) : (
          <ol className="mt-2 flex flex-col divide-y rounded-lg border text-sm">
            {data.map((item) => (
              <li key={item.number} className="flex items-center gap-3 px-3 py-2">
                <span className="w-8 font-medium tabular-nums">#{item.number}</span>
                <Badge variant={item.status === "approved" ? "secondary" : "outline"}>
                  {REVISION_STATUS[item.status]}
                </Badge>
                <span className="ml-auto text-muted-foreground">{dateFormat.format(new Date(item.created_at))}</span>
              </li>
            ))}
          </ol>
        )}
      </CollapsibleContent>
    </Collapsible>
  )
}
