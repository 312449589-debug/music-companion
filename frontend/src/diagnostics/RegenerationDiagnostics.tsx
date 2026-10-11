import { useEffect, useState } from 'react'
import CreationPage from '../pages/CreationPage'
import { getGeneration } from '../api/generation'
import type { ReadyWork } from '../api/generation'

// Available only on the dedicated diagnostic server; the regular homepage has no fault controls.
export default function RegenerationDiagnostics() {
  const [source, setSource] = useState<ReadyWork | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const abort = new AbortController()
    async function load() {
      try {
        const response = await fetch('/diagnostics/regeneration-source', { signal: abort.signal })
        if (!response.ok) throw new Error('请启动整段重新生成诊断服务。')
        const { job_id: seedId } = await response.json()
        const id = new URLSearchParams(window.location.search).get('job') || seedId
        if (typeof id !== 'string' || !/^[0-9a-f-]{36}$/.test(id)) throw new Error('诊断作品编号无效')
        const result = await getGeneration(id, abort.signal)
        if (result.status !== 'ready') throw new Error('原真实作品尚未就绪。')
        if (!abort.signal.aborted) setSource(result)
      } catch { if (!abort.signal.aborted) setError('无法读取原真实作品，请确认诊断服务已启动。') }
    }
    void load()
    return () => abort.abort()
  }, [])
  if (error) return <main className="diagnostic-shell"><p role="alert">{error}</p></main>
  if (!source) return <main className="diagnostic-shell"><p role="status">正在读取原真实作品…</p></main>
  return <CreationPage initialWork={source} />
}
