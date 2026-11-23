import { useState } from "react"
import { BanIcon, CheckIcon, CircleCheckIcon, CircleDashedIcon, CircleSlashIcon } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { toast } from "@/components/toaster"
import { ApiError } from "@/lib/api"

import { approveMetric, revokeMetric } from "./api"
import { METRIC_STATES } from "./labels"
import type { Metric } from "./types"

const ICONS = { approved: CircleCheckIcon, draft: CircleDashedIcon, revoked: CircleSlashIcon }

// The backend's review step for a manual metric (the standalone app has none): its state, and for a reviewer the
// one action that moves it on. Revoking asks first, the way glossary terms do.
export function MetricReview({
  metric,
  canReview,
  editable,
}: {
  metric: Metric
  canReview: boolean
  /** Editing an approved metric's content sends it back for review; say so where it can be edited. */
  editable: boolean
}) {
  const [busy, setBusy] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const state = METRIC_STATES[metric.status]
  const Icon = ICONS[metric.status]

  async function run(action: () => Promise<Metric>, done: string) {
    setBusy(true)
    try {
      await action()
      toast.success(done)
      setConfirming(false)
    } catch (caught) {
      toast.error(caught instanceof ApiError ? caught.message : "Không cập nhật được trạng thái metric.")
    } finally {
      setBusy(false)
    }
  }

  const hint =
    metric.status === "approved" && editable
      ? `${state.hint} Sửa nội dung sẽ đưa metric về chờ duyệt.`
      : metric.status === "revoked" && editable
        ? `${state.hint} Sửa nội dung để gửi duyệt lại.`
        : state.hint

  return (
    <Alert>
      <Icon />
      <AlertTitle>{state.label}</AlertTitle>
      <AlertDescription>{confirming ? "Thu hồi? AI sẽ ngừng dùng metric này ngay." : hint}</AlertDescription>
      {canReview && metric.status !== "revoked" ? (
        // Below the text rather than in AlertAction: the revoke confirmation needs two buttons.
        <div className="col-start-2 mt-2 flex flex-wrap gap-2">
          {metric.status === "draft" ? (
            <Button
              size="sm"
              disabled={busy}
              onClick={() => void run(() => approveMetric(metric.dataset_id, metric.id), "Đã duyệt metric")}
            >
              {busy ? <Spinner data-icon="inline-start" /> : <CheckIcon data-icon="inline-start" />}
              Duyệt
            </Button>
          ) : confirming ? (
            <>
              <Button
                size="sm"
                variant="destructive"
                disabled={busy}
                onClick={() => void run(() => revokeMetric(metric.dataset_id, metric.id), "Đã thu hồi metric")}
              >
                {busy ? <Spinner data-icon="inline-start" /> : null}
                Thu hồi
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
                Giữ lại
              </Button>
            </>
          ) : (
            <Button size="sm" variant="outline" onClick={() => setConfirming(true)}>
              <BanIcon data-icon="inline-start" />
              Thu hồi
            </Button>
          )}
        </div>
      ) : null}
    </Alert>
  )
}
