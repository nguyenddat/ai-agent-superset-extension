import { useCallback } from "react"
import useSWR from "swr"

import { type ApiError, apiFetch } from "@/lib/api"

// The standalone app has no sign-in, so its reviewer typed a name that this file remembered. Superset knows who is
// signed in and records the reviewer itself; what the screens need instead is a name for the integer user ids that
// entries carry. The admin's role-assignment list names every active user, and this page is admin-only like it.
type UserRow = { user_id: number; username: string; name: string }

const USERS_KEY = "/auth/role-assignments"

// Pass false to skip the request for someone who is not an admin, who would get 403.
export function useUserNames(enabled = true) {
  const { data } = useSWR<Map<number, string>, ApiError>(
    enabled ? USERS_KEY : null,
    async (path: string) => {
      const { users } = await apiFetch<{ users: UserRow[] }>(path)
      return new Map(users.map((user) => [user.user_id, user.name.trim() || user.username]))
    },
    { revalidateOnFocus: false },
  )
  // A user who left (inactive, or not listed yet while loading) still gets a stable label.
  return useCallback((userId: number) => data?.get(userId) ?? `Người dùng #${userId}`, [data])
}

export type UserName = ReturnType<typeof useUserNames>
