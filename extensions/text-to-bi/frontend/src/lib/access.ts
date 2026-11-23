import { apiFetch } from "./api"

// What the signed-in user may do in the extension, read once when the page loads and passed down to each section.
export type Access = {
  is_admin: boolean
  can_view: boolean
  can_edit: boolean
  can_query: boolean
  can_review: boolean
}

export const fetchAccess = () => apiFetch<Access>("/auth/me")
