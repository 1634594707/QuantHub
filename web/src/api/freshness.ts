export const DATA_FRESHNESS_MS = {
  connection: 45_000,
  operational: 5 * 60_000,
  research: 30 * 60_000,
  configuration: 15 * 60_000,
} as const

export function isDataStale(updatedAt: number | null, staleAfterMs: number, now = Date.now()): boolean {
  return updatedAt !== null && now - updatedAt > staleAfterMs
}
