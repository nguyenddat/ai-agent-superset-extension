import { useState } from "react"
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog"
import { CircleXIcon, CornerDownRightIcon, HistoryIcon, MessageSquareTextIcon, SquarePenIcon } from "lucide-react"

import { PromptComposer } from "@/components/prompt-composer"
import { toast } from "@/components/toaster"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from "@/components/ui/message-scroller"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import type { Access } from "@/lib/access"
import { cn } from "@/lib/utils"

import { DatabasePicker, NoDatabase, useDatabaseScope } from "../workspace/database-scope"
import { FILL_SCREEN_ALWAYS } from "../workspace/workspace-layout"
import { AssistantTurn, UserTurn } from "./chat-turn"
import { ConversationHistory } from "./conversation-history"
import { useChat } from "./use-chat"

// Standalone's chat screen. Differences: Superset knows the user, so standalone's "ask as" user picker (and its
// "not saved" notice) gives way to the database picker in the same toolbar spot, and every conversation is saved;
// the chat is scoped by Superset database (one chat per database, remounted on a switch) instead of connection;
// a user without the query right sees the composer disabled the way standalone shows a paused connection.

const MAX_LENGTH = 2000

const FRAME = cn("flex min-h-96 gap-4", FILL_SCREEN_ALWAYS)

// The database picker styled as standalone's ghost "sm" user picker button in the composer toolbar.
const PICKER =
  "ml-0 h-7 max-w-48 gap-1 px-2.5 py-0 text-[0.8rem] font-medium text-muted-foreground " +
  "[&_svg:not([class*='size-'])]:size-3.5"

const errorText = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback)

export function ChatWorkspace({ access }: { access: Access }) {
  const { databaseId, isLoading, error } = useDatabaseScope()

  if (error) {
    return (
      <Alert variant="destructive">
        <CircleXIcon />
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    )
  }

  // The user can read no dataset, so there is no database to ask about.
  if (!isLoading && databaseId === null) return <NoDatabase title="Chưa có dữ liệu để hỏi" />

  if (databaseId === null) {
    return (
      <div className={FRAME}>
        <Skeleton className="hidden w-64 shrink-0 rounded-xl lg:block" />
        <div className="flex min-w-0 flex-1 flex-col justify-end">
          <Skeleton className="mx-auto h-28 w-full max-w-4xl rounded-xl" />
        </div>
      </div>
    )
  }

  // A conversation belongs to one database: another database starts a fresh chat.
  return <ChatPanel key={databaseId} databaseId={databaseId} access={access} />
}

