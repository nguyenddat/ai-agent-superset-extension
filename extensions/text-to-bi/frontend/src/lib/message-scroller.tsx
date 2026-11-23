import * as React from "react"

import { inert, useSyncExternalStore } from "./react-compat"

// A port of @shadcn/react/message-scroller 0.3.1 (the unstyled primitive behind standalone's
// components/ui/message-scroller.tsx), which needs React 19. Same behaviour, same API:
// - follows the bottom while content streams in (autoScroll) until the user scrolls up;
// - a new item marked scrollAnchor (a new question) is scrolled to the top of the viewport, keeping a peek of the
//   previous item, and a bottom spacer keeps it there while its answer is still short;
// - prepending older items keeps what the user was reading in place;
// - data-scrollable="start end" and the Button's data-active tell whether there is more to scroll to.
// React 17 changes: ref props become forwardRef, useSyncExternalStore comes from the compat shim, the Button's
// `render` is merged by hand (cloneElement) and `inert` is spread as a string attribute.

export type MessageScrollerDefaultScrollPosition = "start" | "end" | "last-anchor"
export type MessageScrollerButtonDirection = "start" | "end"
export type MessageScrollerScrollAlign = "start" | "center" | "end" | "nearest"
export type MessageScrollerScrollOptions = {
  align?: MessageScrollerScrollAlign
  behavior?: ScrollBehavior
  scrollMargin?: number
}
export type MessageScrollerScrollable = { start: boolean; end: boolean }
export type MessageScrollerVisibilityState = { currentAnchorId: string | null; visibleMessageIds: string[] }

const DEFAULT_EDGE_THRESHOLD = 8
const DEFAULT_PREVIOUS_PEEK = 64
const DEFAULT_SCROLL_MARGIN = 0
const EPSILON = 0.5
const AUTOSCROLL_MS = 180
const SCROLL_KEYS = new Set(["ArrowDown", "ArrowUp", "End", "Home", "PageDown", "PageUp", " "])
const NOT_SCROLLABLE: MessageScrollerScrollable = { start: false, end: false }
const NO_VISIBILITY: MessageScrollerVisibilityState = { currentAnchorId: null, visibleMessageIds: [] }

type Mode = "following-bottom" | "free-scrolling" | "anchored-to-message" | "settling-jump"
type Layout = { content: HTMLElement | null; spacer: HTMLElement | null; viewport: HTMLElement | null }

// ---------------------------------------------------------------- geometry

function itemsOf(content: HTMLElement, spacer: HTMLElement | null): HTMLElement[] {
  return Array.from(content.children).filter(
    (child): child is HTMLElement => child instanceof HTMLElement && child !== spacer,
  )
}

const isAnchor = (element: HTMLElement | undefined) => element?.dataset.scrollAnchor === "true"

function firstAnchorFrom(items: HTMLElement[], from: number) {
  for (let index = from; index < items.length; index++) if (isAnchor(items[index])) return items[index]!
  return null
}

function firstUnhandledAnchor(items: HTMLElement[], handled: WeakSet<HTMLElement>) {
  for (const item of items) if (isAnchor(item) && !handled.has(item)) return item
  return null
}

function severalAnchorsFrom(items: HTMLElement[], from: number) {
  let count = 0
  for (let index = from; index < items.length; index++) if (isAnchor(items[index]) && ++count > 1) return true
  return false
}

function lastAnchor(items: HTMLElement[]) {
  for (let index = items.length - 1; index >= 0; index--) if (isAnchor(items[index])) return items[index]!
  return null
}

function firstVisibleItem({
  content,
  spacer,
  viewport,
}: {
  content: HTMLElement
  spacer: HTMLElement | null
  viewport: HTMLElement
}) {
  const box = viewport.getBoundingClientRect()
  for (const item of itemsOf(content, spacer)) {
    if (!item.dataset.messageId) continue
    const rect = item.getBoundingClientRect()
    if (rect.bottom > box.top && rect.top < box.bottom) return item
  }
  return null
}

function px(value: string | undefined) {
  if (!value) return 0
  const number = Number.parseFloat(value)
  return Number.isFinite(number) ? number : 0
}

function paddingBlock(element: HTMLElement) {
  const style = window.getComputedStyle(element)
  return {
    end: px(style.paddingBlockEnd || style.paddingBottom),
    start: px(style.paddingBlockStart || style.paddingTop),
  }
}

function contentPadding(spacer: HTMLElement | null) {
  const parent = spacer?.parentElement
  return parent ? paddingBlock(parent) : { end: 0, start: 0 }
}

function rowGap(element: HTMLElement | null) {
  if (!element) return 0
  const style = window.getComputedStyle(element)
  return px(style.rowGap === "normal" ? style.gap : style.rowGap)
}

function offsetTopIn(element: HTMLElement, viewport: HTMLElement) {
  return element.getBoundingClientRect().top - viewport.getBoundingClientRect().top + viewport.scrollTop
}

function topInViewport(element: HTMLElement, viewport: HTMLElement) {
  return element.getBoundingClientRect().top - viewport.getBoundingClientRect().top
}

// Where the content really ends: the last item's bottom plus the content's end padding, ignoring the spacer.
function contentBottom({
  content,
  spacer,
  viewport,
}: {
  content: HTMLElement
  spacer: HTMLElement | null
  viewport: HTMLElement
}) {
  const padding = paddingBlock(content)
  const box = viewport.getBoundingClientRect()
  let bottom = padding.start + padding.end
  for (const item of itemsOf(content, spacer)) {
    bottom = Math.max(bottom, item.getBoundingClientRect().bottom - box.top + viewport.scrollTop + padding.end)
  }
  return bottom
}

