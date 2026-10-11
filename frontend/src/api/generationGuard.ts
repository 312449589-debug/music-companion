import type { ReadyWork } from './generation'

export function isActiveResponse(epoch: number, currentEpoch: number, jobId: string, currentJobId: string | null, aborted: boolean): boolean {
  return !aborted && epoch === currentEpoch && jobId === currentJobId
}

export function replacementMatches(next: ReadyWork, previous: ReadyWork | null): boolean {
  if (!previous) return true
  return next.job_id !== previous.job_id && next.composition_id !== previous.composition_id &&
    next.composition.source_composition_id === previous.composition_id &&
    next.composition.tempo_bpm === previous.composition.tempo_bpm &&
    next.composition.key_signature === previous.composition.key_signature
}
