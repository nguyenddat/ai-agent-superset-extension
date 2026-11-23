import { useMemo } from "react"

import { ChatHistory } from "@/components/chat-history"
import { toast } from "@/components/toaster"
import { Skeleton } from "@/components/ui/skeleton"

import { deleteConversation, updateConversation, useConversations, type ConversationChange } from "./api"

// Standalone's history without its "set a user name" empty state: Superset knows the user, so every conversation
// is recorded, and the list is the user's conversations on the chosen database.

type HistoryProps = {
  databaseId: number
  activeId?: string
  onSelect: (id: string) => void
  onNew: () => void
  // The open conversation was deleted, so the screen must not keep adding turns to it.
  onDeleted: (id: string) => void
}

const failed = (error: unknown) => toast.error(error instanceof Error ? error.message : "Không lưu được thay đổi.")

export function ConversationHistory({ databaseId, activeId, onSelect, onNew, onDeleted }: HistoryProps) {
  const { data, error, isLoading } = useConversations(databaseId)
  const chats = useMemo(
    () =>
      (data ?? []).map((item) => ({
        id: item.id,
        title: item.title,
        updatedAt: Date.parse(item.last_message_at ?? item.updated_at),
        pinned: item.is_pinned,
      })),
    [data],
  )

  if (isLoading) {
    return (
      <div className="flex flex-col gap-2 p-1">
        {Array.from({ length: 5 }, (_, index) => (
          <Skeleton key={index} className="h-8 w-full" />
        ))}
      </div>
    )
  }
  if (error) return <p className="p-2 text-sm text-muted-foreground">{error.message}</p>

  const change = (id: string, value: ConversationChange) =>
    updateConversation(databaseId, id, value).catch(failed)

  return (
    <ChatHistory
      className="h-full"
      chats={chats}
      activeId={activeId}
      onSelect={onSelect}
      onNew={onNew}
      onRename={(id, title) => void change(id, { title })}
      onPin={(id, pinned) => void change(id, { is_pinned: pinned })}
      onDelete={(id) => {
        if (id === activeId) onDeleted(id)
        deleteConversation(databaseId, id).catch(failed)
      }}
    />
  )
}