function spacerNeeded(layout: {
  content: HTMLElement
  scrollTop: number
  spacer: HTMLElement | null
  viewport: HTMLElement
}) {
  return layout.scrollTop + layout.viewport.clientHeight - contentBottom(layout)
}

const maxScrollTop = (viewport: HTMLElement) => Math.max(0, viewport.scrollHeight - viewport.clientHeight)

function targetScrollTop({
  align,
  element,
  scrollMargin,
  spacer,
  viewport,
}: {
  align: MessageScrollerScrollAlign
  element: HTMLElement
  scrollMargin: number
  spacer: HTMLElement | null
  viewport: HTMLElement
}) {
  const top = offsetTopIn(element, viewport)
  const height = element.getBoundingClientRect().height
  const padding = contentPadding(spacer)
  if (align === "center") {
    const room = Math.max(0, viewport.clientHeight - padding.start - padding.end)
    return top - padding.start - (room - height) / 2 - scrollMargin
  }
  if (align === "end") return top - viewport.clientHeight + height + padding.end + scrollMargin
  if (align === "nearest") {
    const bottom = top + height
    const visibleTop = viewport.scrollTop + padding.start
    const visibleBottom = viewport.scrollTop + viewport.clientHeight - padding.end
    if (top >= visibleTop && bottom <= visibleBottom) return viewport.scrollTop
    return top < visibleTop
      ? top - padding.start - scrollMargin
      : bottom - viewport.clientHeight + padding.end + scrollMargin
  }
  return top - padding.start - scrollMargin
}

function scrollableOf({ content, scrollEdgeThreshold, spacer, viewport }: Layout & { scrollEdgeThreshold: number }) {
  if (!viewport || !content) return NOT_SCROLLABLE
  const bottom = contentBottom({ content, spacer, viewport })
  return {
    start: viewport.scrollTop > scrollEdgeThreshold,
    end: bottom - viewport.scrollTop - viewport.clientHeight > scrollEdgeThreshold,
  }
}

function visibilityOf({
  content,
  scrollMargin,
  scrollPreviousItemPeek,
  spacer,
  viewport,
  visibleMessageIds,
}: Layout & { scrollMargin: number; scrollPreviousItemPeek: number; visibleMessageIds: Set<string> }) {
  if (!content || !viewport) return NO_VISIBILITY
  const box = viewport.getBoundingClientRect()
  const line = box.top + scrollMargin + scrollPreviousItemPeek
  const noObserver = typeof IntersectionObserver === "undefined"
  const visible: string[] = []
  let currentAnchorId: string | null = null
  for (const item of itemsOf(content, spacer)) {
    const id = item.dataset.messageId
    if (!id) continue
    const anchor = item.dataset.scrollAnchor === "true"
    const rect = anchor || noObserver ? item.getBoundingClientRect() : null
    if (noObserver && rect ? rect.bottom > line && rect.top < box.bottom : visibleMessageIds.has(id)) visible.push(id)
    if (anchor && rect && rect.top <= line + EPSILON) currentAnchorId = id
  }
  return visible.length === 0 && currentAnchorId === null
    ? NO_VISIBILITY
    : { currentAnchorId, visibleMessageIds: visible }
}

// ---------------------------------------------------------------- stores

type Store<T> = {
  getSnapshot: () => T
  hasListeners: () => boolean
  setSnapshot: (value: T) => void
  subscribe: (listener: () => void, onFirst?: () => void, onLast?: () => void) => () => void
}

function createStore<T>(initial: T, equal: (a: T, b: T) => boolean): Store<T> {
  let value = initial
  const listeners = new Set<() => void>()
  return {
    getSnapshot: () => value,
    hasListeners: () => listeners.size > 0,
    setSnapshot: (next) => {
      if (equal(value, next)) return
      value = next
      listeners.forEach((listener) => listener())
    },
    subscribe: (listener, onFirst, onLast) => {
      const first = listeners.size === 0
      listeners.add(listener)
      if (first) onFirst?.()
      return () => {
        listeners.delete(listener)
        if (listeners.size === 0) onLast?.()
      }
    },
  }
}

const sameScrollable = (a: MessageScrollerScrollable, b: MessageScrollerScrollable) =>
  a.start === b.start && a.end === b.end

const sameVisibility = (a: MessageScrollerVisibilityState, b: MessageScrollerVisibilityState) =>
  a.currentAnchorId === b.currentAnchorId &&
  a.visibleMessageIds.length === b.visibleMessageIds.length &&
  a.visibleMessageIds.every((id, index) => id === b.visibleMessageIds[index])

function useLatest<T>(value: T) {
  const ref = React.useRef(value)
  ref.current = value
  return ref
}

function setRef<T>(ref: React.Ref<T> | undefined, value: T | null) {
  if (typeof ref === "function") ref(value)
  else if (ref) (ref as React.MutableRefObject<T | null>).current = value
}

// ---------------------------------------------------------------- controller

type ScrollToOptions = { behavior?: ScrollBehavior; autoscrolling?: boolean }

type Controller = {
  handleContentChange: () => void
  handleResize: () => void
  observeVisibility: () => void
  pendingDefaultScrollStore: Store<boolean>
  preserveScrollOnPrependRef: React.MutableRefObject<boolean>
  scrollToEnd: (options?: MessageScrollerScrollOptions) => boolean
  scrollToMessage: (messageId: string, options?: MessageScrollerScrollOptions) => boolean
  scrollToStart: (options?: MessageScrollerScrollOptions) => boolean
  setContentElement: (element: HTMLDivElement | null) => void
  setRootElement: (element: HTMLDivElement | null) => void
  setSpacerElement: (element: HTMLDivElement | null) => void
  setViewportElement: (element: HTMLDivElement | null) => void
  stateStore: Store<MessageScrollerScrollable>
  syncAfterScroll: () => void
  unobserveVisibility: () => void
  userScrollIntent: () => void
  viewportRef: React.MutableRefObject<HTMLDivElement | null>
  visibilityStore: Store<MessageScrollerVisibilityState>
}

