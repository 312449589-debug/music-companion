// One tab's current session, not a music library; persist IDs before any POST.
export type PendingSubmission = { id: string; prompt: string; sourceId?: string }
export type CurrentSession = { prompt: string; visibleJobId?: string; pending?: PendingSubmission }
const key = 'music-companion-current-v1'
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
export function loadSession(): CurrentSession | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(key) || 'null')
    if (!value || typeof value.prompt !== 'string' || value.prompt.length > 1000) return null
    if (value.visibleJobId !== undefined && !uuid.test(value.visibleJobId)) return null
    if (value.pending && (!uuid.test(value.pending.id) || typeof value.pending.prompt !== 'string' ||
        !value.pending.prompt.trim() || value.pending.prompt.length > 1000 ||
        (value.pending.sourceId !== undefined && !uuid.test(value.pending.sourceId)))) return null
    return value
  } catch { return null }
}
export function saveSession(value: CurrentSession): boolean {
  try { sessionStorage.setItem(key, JSON.stringify(value)); return true } catch { return false }
}
