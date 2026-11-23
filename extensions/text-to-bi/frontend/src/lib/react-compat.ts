import * as React from "react"

// React 17 has neither useSyncExternalStore nor useId; the components ported from the standalone app (React 19)
// call these two shims instead, with the same signatures.

// Server rendering never happens here, so the server snapshot is only the first value until the effect runs:
// that keeps the one-frame "not yet hydrated" behaviour some components rely on (e.g. skipping a first animation).
export function useSyncExternalStore<T>(
  subscribe: (onChange: () => void) => () => void,
  getSnapshot: () => T,
  getServerSnapshot?: () => T,
): T {
  const [value, setValue] = React.useState<T>(() => (getServerSnapshot ?? getSnapshot)())
  const getRef = React.useRef(getSnapshot)
  getRef.current = getSnapshot

  React.useEffect(() => {
    const sync = () => setValue(() => getRef.current())
    sync()
    return subscribe(sync)
  }, [subscribe])

  return value
}

let nextId = 0

// A stable id per component instance, shaped like React 18's (":r1:") so callers that strip colons still work.
export function useId(): string {
  const ref = React.useRef<string | null>(null)
  if (ref.current === null) ref.current = `:t${(nextId++).toString(36)}:`
  return ref.current
}

// React 17 does not know the `inert` attribute: `inert={true}` is dropped with a warning, while a string passes
// through. Spread the result instead: <button {...inert(!open)}>.
export function inert(on: boolean): Record<string, string> {
  return on ? { inert: "" } : {}
}
