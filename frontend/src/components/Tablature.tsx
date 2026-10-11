import { useEffect, useRef, useState } from 'react'
import { AlphaTabApi } from '@coderline/alphatab'

type Props = { alphatex: string; onReady?: () => void; onError?: () => void; print?: boolean }

export function Tablature({ alphatex, onReady, onError, print = false }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const ready = useRef(onReady)
  ready.current = onReady
  const failed = useRef(onError)
  failed.current = onError
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')

  useEffect(() => {
    if (!host.current) return
    setState('loading')
    let disposed = false
    const api = new AlphaTabApi(host.current, {
      core: { fontDirectory: '/font/', enableLazyLoading: false, useWorkers: false, engine: 'svg' },
      player: { enablePlayer: false },
      display: { scale: 1, ...(print ? { barsPerRow: 2 } : {}), resources: { secondaryGlyphColor: '#312b26' } },
    })
    const reportError = () => { if (!disposed) { setState('error'); failed.current?.() } }
    const timer = window.setTimeout(reportError, 30000)
    api.error.on(() => { clearTimeout(timer); reportError() })
    api.postRenderFinished.on(() => {
      if (!disposed) { clearTimeout(timer); setState('ready'); ready.current?.() }
    })
    try { api.tex(alphatex) } catch { clearTimeout(timer); reportError() }
    return () => { disposed = true; clearTimeout(timer); api.destroy() }
  }, [alphatex, print])

  return <section className="tablature" data-render-state={state}>
    {state === 'loading' && <p role="status">正在排谱…</p>}
    {state === 'error' && <p role="alert" className="error">谱面加载失败，请刷新后重试。</p>}
    <div className="tablature-scroll"><div ref={host} /></div>
  </section>
}