type RegisterMessage = (id: string, element: HTMLElement | null, previous: HTMLElement | null) => void

type ProviderOptions = {
  autoScroll: boolean
  defaultScrollPosition: MessageScrollerDefaultScrollPosition
  scrollEdgeThreshold: number
  scrollPreviousItemPeek: number
  scrollMargin: number
}

function useController({
  autoScroll,
  defaultScrollPosition,
  scrollEdgeThreshold,
  scrollPreviousItemPeek,
  scrollMargin,
}: ProviderOptions): { context: Controller; registerMessage: RegisterMessage } {
  const autoScrollRef = useLatest(autoScroll)
  const edgeRef = useLatest(scrollEdgeThreshold)
  const marginRef = useLatest(scrollMargin)
  const peekRef = useLatest(scrollPreviousItemPeek)
  const autoscrollingRef = React.useRef(false)
  const autoscrollingTimeoutRef = React.useRef<number | null>(null)
  const contentRef = React.useRef<HTMLDivElement | null>(null)
  const defaultAppliedRef = React.useRef(false)
  const firstItemRef = React.useRef<HTMLElement | null>(null)
  const itemCountRef = React.useRef(0)
  const lastScrollTopRef = React.useRef(0)
  const modeRef = React.useRef<Mode>(autoScroll ? "following-bottom" : "free-scrolling")
  const messagesRef = React.useRef(new Map<string, HTMLElement>())
  const pendingToMessageRef = React.useRef<{ messageId: string; options?: MessageScrollerScrollOptions } | null>(null)
  const restoreRef = React.useRef<{ element: HTMLElement; viewportTop: number } | null>(null)
  const anchoredTurnRef = React.useRef<HTMLElement | null>(null)
  const preserveScrollOnPrependRef = React.useRef(true)
  const rootRef = React.useRef<HTMLDivElement | null>(null)
  const pendingScrollFrameRef = React.useRef<number | null>(null)
  const spacerGapRef = React.useRef(0)
  const spacerHeightRef = React.useRef(0)
  const spacerRef = React.useRef<HTMLDivElement | null>(null)
  const stateFrameRef = React.useRef<number | null>(null)
  const viewportRef = React.useRef<HTMLDivElement | null>(null)
  const visibilityFrameRef = React.useRef<number | null>(null)
  const observerRef = React.useRef<IntersectionObserver | null>(null)
  const visibleIdsRef = React.useRef(new Set<string>())
  const handledAnchorsRef = React.useRef(new WeakSet<HTMLElement>())

  const [pendingDefaultScrollStore] = React.useState(() =>
    createStore(defaultScrollPosition === "end" || defaultScrollPosition === "last-anchor", (a, b) => a === b),
  )
  const [stateStore] = React.useState(() => createStore(NOT_SCROLLABLE, sameScrollable))
  const [visibilityStore] = React.useState(() => createStore(NO_VISIBILITY, sameVisibility))

  const positionRef = React.useRef(defaultScrollPosition)
  if (positionRef.current !== defaultScrollPosition) {
    positionRef.current = defaultScrollPosition
    defaultAppliedRef.current = false
  }

  const clearPendingDefault = () => pendingDefaultScrollStore.setSnapshot(false)
  const markDefaultApplied = () => {
    defaultAppliedRef.current = true
    clearPendingDefault()
  }

  const layout = (): Layout => ({
    content: contentRef.current,
    spacer: spacerRef.current,
    viewport: viewportRef.current,
  })

  const writeAttributes = React.useCallback((scrollable: MessageScrollerScrollable) => {
    const value = [scrollable.start && "start", scrollable.end && "end"].filter(Boolean).join(" ")
    for (const element of [rootRef.current, viewportRef.current]) {
      if (!element) continue
      if (value) element.setAttribute("data-scrollable", value)
      else element.removeAttribute("data-scrollable")
      element.toggleAttribute("data-autoscrolling", autoscrollingRef.current)
    }
  }, [])

  const updateMode = React.useCallback((scrollable: MessageScrollerScrollable) => {
    const top = viewportRef.current?.scrollTop ?? 0
    const scrolledUp = top < lastScrollTopRef.current - EPSILON
    lastScrollTopRef.current = top
    if (
      autoScrollRef.current &&
      !scrollable.end &&
      modeRef.current !== "settling-jump" &&
      modeRef.current !== "anchored-to-message"
    ) {
      modeRef.current = "following-bottom"
    } else if (modeRef.current === "following-bottom" && scrollable.end && scrolledUp && !autoscrollingRef.current) {
      modeRef.current = "free-scrolling"
    }
  }, [])

  const commitScrollState = React.useCallback(() => {
    const scrollable = scrollableOf({ ...layout(), scrollEdgeThreshold: edgeRef.current })
    updateMode(scrollable)
    // While following the bottom there is nothing below worth a "jump to latest" button.
    const shown = modeRef.current === "following-bottom" ? { ...scrollable, end: false } : scrollable
    writeAttributes(shown)
    stateStore.setSnapshot(shown)
  }, [updateMode, stateStore, writeAttributes])

  const scheduleStateCommit = React.useCallback(() => {
    if (stateFrameRef.current !== null) return
    stateFrameRef.current = window.requestAnimationFrame(() => {
      stateFrameRef.current = null
      commitScrollState()
    })
  }, [commitScrollState])

  const scheduleVisibilitySync = React.useCallback(() => {
    if (!visibilityStore.hasListeners() || visibilityFrameRef.current !== null) return
    visibilityFrameRef.current = window.requestAnimationFrame(() => {
      visibilityFrameRef.current = null
      if (!visibilityStore.hasListeners()) return
      visibilityStore.setSnapshot(
        visibilityOf({
          ...layout(),
          scrollMargin: marginRef.current,
          scrollPreviousItemPeek: peekRef.current,
          visibleMessageIds: visibleIdsRef.current,
        }),
      )
    })
  }, [visibilityStore])

  // ------------------------------------------------ scrolling

  const setAutoscrolling = React.useCallback(
    (on: boolean) => {
      if (autoscrollingTimeoutRef.current !== null) {
        window.clearTimeout(autoscrollingTimeoutRef.current)
        autoscrollingTimeoutRef.current = null
      }
      if (autoscrollingRef.current !== on) {
        autoscrollingRef.current = on
        commitScrollState()
      }
      if (on) {
        autoscrollingTimeoutRef.current = window.setTimeout(() => {
          autoscrollingTimeoutRef.current = null
          autoscrollingRef.current = false
          commitScrollState()
        }, AUTOSCROLL_MS)
      }
    },
    [commitScrollState],
  )

  const setSpacerHeight = React.useCallback((height: number) => {
    const spacer = spacerRef.current
    if (!spacer) return
    const next = Math.max(0, Math.ceil(height))
    if (spacerHeightRef.current === next) return
    spacerHeightRef.current = next
    spacer.hidden = next === 0
    spacer.style.height = `${next}px`
    // The content's gap would add space above the spacer; cancel it.
    spacer.style.marginTop = next > 0 ? `${-spacerGapRef.current}px` : ""
  }, [])

  const scrollViewportTo = React.useCallback(
    (top: number, { behavior = "auto", autoscrolling = false }: ScrollToOptions = {}) => {
      const viewport = viewportRef.current
      if (!viewport) return
      const target = Math.max(0, top)
      if (Math.abs(viewport.scrollTop - target) <= EPSILON) {
        viewport.scrollTop = target
        commitScrollState()
        return
      }
      if (autoscrolling) setAutoscrolling(true)
      viewport.scrollTo({ top: target, behavior })
      scheduleStateCommit()
    },
    [commitScrollState, scheduleStateCommit, setAutoscrolling],
  )

  const scrollToStart = React.useCallback(
    ({ behavior = "auto" }: MessageScrollerScrollOptions = {}) => {
      if (!viewportRef.current) return false
      setSpacerHeight(0)
      anchoredTurnRef.current = null
      modeRef.current = "free-scrolling"
      scrollViewportTo(0, { behavior })
      scheduleVisibilitySync()
      return true
    },
    [scheduleVisibilitySync, scrollViewportTo, setSpacerHeight],
  )

  const scrollToEnd = React.useCallback(
    ({ behavior = "auto" }: MessageScrollerScrollOptions = {}) => {
      const viewport = viewportRef.current
      if (!viewport) return false
      setSpacerHeight(0)
      anchoredTurnRef.current = null
      modeRef.current = autoScrollRef.current ? "following-bottom" : "free-scrolling"
      scrollViewportTo(maxScrollTop(viewport), { autoscrolling: true, behavior })
      scheduleVisibilitySync()
      return true
    },
    [scheduleVisibilitySync, scrollViewportTo, setSpacerHeight],
  )

  const scrollToElement = React.useCallback(
    (
      element: HTMLElement,
      {
        align = "start",
        behavior = "auto",
        scrollMargin: margin = marginRef.current,
      }: MessageScrollerScrollOptions = {},
      { keepPreviousPeek = false }: { keepPreviousPeek?: boolean } = {},
    ) => {
      const content = contentRef.current
      const viewport = viewportRef.current
      if (!content || !viewport || !content.contains(element)) return false
      const top = targetScrollTop({
        align,
        element,
        scrollMargin: keepPreviousPeek ? margin + peekRef.current : margin,
        spacer: spacerRef.current,
        viewport,
      })
      setSpacerHeight(spacerNeeded({ content, scrollTop: top, spacer: spacerRef.current, viewport }))
      restoreRef.current = { element, viewportTop: topInViewport(element, viewport) }
      modeRef.current = keepPreviousPeek ? "anchored-to-message" : "settling-jump"
      anchoredTurnRef.current = keepPreviousPeek ? element : null
      scrollViewportTo(top, { behavior })
      scheduleVisibilitySync()
      return true
    },
    [scheduleVisibilitySync, scrollViewportTo, setSpacerHeight],
  )

  const reanchorToAnchoredMessage = React.useCallback(() => {
    const element = anchoredTurnRef.current
    if (!element || !element.isConnected || modeRef.current !== "anchored-to-message") return false
    return scrollToElement(element, { align: "start" }, { keepPreviousPeek: true })
  }, [scrollToElement])

  const scrollToMessage = React.useCallback(
    (messageId: string, options?: MessageScrollerScrollOptions) => {
      const element = messagesRef.current.get(messageId)
      if (element) {
        markDefaultApplied()
        if (scrollToElement(element, options)) pendingToMessageRef.current = null
        else pendingToMessageRef.current = { messageId, options }
        return true
      }
      if (itemCountRef.current === 0) {
        pendingToMessageRef.current = { messageId, options }
        markDefaultApplied()
        return true
      }
      return false
    },
    [scrollToElement],
  )

  const flushPendingScrollToMessage = React.useCallback(() => {
    const pending = pendingToMessageRef.current
    if (!pending) return false
    const element = messagesRef.current.get(pending.messageId)
    if (!element || !scrollToElement(element, pending.options)) return false
    pendingToMessageRef.current = null
    markDefaultApplied()
    return true
  }, [scrollToElement])

  // ------------------------------------------------ content changes

  const restorePrependPosition = React.useCallback(() => {
    const restore = restoreRef.current
    const viewport = viewportRef.current
    if (!restore || !viewport || !restore.element.isConnected) return false
    const delta = topInViewport(restore.element, viewport) - restore.viewportTop
    if (Math.abs(delta) <= EPSILON) return false
    viewport.scrollTop += delta
    restore.viewportTop = topInViewport(restore.element, viewport)
    scheduleStateCommit()
    scheduleVisibilitySync()
    return true
  }, [scheduleStateCommit, scheduleVisibilitySync])

  const rememberFirstVisible = React.useCallback(() => {
    const content = contentRef.current
    const viewport = viewportRef.current
    if (!content || !viewport) {
      restoreRef.current = null
      return
    }
    const element = firstVisibleItem({ content, spacer: spacerRef.current, viewport })
    restoreRef.current = element ? { element, viewportTop: topInViewport(element, viewport) } : null
  }, [])

  const schedulePendingScroll = React.useCallback(() => {
    if (pendingScrollFrameRef.current !== null) return
    pendingScrollFrameRef.current = window.requestAnimationFrame(() => {
      pendingScrollFrameRef.current = null
      if (flushPendingScrollToMessage()) rememberFirstVisible()
    })
  }, [rememberFirstVisible, flushPendingScrollToMessage])

  const applyDefaultScroll = React.useCallback(() => {
    if (!defaultScrollPosition || defaultAppliedRef.current || itemCountRef.current === 0) return false
    let done = false
    if (defaultScrollPosition === "last-anchor") {
      const content = contentRef.current
      const viewport = viewportRef.current
      const anchor = content && viewport ? lastAnchor(itemsOf(content, spacerRef.current)) : null
      if (!content || !viewport || !anchor) done = scrollToEnd({ behavior: "auto" })
      else {
        const top = offsetTopIn(anchor, viewport)
        // A last turn that fits on screen is shown whole, from the bottom.
        done =
          contentBottom({ content, spacer: spacerRef.current, viewport }) - top <= viewport.clientHeight
            ? scrollToEnd({ behavior: "auto" })
            : scrollToElement(anchor, { align: "start" }, { keepPreviousPeek: true })
      }
    } else {
      done = defaultScrollPosition === "end" ? scrollToEnd({ behavior: "auto" }) : scrollToStart({ behavior: "auto" })
    }
    if (done) markDefaultApplied()
    return done
  }, [defaultScrollPosition, scrollToElement, scrollToEnd, scrollToStart])

  const handleContentChange = React.useCallback(() => {
    const content = contentRef.current
    if (!content) return
    const items = itemsOf(content, spacerRef.current)
    const previousCount = itemCountRef.current
    const previousFirst = firstItemRef.current
    itemCountRef.current = items.length
    firstItemRef.current = items[0] ?? null
    ;(() => {
      if (flushPendingScrollToMessage()) return
      if (previousCount === 0) {
        if (applyDefaultScroll() || (items.length > 0 && autoScrollRef.current && scrollToEnd({ behavior: "auto" })))
          return
        commitScrollState()
        scheduleVisibilitySync()
        return
      }
      // Older items were prepended: keep what the user was reading where it was.
      const firstIndex = previousFirst ? items.indexOf(previousFirst) : -1
      if (preserveScrollOnPrependRef.current && firstIndex > 0) {
        restorePrependPosition()
        return
      }
      if (items.length > previousCount) {
        const anchor = firstAnchorFrom(items, previousCount)
        if (anchor) {
          if (
            autoScrollRef.current &&
            modeRef.current === "following-bottom" &&
            severalAnchorsFrom(items, previousCount)
          ) {
            scrollToEnd({ behavior: "auto" })
            return
          }
          scrollToElement(anchor, { align: "start" }, { keepPreviousPeek: true })
          handledAnchorsRef.current.add(anchor)
          return
        }
      }
      if (items.length === previousCount) {
        const anchor = firstUnhandledAnchor(items, handledAnchorsRef.current)
        if (anchor) {
          scrollToElement(anchor, { align: "start" }, { keepPreviousPeek: true })
          handledAnchorsRef.current.add(anchor)
          return
        }
      }
      if (modeRef.current === "following-bottom" && autoScrollRef.current) scrollToEnd({ behavior: "auto" })
      else {
        commitScrollState()
        scheduleVisibilitySync()
      }
    })()
    rememberFirstVisible()
  }, [
    applyDefaultScroll,
    rememberFirstVisible,
    commitScrollState,
    flushPendingScrollToMessage,
    restorePrependPosition,
    scheduleVisibilitySync,
    scrollToElement,
    scrollToEnd,
  ])

  const handleResize = React.useCallback(() => {
    if (modeRef.current === "following-bottom" && autoScrollRef.current) {
      scrollToEnd({ behavior: "auto" })
      return
    }
    const spacerBefore = spacerHeightRef.current
    if (reanchorToAnchoredMessage()) {
      // The answer outgrew the spacer: from now on follow the bottom.
      if (autoScrollRef.current && spacerBefore > 0 && spacerHeightRef.current === 0) scrollToEnd({ behavior: "auto" })
      return
    }
    scheduleStateCommit()
    scheduleVisibilitySync()
  }, [reanchorToAnchoredMessage, scheduleStateCommit, scheduleVisibilitySync, scrollToEnd])

  // ------------------------------------------------ visibility

  const observeVisibility = React.useCallback(() => {
    const viewport = viewportRef.current
    if (!viewport || !visibilityStore.hasListeners()) return
    if (typeof IntersectionObserver === "undefined") {
      scheduleVisibilitySync()
      return
    }
    if (!observerRef.current) {
      observerRef.current = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) {
            const id = (entry.target as HTMLElement).dataset.messageId
            if (!id) continue
            if (entry.isIntersecting) visibleIdsRef.current.add(id)
            else visibleIdsRef.current.delete(id)
          }
          scheduleVisibilitySync()
        },
        {
          root: viewport,
          rootMargin: `${-(marginRef.current + peekRef.current)}px 0px 0px 0px`,
          threshold: [0, 0.01, 0.5, 1],
        },
      )
    }
    messagesRef.current.forEach((element) => observerRef.current?.observe(element))
    scheduleVisibilitySync()
  }, [scheduleVisibilitySync, visibilityStore])

  const unobserveVisibility = React.useCallback(() => {
    if (visibilityFrameRef.current !== null) {
      window.cancelAnimationFrame(visibilityFrameRef.current)
      visibilityFrameRef.current = null
    }
    observerRef.current?.disconnect()
    observerRef.current = null
    visibleIdsRef.current.clear()
    visibilityStore.setSnapshot(NO_VISIBILITY)
  }, [visibilityStore])

  const registerMessage = React.useCallback<RegisterMessage>(
    (id, element, previous) => {
      if (element) {
        messagesRef.current.set(id, element)
        observerRef.current?.observe(element)
        scheduleVisibilitySync()
        if (pendingToMessageRef.current?.messageId === id) schedulePendingScroll()
        return
      }
      if (previous && messagesRef.current.get(id) === previous) {
        messagesRef.current.delete(id)
        visibleIdsRef.current.delete(id)
        observerRef.current?.unobserve(previous)
        scheduleVisibilitySync()
      }
    },
    [schedulePendingScroll, scheduleVisibilitySync],
  )

  // ------------------------------------------------ element refs and user input

  const userScrollIntent = React.useCallback(() => {
    if (
      modeRef.current === "following-bottom" ||
      modeRef.current === "anchored-to-message" ||
      modeRef.current === "settling-jump"
    ) {
      anchoredTurnRef.current = null
      modeRef.current = "free-scrolling"
    }
  }, [])

  const rewriteAttributes = React.useCallback(
    () => writeAttributes(stateStore.getSnapshot()),
    [stateStore, writeAttributes],
  )

  const setRootElement = React.useCallback(
    (element: HTMLDivElement | null) => {
      rootRef.current = element
      if (element) rewriteAttributes()
    },
    [rewriteAttributes],
  )

  const setViewportElement = React.useCallback(
    (element: HTMLDivElement | null) => {
      viewportRef.current = element
      if (element) rewriteAttributes()
    },
    [rewriteAttributes],
  )

  const setContentElement = React.useCallback((element: HTMLDivElement | null) => {
    contentRef.current = element
  }, [])

  const setSpacerElement = React.useCallback((element: HTMLDivElement | null) => {
    spacerRef.current = element
    spacerGapRef.current = rowGap(element?.parentElement ?? null)
  }, [])

  const syncAfterScroll = React.useCallback(() => {
    commitScrollState()
    scheduleVisibilitySync()
    rememberFirstVisible()
  }, [rememberFirstVisible, commitScrollState, scheduleVisibilitySync])

  const context = React.useMemo<Controller>(
    () => ({
      handleContentChange,
      handleResize,
      observeVisibility,
      pendingDefaultScrollStore,
      preserveScrollOnPrependRef,
      scrollToEnd,
      scrollToMessage,
      scrollToStart,
      setContentElement,
      setRootElement,
      setSpacerElement,
      setViewportElement,
      stateStore,
      syncAfterScroll,
      unobserveVisibility,
      userScrollIntent,
      viewportRef,
      visibilityStore,
    }),
    [
      handleContentChange,
      handleResize,
      observeVisibility,
      pendingDefaultScrollStore,
      scrollToEnd,
      scrollToMessage,
      scrollToStart,
      setContentElement,
      setRootElement,
      setSpacerElement,
      setViewportElement,
      stateStore,
      syncAfterScroll,
      unobserveVisibility,
      userScrollIntent,
      visibilityStore,
    ],
  )

  React.useLayoutEffect(() => {
    if (!applyDefaultScroll() && itemCountRef.current === 0) clearPendingDefault()
  }, [applyDefaultScroll])

  React.useEffect(
    () => () => {
      for (const frame of [stateFrameRef, visibilityFrameRef, pendingScrollFrameRef]) {
        if (frame.current !== null) window.cancelAnimationFrame(frame.current)
        frame.current = null
      }
      if (autoscrollingTimeoutRef.current !== null) window.clearTimeout(autoscrollingTimeoutRef.current)
      autoscrollingTimeoutRef.current = null
      observerRef.current?.disconnect()
      observerRef.current = null
    },
    [],
  )

  React.useLayoutEffect(() => {
    if (autoScroll && modeRef.current === "following-bottom" && itemCountRef.current > 0) {
      scrollToEnd({ behavior: "auto" })
      return
    }
    commitScrollState()
  }, [autoScroll, commitScrollState, scrollToEnd])

  return { context, registerMessage }
}

