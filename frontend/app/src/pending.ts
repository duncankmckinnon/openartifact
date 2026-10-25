/** Transient references survive client navigation and never enter persistent browser storage. */
export interface Pending {
  text: string
  files: File[]
}
const pending = new Map<string, Pending>()
export function setPending(id: string, value: Pending): void {
  pending.set(id, value)
}
export function takePending(id: string): Pending | null {
  const value = pending.get(id) ?? null
  pending.delete(id)
  return value
}
