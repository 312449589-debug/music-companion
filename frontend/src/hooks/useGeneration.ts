import { useEffect, useRef, useState } from 'react'
import { cancelGeneration, getGeneration, RequestFailure, submitGeneration } from '../api/generation'
import { loadSession, saveSession } from '../api/currentSession'
import type { PendingSubmission } from '../api/currentSession'
import { isActiveResponse, replacementMatches } from '../api/generationGuard'
import type { ReadyWork } from '../api/generation'

type Status = 'idle' | 'submitting' | 'queued' | 'running' | 'ready' | 'failed' | 'query-error' | 'uncertain'
export function useGeneration(initialWork: ReadyWork | null = null, onBeforeReplace?: () => void) {
  const persistent = initialWork === null && window.location.pathname === '/'
  const beforeReplace = useRef(onBeforeReplace)
  beforeReplace.current = onBeforeReplace
  const [status, setStatus] = useState<Status>(initialWork ? 'ready' : 'idle')
  const [message, setMessage] = useState('')
  const [work, setWork] = useState<ReadyWork | null>(initialWork)
  const [restoredPrompt, setRestoredPrompt] = useState<string | null>(null)
  const [restoring, setRestoring] = useState(persistent && !!loadSession())
  const visibleWork = useRef<ReadyWork | null>(initialWork)
  const pendingSource = useRef<ReadyWork | null>(null)
  const pending = useRef<PendingSubmission | undefined>(undefined)
  const active = useRef(false)
  const epoch = useRef(0)
  const controller = useRef<AbortController | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const jobId = useRef<string | null>(null)
  const cancelled = useRef(false)
  const persist = (prompt: string) => !persistent || saveSession({ prompt, visibleJobId: visibleWork.current?.job_id, pending: pending.current })
  const current = (id: string, signal: AbortSignal, token: number) => isActiveResponse(token, epoch.current, id, jobId.current, signal.aborted)

  async function poll(id: string, signal: AbortSignal, token: number, failures = 0) {
    try {
      const job = await getGeneration(id, signal)
      if (!current(id, signal, token)) return
      if (job.status === 'ready') {
        if (!replacementMatches(job, pendingSource.current) ||
            (pending.current?.sourceId && job.composition.source_composition_id !== pending.current.sourceId)) {
          setStatus('failed'); setMessage('新作品的来源、速度或调性不一致，已保留上次作品。');
        } else {
          if (visibleWork.current) beforeReplace.current?.()
          visibleWork.current = job
          setWork(job); setStatus('ready'); setMessage('作品已完整生成。')
        }
        const prompt = pending.current?.prompt || job.composition.prompt
        pending.current = undefined; persist(prompt); active.current = false; return
      }
      if (job.status === 'failed') {
        setStatus('failed'); setMessage(job.error.message + (visibleWork.current ? ' 上次作品仍可下载。' : ''))
        const prompt = pending.current?.prompt || ''
        pending.current = undefined; persist(prompt); active.current = false; return
      }
      setStatus(job.status)
      setMessage(job.cancellation_requested || cancelled.current ? '正在取消，等待当前步骤停止；不会继续后续生成。' :
        job.status === 'queued' ? '正在排队，请稍候（等待上限10分钟）。' : job.progress || '正在创作并准备乐谱与音频，请稍候（等待上限10分钟）。')
      timer.current = setTimeout(() => { void poll(id, signal, token) }, 1500)
    } catch {
      if (!current(id, signal, token)) return
      if (failures < 2) { timer.current = setTimeout(() => { void poll(id, signal, token, failures + 1) }, 2000); return }
      setStatus('query-error'); setMessage('暂时无法查询结果。点击“恢复当前任务”继续查询，不会另建任务。'); active.current = false
    }
  }

  useEffect(() => {
    const saved = persistent ? loadSession() : null
    const abort = new AbortController(); controller.current = abort
    const token = ++epoch.current
    if (saved) {
      active.current = true; setRestoring(true); setMessage('正在恢复当前任务与作品…')
      setRestoredPrompt(saved.prompt); pending.current = saved.pending
      jobId.current = saved.pending?.id || saved.visibleJobId || null
      void (async () => {
        try {
          if (saved.visibleJobId) {
            try {
              const old = await getGeneration(saved.visibleJobId, abort.signal)
              if (abort.signal.aborted || token !== epoch.current) return
              if (old.status !== 'ready') throw new Error('old unavailable')
              visibleWork.current = old; pendingSource.current = old; setWork(old)
            } catch (error) {
              if (!(error instanceof RequestFailure) || ![404, 409].includes(error.status || 0)) throw error
              if (!saved.pending) {
                saveSession({prompt:saved.prompt}); setStatus('idle'); setMessage('上次临时作品已不可用，请使用已下载文件或重新创作。'); active.current = false; return
              }
              saveSession({prompt:saved.prompt, pending:saved.pending})
            }
          }
          if (saved.pending) {
            // Lookup first. A missing job permits a resend of the same immutable ID.
            try { await getGeneration(saved.pending.id, abort.signal) }
            catch (error) {
              if (!(error instanceof RequestFailure) || error.status !== 404) throw error
              await submitGeneration(saved.pending.prompt, abort.signal, saved.pending.sourceId, saved.pending.id)
            }
            if (abort.signal.aborted || token !== epoch.current) return
            await poll(saved.pending.id, abort.signal, token)
          } else { setStatus(visibleWork.current ? 'ready' : 'idle'); setMessage(visibleWork.current ? '已恢复当前作品。' : ''); active.current = false }
        } catch {
          if (!abort.signal.aborted && token === epoch.current) {
            setStatus('query-error'); setMessage('当前任务暂时无法恢复，请恢复网络后点击“恢复当前任务”。'); active.current = false
          }
        } finally { if (!abort.signal.aborted && token === epoch.current) setRestoring(false) }
      })()
    } else { setRestoring(false) }
    return () => { epoch.current++; abort.abort(); controller.current?.abort(); if (timer.current) clearTimeout(timer.current) }
  }, [])

  async function submitOriginal(signal: AbortSignal, token: number) {
    const submission = pending.current
    if (!submission) return
    try {
      const id = await submitGeneration(submission.prompt, signal, submission.sourceId, submission.id)
      if (!current(submission.id, signal, token)) return
      if (id !== submission.id) throw new RequestFailure('任务编号不一致，请恢复当前任务。', true)
      await poll(id, signal, token)
    } catch (error) {
      if (!current(submission.id, signal, token)) return
      const uncertain = error instanceof RequestFailure && error.uncertain
      setStatus(uncertain ? 'uncertain' : 'failed')
      setMessage(uncertain ? '提交结果暂时无法确认。点击“恢复当前任务”，会找回原任务，不重复生成。' : error instanceof Error ? error.message : '提交失败，请稍后重试。')
      if (!uncertain) { pending.current = undefined; persist(submission.prompt) }
      active.current = false
    }
  }
  async function generate(prompt: string) {
    if (active.current || restoring || status === 'uncertain' || status === 'query-error' || !prompt.trim()) return
    pending.current = { id: crypto.randomUUID(), prompt: prompt.trim(), sourceId: visibleWork.current?.composition_id }
    if (!persist(prompt.trim())) {
      pending.current = undefined; setStatus('failed'); setMessage('浏览器无法保存当前任务编号，请允许此网页使用会话存储后重试；本次未提交生成。'); return
    }
    active.current = true; cancelled.current = false
    controller.current?.abort(); if (timer.current) clearTimeout(timer.current)
    const token = ++epoch.current; const abort = new AbortController(); controller.current = abort
    pendingSource.current = visibleWork.current; jobId.current = pending.current.id
    setStatus('submitting'); setMessage('正在提交描述…')
    await submitOriginal(abort.signal, token)
  }
  async function resume() {
    if (active.current || !jobId.current) return
    active.current = true; controller.current?.abort(); if (timer.current) clearTimeout(timer.current)
    const abort = new AbortController(); controller.current = abort; const token = ++epoch.current
    setStatus('running'); setMessage('正在恢复原任务…')
    try {
      // Restore the old visible result too if the initial recovery was interrupted.
      const saved = persistent ? loadSession() : null
      if (!visibleWork.current && saved?.visibleJobId) {
        try {
          const old = await getGeneration(saved.visibleJobId, abort.signal)
          if (abort.signal.aborted || token !== epoch.current) return
          if (old.status !== 'ready') throw new Error('old unavailable')
          visibleWork.current = old; pendingSource.current = old; setWork(old)
        } catch (error) {
          if (!(error instanceof RequestFailure) || ![404,409].includes(error.status || 0) || !pending.current) throw error
          saveSession({prompt:saved.prompt,pending:pending.current})
        }
      }
      await getGeneration(jobId.current, abort.signal)
      if (!abort.signal.aborted && token === epoch.current) await poll(jobId.current, abort.signal, token)
    } catch (error) {
      if (abort.signal.aborted || token !== epoch.current) return
      if (error instanceof RequestFailure && error.status === 404 && pending.current) { await submitOriginal(abort.signal, token); return }
      setStatus('query-error'); setMessage('仍无法恢复原任务，请确认本地服务与网络已启动。'); active.current = false
    }
  }
  async function cancel() {
    if (!jobId.current || !pending.current) return
    try {
      await cancelGeneration(jobId.current, new AbortController().signal)
      cancelled.current = true
      setMessage('已请求取消，等待当前步骤停止；已发生的费用仍会计入预算。')
      if (!active.current) void resume()
    } catch { setMessage('取消请求未确认，请恢复连接后再次取消；原任务可能仍在运行。') }
  }
  const busy = restoring || ['submitting', 'queued', 'running'].includes(status)
  return { status, message, work, busy, generate, resume, cancel, restoredPrompt, canCancel: !!pending.current }
}