// ---------------------------------------------------------------- contexts and hooks

const ControllerContext = React.createContext<Controller | null>(null)
const RegisterContext = React.createContext<RegisterMessage | null>(null)

function useController_() {
  const context = React.useContext(ControllerContext)
  if (!context) throw new Error("useMessageScroller must be used within a MessageScroller.")
  return context
}

export function useMessageScroller() {
  const { scrollToEnd, scrollToMessage, scrollToStart } = useController_()
  return React.useMemo(
    () => ({ scrollToEnd, scrollToMessage, scrollToStart }),
    [scrollToEnd, scrollToMessage, scrollToStart],
  )
}

export function useMessageScrollerScrollable(): MessageScrollerScrollable {
  const { stateStore } = useController_()
  return useSyncExternalStore(stateStore.subscribe, stateStore.getSnapshot, stateStore.getSnapshot)
}

export function useMessageScrollerVisibility(): MessageScrollerVisibilityState {
  const { observeVisibility, unobserveVisibility, visibilityStore } = useController_()
  const subscribe = React.useCallback(
    (listener: () => void) => visibilityStore.subscribe(listener, observeVisibility, unobserveVisibility),
    [observeVisibility, unobserveVisibility, visibilityStore],
  )
  return useSyncExternalStore(subscribe, visibilityStore.getSnapshot, visibilityStore.getSnapshot)
}