function ChatPanel({ databaseId, access }: { databaseId: number; access: Access }) {
  const chat = useChat(databaseId)
  const { turns, status, busy, loading, conversationId, pending } = chat
  const [draft, setDraft] = useState("")
  const [historyOpen, setHistoryOpen] = useState(false)
  const paused = !access.can_query

  const ask = (question: string) => {
    setDraft("")
    chat.send(question)
  }

  // Editing a question that was asked back means asking it anew rather than answering the AI.
  const edit = (question: string) => {
    chat.dismiss()
    setDraft(question)
  }

  const openConversation = (id: string) => {
    setHistoryOpen(false)
    if (id === conversationId) return
    chat.open(id).catch((error) => toast.error(errorText(error, "Không mở được cuộc trò chuyện.")))
  }

  const startNew = () => {
    setHistoryOpen(false)
    setDraft("")
    chat.clear()
  }

  const history = (
    <ConversationHistory
      databaseId={databaseId}
      activeId={conversationId}
      onSelect={openConversation}
      onNew={startNew}
      onDeleted={chat.clear}
    />
  )

  const content = loading ? (
    <div className="flex flex-1 items-center justify-center gap-2 text-sm text-muted-foreground">
      <Spinner />
      Đang mở cuộc trò chuyện
    </div>
  ) : turns.length === 0 ? (
    <Empty className="flex-1">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <MessageSquareTextIcon />
        </EmptyMedia>
        <EmptyTitle>Hỏi dữ liệu bằng tiếng Việt</EmptyTitle>
        <EmptyDescription>
          AI tách câu hỏi thành các câu đơn, dùng metric, bảng và quy tắc đã mô tả để chạy truy vấn chỉ đọc rồi giải
          thích kết quả. Thiếu thông tin thì AI hỏi lại. Thông tin cá nhân được che trước khi gửi cho AI; bạn vẫn
          thấy giá trị thật.
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  ) : (
    <MessageScrollerProvider autoScroll>
      <MessageScroller className="flex-1">
        <MessageScrollerViewport>
          <MessageScrollerContent className="mx-auto w-full max-w-4xl px-1 py-4">
            {turns.flatMap((turn) => [
              <MessageScrollerItem key={`${turn.id}:q`} messageId={`${turn.id}:q`} scrollAnchor>
                <UserTurn turn={turn} />
              </MessageScrollerItem>,
              <MessageScrollerItem key={`${turn.id}:a`} messageId={`${turn.id}:a`}>
                <AssistantTurn
                  turn={turn}
                  busy={busy || paused}
                  onReply={chat.reply}
                  onRetry={chat.retry}
                  onEdit={edit}
                  onRate={(target, rating) =>
                    chat
                      .rate(target, rating)
                      .catch((error) => toast.error(errorText(error, "Không lưu được đánh giá.")))
                  }
                  actions={chat}
                />
              </MessageScrollerItem>,
            ])}
          </MessageScrollerContent>
        </MessageScrollerViewport>
        <MessageScrollerButton />
      </MessageScroller>
    </MessageScrollerProvider>
  )

  return (
    <div className={FRAME}>
      <aside aria-label="Cuộc trò chuyện đã lưu" className="hidden w-64 shrink-0 flex-col border-r pr-3 lg:flex">
        {history}
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        {content}
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-1.5 pt-2">
          {pending && !busy && (
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-1 text-xs text-muted-foreground">
              <CornerDownRightIcon className="size-3.5 shrink-0" />
              <span>Tin nhắn tiếp theo sẽ trả lời câu hỏi lại của AI.</span>
              <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={chat.dismiss}>
                Hỏi câu khác
              </Button>
            </div>
          )}
          <PromptComposer
            value={draft}
            onValueChange={setDraft}
            onSubmit={ask}
            onStop={chat.stop}
            status={status}
            maxLength={MAX_LENGTH}
            autoFocus
            placeholder={pending ? "Trả lời câu hỏi của AI" : "Hỏi về dữ liệu, vd. doanh thu theo vùng năm nay"}
            disabled={paused}
            disabledReason="Bạn chưa được cấp quyền hỏi dữ liệu."
            toolbar={
              <>
                <DatabasePicker section="chat" className={PICKER} />
                <Sheet open={historyOpen} onOpenChange={setHistoryOpen}>
                  <Tooltip>
                    {/* Base UI's own Dialog.Trigger: the Sheet wrapper is a plain function component, which drops
                        the ref the tooltip anchors to under React 17. */}
                    <TooltipTrigger
                      render={
                        <DialogPrimitive.Trigger
                          data-slot="sheet-trigger"
                          render={
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              className="text-muted-foreground lg:hidden"
                              aria-label="Lịch sử trò chuyện"
                            />
                          }
                        />
                      }
                    >
                      <HistoryIcon />
                    </TooltipTrigger>
                    <TooltipContent>Lịch sử trò chuyện</TooltipContent>
                  </Tooltip>
                  <SheetContent side="left" className="w-80 gap-0">
                    <SheetHeader>
                      <SheetTitle>Lịch sử trò chuyện</SheetTitle>
                      <SheetDescription className="sr-only">
                        Mở lại hoặc quản lý các cuộc trò chuyện đã lưu.
                      </SheetDescription>
                    </SheetHeader>
                    <div className="min-h-0 flex-1 px-4 pb-4">{history}</div>
                  </SheetContent>
                </Sheet>
                {turns.length > 0 && (
                  <Tooltip>
                    <TooltipTrigger
                      render={
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          className="text-muted-foreground"
                          aria-label="Cuộc trò chuyện mới"
                          onClick={startNew}
                        />
                      }
                    >
                      <SquarePenIcon />
                    </TooltipTrigger>
                    <TooltipContent>Cuộc trò chuyện mới</TooltipContent>
                  </Tooltip>
                )}
              </>
            }
          />
          <p className="text-center text-xs text-muted-foreground">
            AI có thể hiểu sai câu hỏi. Kiểm tra SQL và các quy tắc đã áp dụng trước khi dùng số liệu.
          </p>
        </div>
      </div>
    </div>
  )
}
