import { useEffect, useRef, useState } from 'react'
import type { ReadyWork } from '../api/generation'

function timeLabel(seconds: number) {
  const value = Number.isFinite(seconds) && seconds >= 0 ? Math.floor(seconds) : 0
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`
}

export default function AudioPlayer({ work }: { work: ReadyWork | null }) {
  const media = useRef<HTMLAudioElement>(null)
  const alive = useRef(true)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [status, setStatus] = useState<'idle' | 'loading' | 'playing' | 'paused' | 'ended' | 'error'>('idle')
  const [position, setPosition] = useState(0)
  const [duration, setDuration] = useState(work?.audio_seconds || 0)
  const clearTimer = () => { if (timer.current) { clearTimeout(timer.current); timer.current = null } }
  const fail = () => { clearTimer(); if (alive.current) { media.current?.pause(); setStatus('error') } }

  useEffect(() => {
    alive.current = true
    const audio = media.current
    if (audio && work) audio.src = work.audio_url
    setStatus('idle'); setPosition(0); setDuration(work?.audio_seconds || 0)
    return () => {
      alive.current = false
      clearTimer()
      if (audio) { audio.pause(); audio.removeAttribute('src'); audio.load() }
    }
  }, [work?.audio_url, work?.audio_seconds])

  function toggle() {
    const audio = media.current
    if (!audio || !work) return
    if (status === 'playing') { audio.pause(); return }
    if (status === 'loading') return
    if (status === 'error') { audio.load(); setPosition(0) }
    if (audio.ended) audio.currentTime = 0
    setStatus('loading')
    clearTimer()
    timer.current = setTimeout(fail, 15000)
    void audio.play().catch(fail)
  }
  const playing = status === 'playing'
  return <section className="creation-panel audio-panel" aria-label="试听音频">
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M4 14v-3a8 8 0 0 1 16 0v3" /><rect x="3" y="12" width="4" height="8" rx="2" /><rect x="17" y="12" width="4" height="8" rx="2" /></svg>
    <div className="audio-details"><h2>试听音频</h2><p>合成音频 · {work ? '标准定弦吉他演奏示意' : '作品完成后即可试听'}</p>{work && <><div className="audio-time" role="status" aria-label="播放时间">{timeLabel(position)} / {timeLabel(duration)}{status === 'loading' ? ' · 正在加载…' : playing ? ' · 正在播放' : status === 'paused' ? ' · 已暂停' : status === 'ended' ? ' · 播放结束' : ''}</div><progress className="audio-progress" max={duration || 1} value={Math.min(position, duration)} aria-label="播放进度" />{status === 'error' && <p className="error" role="alert">音频暂时无法播放，请点击“重试试听”。乐谱仍可查看。</p>}</>}</div>
    <button type="button" className="play-button" disabled={!work || status === 'loading'} onClick={toggle} aria-label={!work ? '播放音频（尚无作品）' : status === 'error' ? '重试试听' : playing ? '暂停音频' : '播放音频'} title={status === 'error' ? '重试试听' : playing ? '暂停' : '播放'}>
      <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">{playing ? <><path d="M8 5v14M16 5v14" /></> : <path d="m9 5 11 7-11 7Z" />}</svg>
    </button>
    {work && <audio ref={media} src={work.audio_url} preload="none" onPlaying={() => { clearTimer(); setStatus('playing') }} onPause={() => { clearTimer(); setStatus((current) => current === 'error' ? 'error' : 'paused') }} onEnded={() => { clearTimer(); setStatus('ended') }} onTimeUpdate={(event) => setPosition(event.currentTarget.currentTime)} onLoadedMetadata={(event) => { const length = event.currentTarget.duration; if (Number.isFinite(length) && length > 0) setDuration(length) }} onError={fail} />}
  </section>
}
