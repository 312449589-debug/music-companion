import { useEffect, useRef, useState } from 'react'
import AudioPlayer from '../components/AudioPlayer'
import DownloadPanel from '../components/DownloadPanel'
import { Tablature } from '../components/Tablature'
import { useGeneration } from '../hooks/useGeneration'
import type { ReadyWork } from '../api/generation'

const examples = [
  { label: '温暖安静', prompt: '温暖安静的旋律，适合夜晚独自弹奏。简单的和声托住柔和的旋律，速度舒缓。' },
  { label: '轻快明亮', prompt: '轻快明亮的旋律，像清晨的阳光。简单的和声搭配活泼的旋律，听起来轻松愉快。' },
  { label: '略带忧伤', prompt: '略带忧伤的旋律，像回忆一段往事。简单的和声搭配温柔的旋律，速度从容。' },
]

type IconName = 'music' | 'sparkle' | 'headphones' | 'download' | 'info' | 'play'
function Icon({ name }: { name: IconName }) {
  const paths: Record<IconName, React.ReactNode> = {
    music: <><path d="M9 18V5l11-2v13M9 9l11-2" /><ellipse cx="6" cy="18" rx="3" ry="2" /><ellipse cx="17" cy="16" rx="3" ry="2" /></>,
    sparkle: <><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z" /><path d="M21 2v4M19 4h4" /></>,
    headphones: <><path d="M4 14v-3a8 8 0 0 1 16 0v3" /><rect x="3" y="12" width="4" height="8" rx="2" /><rect x="17" y="12" width="4" height="8" rx="2" /></>,
    download: <><path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5" /></>,
    info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6m0-10v1" /></>,
    play: <path d="m9 5 11 7-11 7Z" />,
  }
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}

export default function CreationPage({ initialWork = null }: { initialWork?: ReadyWork | null }) {
  const [prompt, setPrompt] = useState(initialWork?.composition.prompt || '')
  const output = useRef<HTMLDivElement>(null)
  const generation = useGeneration(initialWork, () => {
    // Stop the old media before the shared visible result switches.
    output.current?.querySelectorAll('audio').forEach((audio) => { audio.pause(); audio.currentTime = 0 })
  })
  useEffect(() => { if (generation.restoredPrompt !== null) setPrompt(generation.restoredPrompt) }, [generation.restoredPrompt])
  const [scoreError, setScoreError] = useState(false)
  const [scoreAttempt, setScoreAttempt] = useState(0)
  const hasPrompt = prompt.trim().length > 0

  return (
    <div className="creation-page">
      <header className="creation-header">
        <div className="creation-brand"><span className="brand-mark"><Icon name="music" /></span><div><strong>音乐伙伴</strong><span>Music Companion</span></div></div>
        <span className="entry-note">免登录 · 直接创作</span>
      </header>
      <main>
        <div className="creation-hero"><h1>把你的音乐想法，变成可以亲手弹奏的小作品</h1><p>为吉他指弹学习者而做，教师也可使用同一页面。只需描述听感，余下的交给旋律。</p></div>
        <div className="creation-grid">
          <aside className="creation-input-column">
            <form className="creation-panel prompt-panel" onSubmit={(event) => {
              event.preventDefault()
              void generation.generate(prompt)
            }}>
              <label htmlFor="music-prompt">你想弹奏怎样的旋律？</label>
              <p className="muted">从一个听感、一种心情开始。</p>
              <textarea id="music-prompt" value={prompt} maxLength={1000} disabled={generation.busy} onChange={(event) => setPrompt(event.target.value)} placeholder="描述你想要的听感，例如：温暖安静的旋律，适合夜晚弹奏。" aria-describedby="prompt-hint prompt-feedback" />
              <p className="example-heading">试试这些听感</p>
              <div className="example-buttons">{examples.map((example) => <button key={example.label} type="button" disabled={generation.busy} onClick={() => setPrompt(example.prompt)}>{example.label}</button>)}</div>
              {generation.work && <p className="fine-print">重新生成会保持 {generation.work.composition.tempo_bpm} BPM 和 {generation.work.composition.key_signature} 调性。</p>}
              <p id="prompt-hint" className="fine-print">示例点击只填入可编辑描述，不自动生成。</p>
              <button className="generate-button" type="submit" disabled={!hasPrompt || generation.busy || generation.status === 'query-error' || generation.status === 'uncertain'}><Icon name="sparkle" />{generation.busy ? '正在生成…' : generation.status === 'failed' ? (generation.work ? '重试重新生成' : '重试生成') : generation.work ? '重新生成整段' : '生成指弹作品'}</button>
              <p id="prompt-feedback" className="prompt-feedback" role="status">{generation.message || (!hasPrompt ? '请先输入描述，或选择一个示例。' : '可以继续修改描述，准备好后点击生成。')}</p>
              {(generation.status === 'query-error' || generation.status === 'uncertain') && <button className="query-retry" type="button" onClick={() => void generation.resume()}>恢复当前任务</button>}
              {generation.canCancel && <button className="query-retry" type="button" onClick={() => void generation.cancel()}>取消生成</button>}
              <p className="fine-print input-footer">标准定弦 · 简单和声＋旋律<br />音频时长不超过1分钟</p>
            </form>
            <div className="creation-tip"><Icon name="info" /><div><strong>准备好就开始创作</strong><p>输入描述，或先选一个示例再修改。</p></div></div>
            <div className="writing-tip"><strong>让想法简单一点</strong><p>描述心情、氛围或旋律的感觉即可。仅支持标准定弦吉他，不支持打板。</p></div>
          </aside>
          <div ref={output} className="creation-output-column" key={generation.work?.composition_id || 'empty'}>
            <section className="creation-panel work-panel" aria-labelledby="work-title"><h2 id="work-title">你的指弹作品</h2>{generation.work ? <div className="ready-work">{generation.busy && <p role="status" className="previous-work-note">正在生成新作品，当前显示上次作品，文件仍可下载。</p>}{generation.status === 'failed' && <p role="status" className="previous-work-note">新作品未完成，已保留上次作品。</p>}<h3>{generation.work.composition.title}</h3><p className="work-metadata">{generation.work.composition.tempo_bpm} BPM · {generation.work.composition.key_signature} · 标准定弦 · 音频 {generation.work.audio_seconds.toFixed(1)} 秒</p><Tablature key={scoreAttempt} alphatex={generation.work.alphatex} onError={() => setScoreError(true)} onReady={() => setScoreError(false)} />{scoreError && <div role="alert" className="error">作品已生成，谱面暂时无法显示。<button type="button" className="query-retry" onClick={() => { setScoreError(false); setScoreAttempt((attempt) => attempt + 1) }}>重试显示谱面</button></div>}<p className="fine-print">作品编号：{generation.work.composition_id}</p></div> : <div className="empty-work"><span className="empty-icon"><Icon name="music" /></span><h3>一段小作品，从这里开始</h3><p>在左侧描述你想要的听感。创作成功后，<br />这里会显示完整六线谱，供你试听与下载。</p><span className="fine-print">{generation.busy ? '作品正在准备中' : '还没有作品'}</span></div>}</section>
            <AudioPlayer work={generation.work} />
            <DownloadPanel work={generation.work} />
          </div>
        </div>
      </main>
      <footer className="creation-footer">AI创作 · 标准定弦指弹吉他</footer>
    </div>
  )
}
