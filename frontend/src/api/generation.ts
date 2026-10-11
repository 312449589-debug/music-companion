import type { Composition } from '../types/composition'

export type ReadyWork = { job_id: string; status: 'ready'; composition_id: string; composition: Composition; alphatex: string; audio_seconds: number; audio_url: string; pdf_url: string }
export type JobState = ReadyWork | { job_id: string; status: 'queued' | 'running'; stage: string; progress?: string; cancellation_requested?: boolean } | { job_id: string; status: 'failed'; error: { message: string } }
export class RequestFailure extends Error {
  uncertain: boolean
  status?: number
  constructor(message: string, uncertain = false, status?: number) { super(message); this.uncertain = uncertain; this.status = status }
}
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
async function request(path: string, init: RequestInit, signal: AbortSignal): Promise<Record<string, unknown>> {
  const timeout = new AbortController()
  const cancel = () => timeout.abort()
  signal.addEventListener('abort', cancel, { once: true })
  if (signal.aborted) timeout.abort()
  const timer = setTimeout(cancel, 15000)
  try {
    const response = await fetch(path, { ...init, signal: timeout.signal })
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      // Show only known local API messages; never display raw HTML or transport errors.
      const messages: Record<number, string> = { 422: '描述格式不正确，请输入1至1000字的描述。', 429: '生成队列已满，请稍后重试。', 503: '服务暂时不可用，请稍后重试。', 404: '找不到生成任务，请确认服务没有更换。', 409: '作品文件尚未完整可用，请稍后重新查询。' }
      throw new RequestFailure(body?.error?.code === 'source_not_found' ? '找不到完整原作品，请先完成首次生成。' : messages[response.status] || '服务响应异常，请稍后重试。', init.method === 'POST' && response.status >= 500, response.status)
    }
    if (!body || typeof body !== 'object') throw new RequestFailure('服务返回内容不完整。', init.method === 'POST')
    return body
  } catch (error) {
    if (error instanceof RequestFailure) throw error
    throw new RequestFailure('连接中断或请求超时。', init.method === 'POST')
  } finally { clearTimeout(timer); signal.removeEventListener('abort', cancel) }
}
export async function submitGeneration(prompt: string, signal: AbortSignal, sourceCompositionId?: string, requestId?: string): Promise<string> {
  const body = await request('/api/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt: prompt.trim(), ...(sourceCompositionId ? { source_composition_id: sourceCompositionId } : {}), ...(requestId ? { request_id: requestId } : {}) }) }, signal)
  if (typeof body.job_id !== 'string' || !uuid.test(body.job_id)) throw new RequestFailure('没有收到有效任务编号，请勿重复提交。', true)
  return body.job_id
}
export async function getGeneration(jobId: string, signal: AbortSignal): Promise<JobState> {
  const body = await request('/api/jobs/' + jobId, { method: 'GET' }, signal)
  if (body.job_id !== jobId || !['queued', 'running', 'failed', 'ready'].includes(String(body.status))) throw new RequestFailure('任务响应不完整，请重新查询。')
  if (body.status === 'ready') {
    const piece = body.composition as Composition | undefined
    if (!piece || piece.origin !== 'ai' || piece.composition_id !== body.composition_id || !uuid.test(piece.composition_id) || typeof piece.title !== 'string' || !Number.isFinite(piece.tempo_bpm) || typeof piece.key_signature !== 'string' || !Array.isArray(piece.measures) || !piece.measures.length || typeof body.alphatex !== 'string' || !body.alphatex.trim() || typeof body.audio_seconds !== 'number' || body.audio_seconds <= 0 || body.audio_seconds > 60 || body.audio_url !== '/api/jobs/' + jobId + '/audio' || body.pdf_url !== '/api/jobs/' + jobId + '/pdf') throw new RequestFailure('作品数据不完整，尚不能展示或下载，请重新查询。')
  }
  if (body.status === 'failed') {
    const error = body.error as { message?: unknown; stage?: string } | undefined
    const stageMessages: Record<string, string> = { validation: '生成的旋律未通过音乐规则检查，请重试。', fingering: '生成的旋律暂时无法安排为可弹的指型，请重试。', audio: '合成音频失败，作品尚未完整生成。请检查本地音频工具后重试。', pdf: '乐谱文件生成失败，作品尚未完整生成。请检查本地PDF导出环境后重试。' }
    return { job_id: jobId, status: 'failed', error: { message: stageMessages[error?.stage || ''] || (typeof error?.message === 'string' ? error.message : '生成失败，请重试。') } }
  }
  return body as unknown as JobState
}

export async function cancelGeneration(jobId: string, signal: AbortSignal): Promise<void> {
  await request('/api/jobs/' + jobId + '/cancel', { method: 'POST' }, signal)
}
