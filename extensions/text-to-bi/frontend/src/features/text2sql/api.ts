import useSWR, { mutate } from "swr"

import { ApiError, EXTENSION_API, apiFetch, csrfToken, errorFrom } from "@/lib/api"
import { readServerSentEvents } from "@/lib/sse"

import type { ChartField, ChartSpec, ChartType, FieldType, PaletteToken } from "./charts/spec"
import type {
  ChatEvent,
  Conversation,
  ConversationDetail,
  ConversationListItem,
  Feedback,
  Rating,
  ResultValue,
} from "./types"

// Standalone's text2sql api.ts against the extension backend (text2sql and conversations routes). Differences:
// - Superset knows the signed-in user, so no call takes a `userId` (standalone's user-id.ts has no counterpart) and
//   every turn is recorded; conversations are scoped by Superset database (`databaseId: number`) instead of
//   connection. Signatures otherwise keep standalone's names and argument order, minus userId:
//     useConversations(databaseId)                      refreshConversations(databaseId)
//     fetchConversation(id)                             updateConversation(databaseId, id, change)
//     deleteConversation(databaseId, id)                saveFeedback(conversationId, turnId, rating)
//     saveChartView(conversationId, turnId, resultId, chart)   deleteChartView(conversationId, turnId, resultId)
// - Requests ride on the Superset session; the streaming chat call fetches Superset's CSRF token like apiFetch.
// - Superset's REST layer wraps bodies ({result}, {conversation}, {feedback}, {view}); the helpers unwrap them.
// - Errors carry `{code, message}` (errorFrom) instead of FastAPI's `{detail}`.
// - The chat is refused unless the user can query every dataset of the database (backend require_query), the
//   database is PostgreSQL and it has at least one dataset; those come back as a 400/403/404 before the stream.

const CHAT = "/text2sql/chat/stream"
const CONVERSATIONS = "/conversations"

// A past turn as the rewrite step sees it: the question and the bot's final reply (its clarification question
// when it asked one back). The backend reads recorded turns instead whenever it knows the user, which in the
// extension is always, so chatHistory is only a fallback the backend ignores.
export type ChatHistoryTurn = {
  question: string
  answer: string | null
}

// conversationId adds the turn to that conversation (a new one is started without it); resumeId continues the
// turn that paused with a clarification question, and `question` is then the user's reply.
export type ChatRequest = {
  databaseId: number
  question: string
  conversationId?: string
  resumeId?: string
  chatHistory?: ChatHistoryTurn[]
}

export async function* streamChat(request: ChatRequest, signal: AbortSignal): AsyncGenerator<ChatEvent> {
  const body = {
    database_id: request.databaseId,
    question: request.question,
    conversation_id: request.conversationId ?? null,
    resume_id: request.resumeId ?? null,
    chat_history: request.chatHistory ?? [],
  }
  let response: Response
  try {
    const token = await csrfToken()
    response = await fetch(`${EXTENSION_API}${CHAT}`, {
      method: "POST",
      credentials: "same-origin",
      headers: { Accept: "text/event-stream", "Content-Type": "application/json", "X-CSRFToken": token },
      body: JSON.stringify(body),
      signal,
    })
  } catch (error) {
    if (signal.aborted || error instanceof ApiError) throw error
    throw new ApiError(0, "Không kết nối được tới Superset.")
  }
  // The backend answers errors with `{code, message}`; anything else (a proxy page) gets a generic sentence.
  if (!response.ok) throw await errorFrom(response, "Không thể gửi câu hỏi.")
  for await (const message of readServerSentEvents(response)) {
    let data: unknown
    try {
      data = JSON.parse(message.data)
    } catch {
      throw new ApiError(0, "Không đọc được dữ liệu server gửi về.")
    }
    yield { event: message.event, data } as ChatEvent
  }
}

const query = (params: Record<string, string | number>) =>
  new URLSearchParams(Object.entries(params).map(([key, value]) => [key, String(value)]))

export const conversationsKey = (databaseId: number) =>
  `${CONVERSATIONS}/?${query({ database_id: databaseId, limit: 200 })}`

// Pass null while no database is selected yet: nothing is fetched.
export function useConversations(databaseId: number | null) {
  return useSWR<ConversationListItem[], ApiError>(
    databaseId === null ? null : conversationsKey(databaseId),
    async (path: string) => (await apiFetch<{ result: ConversationListItem[] }>(path)).result,
  )
}

export const refreshConversations = (databaseId: number) => mutate(conversationsKey(databaseId))

export async function fetchConversation(id: string) {
  const body = await apiFetch<{ conversation: ConversationDetail }>(
    `${CONVERSATIONS}/${id}?${query({ turns_limit: 500 })}`,
  )
  return body.conversation
}

export type ConversationChange = { title?: string; is_pinned?: boolean; is_archived?: boolean }

export async function updateConversation(databaseId: number, id: string, change: ConversationChange) {
  const body = await apiFetch<{ conversation: Conversation }>(`${CONVERSATIONS}/${id}`, {
    method: "PATCH",
    body: JSON.stringify(change),
  })
  await refreshConversations(databaseId)
  return body.conversation
}

export async function deleteConversation(databaseId: number, id: string) {
  await apiFetch<{ message: string }>(`${CONVERSATIONS}/${id}`, { method: "DELETE" })
  await refreshConversations(databaseId)
}

// Resolves to the saved feedback, or undefined once a rating is cleared (null).
export async function saveFeedback(conversationId: string, turnId: string, rating: Rating | null) {
  const path = `${CONVERSATIONS}/${conversationId}/turns/${turnId}/feedback`
  if (rating === null) {
    await apiFetch<{ message: string }>(path, { method: "DELETE" })
    return undefined
  }
  const body = await apiFetch<{ feedback: Feedback }>(path, { method: "PUT", body: JSON.stringify({ rating }) })
  return body.feedback
}

export type CheckedChart = { chart: ChartSpec; warnings: string[] }

// Checks a chart against a result that was not recorded; 422 carries the problems, one per line, in the message.
export function validateChart(chart: ChartSpec, fields: ChartField[], rows: ResultValue[][], rowsComplete: boolean) {
  return apiFetch<CheckedChart & { chart_types: string[] }>("/text2sql/charts/validate", {
    method: "POST",
    body: JSON.stringify({
      chart,
      fields,
      rows: rows.slice(0, 1000),
      rows_complete: rowsComplete && rows.length <= 1000,
    }),
  })
}

const viewPath = (conversationId: string, turnId: string, resultId: string) =>
  `${CONVERSATIONS}/${conversationId}/turns/${turnId}/views/${encodeURIComponent(resultId)}`

// Saves the user's chart for one result of a recorded turn; the backend checks it against the stored rows.
export type SavedView = CheckedChart & { result_id: string; updated_at: string }

export async function saveChartView(conversationId: string, turnId: string, resultId: string, chart: ChartSpec) {
  const body = await apiFetch<{ view: SavedView }>(viewPath(conversationId, turnId, resultId), {
    method: "PUT",
    body: JSON.stringify({ chart }),
  })
  return body.view
}

export async function deleteChartView(conversationId: string, turnId: string, resultId: string) {
  await apiFetch<{ message: string }>(viewPath(conversationId, turnId, resultId), { method: "DELETE" })
}

// GET /text2sql/chart-types: the key charts/catalog.ts (useChartCatalog) reads the server's chart catalog under.
export const chartTypesKey = "/text2sql/chart-types"
