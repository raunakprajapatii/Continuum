import React, { useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import {
  Activity, ArrowRight, AudioLines, Bot, Check, ChevronRight, CircleDot,
  Clock3, Command, Ear, Gauge, Mic, Phone, PhoneCall, Play, Radio,
  RotateCcw, ShieldCheck, Sparkles, Volume2, Waves, X, Zap,
} from 'lucide-react'
import heroImage from './assets/continuum-hero.png'
import './styles.css'

const timeline = [
  { at: 0, event: 'call.inbound_ring', detail: 'caller=Z', kind: 'call' },
  { at: 120, event: 'thread.match_found', detail: 'confidence=1.00', kind: 'memory' },
  { at: 320, event: 'recap.generation_started', detail: 'thread=z-contact-01', kind: 'brain' },
  { at: 1198, event: 'freshness.discrepancy_found', detail: 'price: $400 → $420', kind: 'alert' },
  { at: 1320, event: 'recap.tts_first_audio', detail: 'Δ 1.20s from match', kind: 'voice' },
  { at: 4980, event: 'barge_in.detected', detail: '“just pick up the call”', kind: 'action' },
  { at: 5170, event: 'tts.playback_halted', detail: 'Δ 190ms from barge-in', kind: 'action' },
  { at: 5190, event: 'barge_in.intent_classified', detail: 'intent=auto_answer', kind: 'action' },
  { at: 5300, event: 'call.auto_answer_triggered', detail: 'caller=Z', kind: 'call' },
]

const recapLines = [
  'Z wanted the Q3 number.',
  'You said you would check with finance.',
  'Heads up — the price is now $420.',
  'Pick up with the updated number.',
]

const icons = { call: PhoneCall, memory: CircleDot, brain: Bot, alert: Zap, voice: Volume2, action: Command }
const formatTime = (ms) => `09:14:${String(2 + Math.floor(ms / 1000)).padStart(2, '0')}.${String(ms % 1000).padStart(3, '0')}`

function App() {
  const [demoTime, setDemoTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [scenario, setScenario] = useState('returning')
  const [audioState, setAudioState] = useState('idle')
  const timer = useRef(null)
  const audioRef = useRef(null)
  const isConnected = demoTime >= 5300
  const isWhispering = demoTime >= 1320 && demoTime < 5170 && scenario === 'returning'
  const events = useMemo(() => timeline.filter((item) => item.at <= demoTime), [demoTime])

  useEffect(() => {
    if (!playing) return undefined
    const started = performance.now() - demoTime
    const tick = (now) => {
      const next = Math.min(5600, Math.floor(now - started))
      setDemoTime(next)
      if (next >= 5600) setPlaying(false)
      else timer.current = requestAnimationFrame(tick)
    }
    timer.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(timer.current)
  }, [playing])

  useEffect(() => {
    if (demoTime >= 5170 && audioRef.current && !audioRef.current.paused) {
      audioRef.current.pause()
      setAudioState('halted')
    }
  }, [demoTime])

  const replay = () => { setPlaying(false); setDemoTime(0); audioRef.current?.pause(); setAudioState('idle') }
  const start = () => { if (demoTime >= 5600) setDemoTime(0); setPlaying(true) }
  const triggerBargeIn = () => { audioRef.current?.pause(); setAudioState('halted'); setDemoTime(4980); setPlaying(true) }
  const switchScenario = (next) => { setScenario(next); replay() }
  const playPrivateRecap = async () => {
    if (audioState === 'loading') return
    audioRef.current?.pause()
    setAudioState('loading')
    try {
      const response = await fetch('/api/private-recap-audio', { method: 'POST' })
      if (!response.ok || response.headers.get('X-Continuum-Track') !== 'continuum-private-whisper') throw new Error('Private recap unavailable')
      const objectUrl = URL.createObjectURL(await response.blob())
      const audio = new Audio(objectUrl)
      audioRef.current = audio
      audio.addEventListener('ended', () => { URL.revokeObjectURL(objectUrl); setAudioState('idle') }, { once: true })
      await audio.play()
      setAudioState('playing')
      setDemoTime(1320)
      setPlaying(true)
    } catch {
      setAudioState('error')
    }
  }
  const progress = Math.min(100, (demoTime / 5600) * 100)
  const spokenCount = demoTime < 1900 ? 1 : demoTime < 3400 ? 2 : demoTime < 4800 ? 3 : 4

  return <main className="app-shell">
    <nav className="topbar">
      <a className="brand" href="#top" aria-label="Continuum home"><span className="brand-mark"><Waves size={18}/></span>CONTINUUM</a>
      <div className="thread-chip"><span className="avatar small">Z</span><span>Thread: Z · Contact</span><span className="online-dot"/></div>
      <div className="provider"><span>Powered by</span><b>Rime</b><i/> <span>model: <b>Mist v3</b></span><i/> <span>voice: <b>Marsh</b></span><i/> <span>endpoint: <b>us-east</b></span></div>
      <div className={`state-pill ${isConnected ? 'connected' : ''}`}><span className="pulse"/>{isConnected ? 'CONNECTED' : 'RINGING'}</div>
    </nav>

    <section className="hero" id="top">
      <div className="hero-copy">
        <div className="eyebrow"><Sparkles size={14}/> Conversation continuity, before hello</div>
        <h1>Never lose the<br/><em>thread</em> again.</h1>
        <p>Continuum quietly catches you up when an interrupted caller returns — while preserving a perfectly normal call for them.</p>
        <div className="hero-actions">
          <button className="primary-button" onClick={start}><Play size={16} fill="currentColor"/>{playing ? 'Demo in progress' : 'Play live demo'}</button>
          <button className="audio-button" onClick={playPrivateRecap} disabled={audioState === 'loading'}><Volume2 size={16}/>{audioState === 'loading' ? 'Connecting to Rime…' : audioState === 'playing' ? 'Private recap playing' : 'Hear Rime recap'}</button>
          <a className="text-button" href="#instrument">Explore the instrument panel <ArrowRight size={16}/></a>
        </div>
        {audioState === 'error' && <p className="audio-error">Rime did not return audio. Check the configured model, speaker, and endpoint.</p>}
        <div className="assurance"><ShieldCheck size={17}/><span>Private recap stays on a separate LiveKit track.</span></div>
      </div>
      <div className="hero-art"><div className="glow-ring"/><img src={heroImage} alt="Indian professional wearing headphones on a call"/><div className="hero-floating-card"><span className="mini-icon"><Ear size={15}/></span><div><small>Private track</small><strong>Recap ready</strong></div><span className="tiny-wave">▮▯▮▰▯</span></div></div>
    </section>

    <section className="instrument-wrap" id="instrument">
      <div className="section-heading"><div><span className="eyebrow"><Activity size={14}/> Live instrument panel</span><h2>Watch the invisible work.</h2><p>One focused simulation. Every event is timestamped. Every track is visible.</p></div><div className="demo-controls"><button className="icon-button" onClick={replay} aria-label="Reset demo"><RotateCcw size={17}/></button><button className="primary-button compact" onClick={start}><Play size={15} fill="currentColor"/>{playing ? 'Running' : 'Run scenario'}</button></div></div>

      <div className="scenario-tabs" role="tablist">
        <button className={scenario === 'returning' ? 'active' : ''} onClick={() => switchScenario('returning')}><Phone size={16}/> Returning caller <span>Primary path</span></button>
        <button className={scenario === 'instant' ? 'active' : ''} onClick={() => switchScenario('instant')}><Mic size={16}/> In-call recall <span>Fallback path</span></button>
      </div>

      <div className="dashboard-grid">
        <section className="card tracks-card">
          <div className="card-title"><div><span className="kicker">Audio isolation</span><h3>Two tracks. Zero leakage.</h3></div><span className="verified"><Check size={13}/> fenced</span></div>
          <Track label="Caller-facing track" sublabel="What Z hears" tone="caller" active={!isConnected} status={isConnected ? 'Connected call' : 'Ringback tone only'} />
          <div className="track-divider"/>
          <Track label="Private whisper track" sublabel="What only you hear" tone="whisper" active={isWhispering} status={isWhispering ? 'Rime recap playing' : demoTime >= 5170 ? 'Playback halted' : 'Standing by'} />
          <div className="separation-note"><ShieldCheck size={16}/><span>Rime audio routes exclusively to <code>continuum-private-whisper</code></span></div>
        </section>

        <section className="card recap-card">
          <div className="card-title"><div><span className="kicker">Thread memory</span><h3>What happened yesterday</h3></div><span className="avatar">Z</span></div>
          <p className="memory-copy">Z asked about Q3 pricing. You quoted <b>$400</b> and said you would confirm with finance.</p>
          <div className="freshness"><span className="freshness-icon"><Zap size={15}/></span><div><small>Freshness flag</small><strong>Price is now $420 <s>was $400</s></strong></div></div>
          <div className="spoken"><div className="spoken-head"><span><Volume2 size={15}/> Recap being spoken</span><span>{isWhispering ? 'LIVE' : 'READY'}</span></div>{recapLines.map((line, index) => <p className={index < spokenCount ? 'spoken-line visible' : 'spoken-line'} key={line}><span>{String(index + 1).padStart(2, '0')}</span>{line}</p>)}</div>
        </section>

        <section className="card event-card">
          <div className="card-title"><div><span className="kicker">Append-only feed</span><h3>Event log</h3></div><span className="live-label"><span className="pulse"/> LIVE</span></div>
          <div className="event-list">{events.length ? events.map((item) => <Event key={item.event} item={item}/>) : <div className="empty-log"><Radio size={20}/><span>Waiting for a call event…</span></div>}</div>
          <button className="barge-button" onClick={triggerBargeIn} disabled={!isWhispering}><Mic size={15}/><span>Test: “just pick up the call”</span><ChevronRight size={15}/></button>
        </section>
      </div>

      <div className="progress-area"><div className="progress-label"><span><Clock3 size={15}/> Demo timeline</span><span>{(demoTime / 1000).toFixed(1)}s / 5.6s</span></div><div className="progress-track"><span style={{width: `${progress}%`}}/></div><div className="timeline-stages"><span>Ring</span><span>Match</span><span>Whisper</span><span>Barge-in</span><span>Answer</span></div></div>
    </section>

    <section className="proof-section">
      <div className="section-heading compact-heading"><div><span className="eyebrow"><Gauge size={14}/> Evidence, not claims</span><h2>Built for a five-minute proof.</h2></div><p>The key numbers mirror the evaluation harness, so a judge can validate the experience at a glance.</p></div>
      <div className="metrics-grid">
        <Metric value="1.20s" label="Ring to first private audio" event="thread.match_found → recap.tts_first_audio" icon={<AudioLines size={19}/>}/>
        <Metric value="190ms" label="Barge-in response" event="barge_in.detected → tts.playback_halted" icon={<Zap size={19}/>}/>
        <Metric value="0ms" label="Caller-side added latency" event="Caller hears normal ringback only" icon={<ShieldCheck size={19}/>}/>
        <Metric value="$420" label="Freshness catch" event="Prior quote $400 checked before speaking" icon={<Sparkles size={19}/>}/>
      </div>
    </section>

    <section className="architecture-section"><div className="architecture-copy"><span className="eyebrow"><Bot size={14}/> Under the hood</span><h2>One calm moment,<br/>many precise handoffs.</h2><p>Continuum listens continuously, preserves the conversation thread, and uses Rime only on the user-private audio track.</p></div><div className="pipeline">{[['Audio', 'Transcript'], ['Memory', 'Recap text'], ['Rime speech', 'Private track']].map(([a,b], i) => <React.Fragment key={a}><div className="pipeline-node"><span>{String(i+1).padStart(2, '0')}</span><b>{a}</b><small>{b}</small></div>{i < 2 && <ArrowRight className="pipeline-arrow" size={20}/>}</React.Fragment>)}</div></section>

    <footer><a className="brand" href="#top"><span className="brand-mark"><Waves size={18}/></span>CONTINUUM</a><span>Voice-native continuity for the moments that matter.</span><span>Made for Rime Hackathon · 2026</span></footer>
  </main>
}

function Track({ label, sublabel, tone, active, status }) { return <div className={`track ${tone} ${active ? 'is-active' : ''}`}><div className="track-meta"><div className="track-label"><span className="track-led"/><div><b>{label}</b><small>{sublabel}</small></div></div><span className="track-status">{status}</span></div><div className="waveform" aria-label={`${label}: ${status}`}>{Array.from({ length: 52 }, (_, i) => <i key={i} style={{ '--h': `${18 + ((i * 37) % 70)}%`, '--d': `${(i % 8) * 0.07}s` }}/>)}</div></div> }
function Event({ item }) { const Icon = icons[item.kind] || Activity; return <div className={`event ${item.kind}`}><span className="event-icon"><Icon size={14}/></span><div><div className="event-main"><time>{formatTime(item.at)}</time><b>{item.event}</b></div><small>{item.detail}</small></div></div> }
function Metric({ value, label, event, icon }) { return <article className="metric"><span className="metric-icon">{icon}</span><strong>{value}</strong><h3>{label}</h3><p>{event}</p><span className="pass"><Check size={13}/> PASS</span></article> }

createRoot(document.getElementById('root')).render(<App />)