function usePendingDefaultScroll() {
  const { pendingDefaultScrollStore: store } = useController_()
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot)
}

// ---------------------------------------------------------------- components

export type MessageScrollerProviderProps = {
  children?: React.ReactNode
  autoScroll?: boolean
  defaultScrollPosition?: MessageScrollerDefaultScrollPosition
  scrollEdgeThreshold?: number
  scrollPreviousItemPeek?: number
  scrollMargin?: number
}

function Provider({
  autoScroll = false,
  children,
  defaultScrollPosition = "end",
  scrollEdgeThreshold = DEFAULT_EDGE_THRESHOLD,
  scrollPreviousItemPeek = DEFAULT_PREVIOUS_PEEK,
  scrollMargin = DEFAULT_SCROLL_MARGIN,
}: MessageScrollerProviderProps) {
  const { context, registerMessage } = useController({
    autoScroll,
    defaultScrollPosition,
    scrollEdgeThreshold,
    scrollPreviousItemPeek,
    scrollMargin,
  })
  return (
    <ControllerContext.Provider value={context}>
      <RegisterContext.Provider value={registerMessage}>{children}</RegisterContext.Provider>
    </ControllerContext.Provider>
  )
}

export type MessageScrollerProps = React.ComponentPropsWithoutRef<"div">

