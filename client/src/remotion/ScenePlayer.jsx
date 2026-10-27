import { useEffect, useMemo, useRef, useState } from 'react'
import { Player } from '@remotion/player'
import { LessonScene } from './Scene'

const FPS = 30
const seconds = t => { const [h, m, s] = t.split(':'); return Number(h) * 3600 + Number(m) * 60 + Number(s) }

// WebVTT cues are written one per narrated utterance, in order (server production.py).
export function parseCues(vtt, utterances = []) {
  const cues = []
  for (const block of vtt.split(/\r?\n\r?\n/)) {
    const lines = block.split(/\r?\n/), timing = lines.findIndex(x => x.includes('-->'))
    if (timing < 0) continue
    const [start, end] = lines[timing].split('-->').map(x => seconds(x.trim()))
    const text = new DOMParser().parseFromString(lines.slice(timing + 1).join(' '), 'text/html').documentElement.textContent
    cues.push({ start, end, text, step: utterances[cues.length]?.visual_step ?? 0 })
  }
  return cues
}

// The parent re-sends the same scene as a new object after every progress save and
// re-signs URLs every few minutes; neither may restart playback (the parent keys by clip).
export function ScenePlayer({ scene, audioUrl, captionUrl, duration, index, total, startAt = 0, speed = 1, autoPlay = false, onProgress, onEnded }) {
  const player = useRef(null), [cues, setCues] = useState(null), last = useRef(0), seeked = useRef(false)
  // ponytail: first signed URL kept for the scene; a pause longer than its expiry may need a reload.
  const [audio] = useState(audioUrl), [captions] = useState(captionUrl), [shown] = useState(scene)
  useEffect(() => {
    let active = true
    // Without captions the visual still plays, advancing on utterance order alone.
    const fallback = () => (shown.utterances || []).map((u, i, all) => ({ start: duration * i / all.length, end: duration * (i + 1) / all.length, text: u.text, step: u.visual_step }))
    if (!captions) { setCues(fallback()); return }
    fetch(captions).then(r => r.ok ? r.text() : Promise.reject()).then(text => { if (active) setCues(parseCues(text, shown.utterances)) })
      .catch(() => { if (active) setCues(fallback()) })
    return () => { active = false }
  }, [captions, shown, duration])
  const props = useMemo(() => ({ scene: shown, cues: cues || [], audio, index, total }), [shown, cues, audio, index, total])
  useEffect(() => {
    const p = player.current
    if (!p || !cues) return
    if (!seeked.current) { seeked.current = true; if (startAt > 0) p.seekTo(Math.floor(startAt * FPS)) }
    const now = () => p.getCurrentFrame() / FPS
    const tick = () => { if (Date.now() - last.current > 5000) { last.current = Date.now(); onProgress?.(now()) } }
    const pause = () => onProgress?.(now())
    const ended = () => onEnded?.(now())
    p.addEventListener('frameupdate', tick); p.addEventListener('pause', pause); p.addEventListener('ended', ended)
    return () => { p.removeEventListener('frameupdate', tick); p.removeEventListener('pause', pause); p.removeEventListener('ended', ended) }
  }, [cues]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!cues) return <div className="media-loading">Preparing this scene…</div>
  return <Player ref={player} component={LessonScene} inputProps={props} durationInFrames={Math.max(1, Math.ceil(duration * FPS))}
    fps={FPS} compositionWidth={1280} compositionHeight={720} controls clickToPlay showVolumeControls allowFullscreen autoPlay={autoPlay}
    playbackRate={speed} acknowledgeRemotionLicense style={{ width: '100%', aspectRatio: '16 / 9', borderRadius: 12, overflow: 'hidden' }} />
}
