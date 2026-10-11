import { useEffect, useState } from 'react'
import { Tablature } from '../components/Tablature'
import type { Composition } from '../types/composition'

type PrintData = { composition: Composition; alphatex: string }
declare global {
  interface Window {
    __PRINT_DATA__?: PrintData
    __PDF_STATUS__?: 'loading' | 'ready' | 'error'
  }
}

export default function PrintPage() {
  const [data, setData] = useState<PrintData | null>(() => {
    window.__PDF_STATUS__ = 'loading'
    return window.__PRINT_DATA__ ?? null
  })
  const [error, setError] = useState(false)
  useEffect(() => {
    if (window.__PRINT_DATA__) return
    fetch('/diagnostics/tablature.json').then(r => {
      if (!r.ok) throw new Error('missing')
      return r.json() as Promise<PrintData[]>
    }).then(examples => {
      setData(examples[new URLSearchParams(window.location.search).get('example') === 'long' ? 1 : 0])
    }).catch(() => { setError(true); window.__PDF_STATUS__ = 'error' })
  }, [])
  return <main className="print-shell">
    <p className="print-brand">音乐伙伴 · 标准定弦指弹谱</p>
    {error && <p role="alert">打印数据加载失败</p>}
    {data && <>
      <p>{data.composition.tempo_bpm} BPM · {data.composition.key_signature} ·
        共 {data.composition.measures.length} 小节</p>
      <p>作品编号：{data.composition.composition_id}</p>
      <Tablature alphatex={data.alphatex} print
        onReady={() => { window.__PDF_STATUS__ = 'ready' }}
        onError={() => { window.__PDF_STATUS__ = 'error' }} />
      <p className="print-end">全曲结束 · {data.composition.measures.length} 小节</p>
    </>}
  </main>
}