const Root = React.forwardRef<HTMLDivElement, MessageScrollerProps>(function MessageScrollerRoot(
  { children, ...props },
  ref,
) {
  const { setRootElement } = useController_()
  const pending = usePendingDefaultScroll()
  const setRefs = React.useCallback(
    (element: HTMLDivElement | null) => {
      setRootElement(element)
      setRef(ref, element)
    },
    [ref, setRootElement],
  )
  return (
    <div ref={setRefs} {...props} {...(pending ? { "data-pending-scroll": "" } : null)}>
      {children}
    </div>
  )
})

export type MessageScrollerViewportProps = React.ComponentPropsWithoutRef<"div"> & { preserveScrollOnPrepend?: boolean }

const Viewport = React.forwardRef<HTMLDivElement, MessageScrollerViewportProps>(function MessageScrollerViewport(
  {
    "aria-label": ariaLabel,
    children,
    onKeyDown,
    onScroll,
    onTouchMove,
    onWheel,
    preserveScrollOnPrepend = true,
    role,
    tabIndex,
    ...props
  },
  ref,
) {
  const {
    handleResize,
    preserveScrollOnPrependRef,
    setViewportElement,
    syncAfterScroll,
    userScrollIntent,
    viewportRef,
  } = useController_()
  const pending = usePendingDefaultScroll()
  preserveScrollOnPrependRef.current = preserveScrollOnPrepend
  const setRefs = React.useCallback(
    (element: HTMLDivElement | null) => {
      setViewportElement(element)
      setRef(ref, element)
    },
    [ref, setViewportElement],
  )

  React.useEffect(() => {
    const viewport = viewportRef.current
    if (!viewport || typeof ResizeObserver === "undefined") return
    let frame = 0
    const observer = new ResizeObserver(() => {
      window.cancelAnimationFrame(frame)
      frame = window.requestAnimationFrame(handleResize)
    })
    observer.observe(viewport)
    return () => {
      window.cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [handleResize, viewportRef])

  return (
    <div
      ref={setRefs}
      role={role ?? "region"}
      aria-label={ariaLabel ?? "Messages"}
      tabIndex={tabIndex ?? 0}
      onKeyDown={(event) => {
        if (SCROLL_KEYS.has(event.key)) userScrollIntent()
        onKeyDown?.(event)
      }}
      onScroll={(event) => {
        syncAfterScroll()
        onScroll?.(event)
      }}
      onTouchMove={(event) => {
        userScrollIntent()
        onTouchMove?.(event)
      }}
      onWheel={(event) => {
        userScrollIntent()
        onWheel?.(event)
      }}
      {...props}
      {...(pending ? { "data-pending-scroll": "" } : null)}
    >
      {children}
    </div>
  )
})

export type MessageScrollerContentProps = React.ComponentPropsWithoutRef<"div"> & { spacerClassName?: string }

const Content = React.forwardRef<HTMLDivElement, MessageScrollerContentProps>(function MessageScrollerContent(
  { "aria-relevant": ariaRelevant, children, role, spacerClassName, ...props },
  ref,
) {
  const { handleContentChange, handleResize, setContentElement, setSpacerElement } = useController_()
  const contentRef = React.useRef<HTMLDivElement | null>(null)
  const setRefs = React.useCallback(
    (element: HTMLDivElement | null) => {
      contentRef.current = element
      setContentElement(element)
      setRef(ref, element)
    },
    [ref, setContentElement],
  )

  React.useLayoutEffect(() => {
    const content = contentRef.current
    if (!content) return
    handleContentChange()
    if (typeof MutationObserver === "undefined") return
    const observer = new MutationObserver(() => handleContentChange())
    observer.observe(content, { childList: true })
    return () => observer.disconnect()
  }, [handleContentChange])

  React.useEffect(() => {
    const content = contentRef.current
    if (!content || typeof ResizeObserver === "undefined") return
    let frame = 0
    const observer = new ResizeObserver(() => {
      window.cancelAnimationFrame(frame)
      frame = window.requestAnimationFrame(handleResize)
    })
    observer.observe(content)
    return () => {
      window.cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [handleResize])

  return (
    <div ref={setRefs} role={role ?? "log"} aria-relevant={ariaRelevant ?? "additions"} {...props}>
      {children}
      <div
        ref={setSpacerElement}
        aria-hidden="true"
        data-message-scroller-spacer=""
        hidden
        className={spacerClassName}
      />
    </div>
  )
})

export type MessageScrollerItemProps = React.ComponentPropsWithoutRef<"div"> & {
  messageId?: string
  scrollAnchor?: boolean
}

const Item = React.forwardRef<HTMLDivElement, MessageScrollerItemProps>(function MessageScrollerItem(
  { messageId, scrollAnchor = false, ...props },
  ref,
) {
  const register = React.useContext(RegisterContext)
  if (!register) throw new Error("MessageScrollerItem must be used within a MessageScroller.")
  const elementRef = React.useRef<HTMLDivElement | null>(null)
  const setRefs = React.useCallback(
    (element: HTMLDivElement | null) => {
      const previous = elementRef.current
      elementRef.current = element
      if (messageId) register(messageId, element, previous)
      setRef(ref, element)
    },
    [messageId, ref, register],
  )
  return (
    <div ref={setRefs} data-message-id={messageId} data-scroll-anchor={scrollAnchor ? "true" : "false"} {...props} />
  )
})

export type MessageScrollerButtonState = { active: boolean; direction: MessageScrollerButtonDirection }

export type MessageScrollerButtonProps = Omit<React.ComponentPropsWithoutRef<"button">, "className"> & {
  behavior?: ScrollBehavior
  direction?: MessageScrollerButtonDirection
  className?: string
  // An element whose props are merged with the button's (Base UI style), or a function of props and state.
  render?:
    | React.ReactElement
    | ((props: React.ComponentPropsWithRef<"button">, state: MessageScrollerButtonState) => React.ReactElement)
}

type AnyProps = Record<string, unknown>

function chain(own: (event: React.SyntheticEvent) => void, theirs: (event: React.SyntheticEvent) => void) {
  return (event: React.SyntheticEvent) => {
    theirs(event)
    if (!event.defaultPrevented) own(event)
  }
}

// The primitive's mergeProps: class names join, styles merge, refs both get the node, and an element's own event
// handler runs first (it can preventDefault the primitive's).
function mergeProps(base: AnyProps, extra: AnyProps) {
  const merged: AnyProps = { ...base }
  for (const [key, value] of Object.entries(extra)) {
    if (value === undefined) continue
    const current = merged[key]
    if (key === "className") merged[key] = [current, value].filter(Boolean).join(" ")
    else if (key === "style") merged[key] = { ...(current as object), ...(value as object) }
    else if (/^on[A-Z]/.test(key) && typeof current === "function" && typeof value === "function") {
      merged[key] = chain(
        current as (event: React.SyntheticEvent) => void,
        value as (event: React.SyntheticEvent) => void,
      )
    } else merged[key] = value
  }
  return merged
}

const Button = React.forwardRef<HTMLButtonElement, MessageScrollerButtonProps>(function MessageScrollerButton(
  { behavior = "smooth", children, direction = "end", onClick, render, tabIndex, type = "button", ...props },
  ref,
) {
  const { scrollToEnd, scrollToStart, stateStore } = useController_()
  const onClickRef = useLatest(onClick)
  const subscribe = React.useCallback((listener: () => void) => stateStore.subscribe(listener), [stateStore])
  const getActive = React.useCallback(() => {
    const snapshot = stateStore.getSnapshot()
    return direction === "start" ? snapshot.start : snapshot.end
  }, [direction, stateStore])
  const active = useSyncExternalStore(subscribe, getActive, getActive)

  const handleClick = React.useCallback(
    (event: React.MouseEvent<HTMLButtonElement>) => {
      if (!active) return
      onClickRef.current?.(event)
      if (event.defaultPrevented) return
      event.currentTarget.blur()
      if (direction === "start") scrollToStart({ behavior })
      else scrollToEnd({ behavior })
    },
    [active, behavior, direction, onClickRef, scrollToEnd, scrollToStart],
  )

  const state: MessageScrollerButtonState = { active, direction }
  const own = mergeProps(
    {
      type,
      ...inert(!active),
      tabIndex: active ? tabIndex : -1,
      children: children ?? <span>Scroll to {direction}</span>,
      onClick: handleClick,
      "data-active": active ? "true" : "false",
      "data-direction": direction,
    },
    props as AnyProps,
  )
  if (typeof render === "function") return render({ ...(own as React.ComponentPropsWithRef<"button">), ref }, state)
  if (render && React.isValidElement(render)) {
    const element = render as React.ReactElement<AnyProps> & { ref?: React.Ref<unknown> }
    const elementRef = element.ref
    const merged = mergeProps(own, element.props)
    return React.cloneElement(element, {
      ...merged,
      ref: (node: HTMLButtonElement | null) => {
        setRef(ref, node)
        setRef(elementRef as React.Ref<HTMLButtonElement> | undefined, node)
      },
    })
  }
  return <button ref={ref} {...(own as React.ComponentPropsWithoutRef<"button">)} />
})

export const MessageScroller = { Provider, Root, Viewport, Content, Item, Button }
