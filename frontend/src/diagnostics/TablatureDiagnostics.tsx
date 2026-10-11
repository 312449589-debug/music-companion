import { useEffect, useState } from 'react'
import { Tablature } from '../components/Tablature'
import type { Composition } from '../types/composition'

type Example = { name: string; composition: Composition; alphatex: string }

export default function TablatureDiagnostics() {
  const [examples, setExamples] = useState<Example[]>([])
  const [selected, setSelected] = useState(0)
  const [error, setError] = useState('')
  useEffect(() => {
    fetch('/diagnostics/tablature.json').then(r => {
      if (!r.ok) throw new Error('诊断数据加载失败')
      return r.json() as Promise<Example[]>
    }).then(setExamples).catch(() => setError('诊断数据加载失败，请重新构建前端。'))
  }, [])
  const example = examples[selected]
  return <main className="diagnostic-shell">
    <p className="eyebrow">音乐伙伴 · 排谱诊断</p>
    <h1>六线谱检查</h1>
    <p>固定诊断样例，非 AI 生成作品。此页面不提供音乐创作或试听。</p>
    {error && <p role="alert" className="error">{error}</p>}
    <nav className="diagnostic-switch" aria-label="选择诊断样例">
      {examples.map((item, index) => <button key={item.name} aria-pressed={selected === index}
        onClick={() => setSelected(index)}>{item.name}</button>)}
    </nav>
    {example && <>
      <p>{example.composition.tempo_bpm} BPM · {example.composition.key_signature} · 标准定弦 ·
        共 {example.composition.measures.length} 小节</p>
      <p>核对节奏：旋律每拍一音，低音每两拍一音，同时弹奏。</p>
      <Tablature key={example.name} alphatex={example.alphatex} />
      <p className="diagnostic-end">全部谱面结束 · {example.composition.measures.length} 小节</p>
      <details><summary>核对原始音乐数据和排谱文本</summary>
        <pre>{JSON.stringify(example.composition, null, 2)}</pre><pre>{example.alphatex}</pre>
      </details>
    </>}
  </main>
}
