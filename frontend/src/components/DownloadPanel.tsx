import { useEffect, useRef, useState } from 'react'
import type { ReadyWork } from '../api/generation'
import { fetchDownload, type DownloadKind } from '../api/download'

function DownloadItem({ work, kind }: { work: ReadyWork | null; kind: DownloadKind }) {
  const [status, setStatus] = useState<'idle' | 'loading' | 'started' | 'error'>('idle')
  const active = useRef<AbortController | null>(null)
  useEffect(() => () => { active.current?.abort(); active.current = null }, [work?.job_id])

  async function download() {
    if (!work || active.current) return
    const controller = new AbortController()
    active.current = controller
    setStatus('loading')
    const timeout = setTimeout(() => controller.abort(), 30000)
    try {
      const { blob, filename } = await fetchDownload(work.job_id, kind, controller.signal)
      if (controller.signal.aborted || active.current !== controller) return
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url; anchor.download = filename
      document.body.appendChild(anchor)
      try { anchor.click() } finally { anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 60000) }
      setStatus('started')
    } catch {
      if (active.current === controller) setStatus('error')
    } finally {
      clearTimeout(timeout)
      if (active.current === controller) active.current = null
    }
  }
  return <div className="download-option">
    <button type="button" className={work ? 'ready-download' : ''} disabled={!work || status === 'loading'} onClick={() => void download()}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5" /></svg>
      {status === 'loading' ? `正在准备 ${kind}…` : status === 'error' ? `重新下载 ${kind}` : `下载 ${kind}`}
    </button>
    <div><p role={status === 'error' ? 'alert' : 'status'} className={status === 'error' ? 'download-error' : ''}>{status === 'error' ? `${kind} 下载失败，请重新下载。` : status === 'started' ? `${kind} 下载已开始，保存位置遵循 Chrome 设置。` : status === 'loading' ? '正在取得当前作品文件…' : work ? '当前作品文件已就绪' : '成功后提供下载文件'}</p><span className="fine-print">{kind === 'MP3' ? '合成音频' : '完整六线谱'}</span></div>
  </div>
}

export default function DownloadPanel({ work }: { work: ReadyWork | null }) {
  return <section className="creation-panel download-panel" aria-labelledby="download-title"><div className="download-heading"><h2 id="download-title">把作品留在本地</h2><span className="fine-print">音频与谱面来自同一作品</span></div><div className="download-options">{(['MP3', 'PDF'] as const).map((kind) => <DownloadItem key={`${work?.job_id || 'empty'}-${kind}`} work={work} kind={kind} />)}</div></section>
}
