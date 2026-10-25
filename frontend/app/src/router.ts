/**
 * Two routes are not worth a router library: `/` is the artifact list, `/edit/<id>` the editor. The server
 * serves the same shell for both; `navigate` pushes a history entry and the app re-renders on `popstate`.
 */

import { useEffect, useState } from 'react'

export type Route = { page: 'list' } | { page: 'edit'; id: string } | { page: 'missing' }

export function parseRoute(pathname: string): Route {
  if (pathname === '/') return { page: 'list' }
  const match = /^\/edit\/([0-9a-f-]{36})\/?$/.exec(pathname)
  if (match) return { page: 'edit', id: match[1] }
  return { page: 'missing' }
}

const listeners = new Set<() => void>()
let guard: ((to: string) => boolean) | null = null
let position = Number(window.history.state?.oaIndex ?? 0)
let currentPath = window.location.pathname + window.location.search + window.location.hash
let restoring = false
window.history.replaceState({ ...window.history.state, oaIndex: position }, '', currentPath)

export function setNavigationGuard(value: ((to: string) => boolean) | null): void {
  guard = value
}

window.addEventListener('popstate', () => {
  if (restoring) {
    restoring = false
    return
  }
  const next = Number(window.history.state?.oaIndex ?? 0)
  const path = window.location.pathname + window.location.search + window.location.hash
  if (path !== currentPath && guard && !guard(path)) {
    restoring = true
    window.history.go(position - next)
    return
  }
  position = next
  currentPath = path
  for (const listener of listeners) listener()
})

/** Go to a path within the app without a full page load. */
export function navigate(path: string): void {
  if (path !== currentPath && guard && !guard(path)) return
  window.history.pushState({ oaIndex: ++position }, '', path)
  currentPath = path
  for (const listener of listeners) listener()
}

/** The current route, updated on `navigate` and the browser's back / forward. */
export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(window.location.pathname))
  useEffect(() => {
    const update = () => setRoute(parseRoute(window.location.pathname))
    listeners.add(update)
    return () => {
      listeners.delete(update)
    }
  }, [])
  return route
}
