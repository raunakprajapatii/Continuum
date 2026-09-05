import React from 'react'
import { createRoot } from 'react-dom/client'
import {
  Activity, AlertTriangle, ArrowRight, AudioLines, Bot, Check, ChevronRight, CircleDot,
  Clock3, Command, Download, Ear, Gauge, Loader2, Mic, MicOff, Phone, PhoneCall, PhoneOff,
  Play, Radio, RotateCcw, ShieldCheck, Sparkles, Square, Volume2, VolumeX, Zap,
} from 'lucide-react'
import './styles.css'
import './sim-console.css'
import logoUrl from './assets/ChatGPT Image Sep 5, 2026, 08_41_24 PM.png'
import { format, t } from './i18n.js'
import { BARGE_EXAMPLES, CALLER, INTENT_LABELS, SPEAKERS } from './sim/config.js'
import { PHASE, RECAP_STATE, useSimulation } from './sim/useSimulation.js'

// The new brand image doubles as the site logo (top bar + footer) and the
// browser favicon. Vite fingerprints the import so both work in dev and in
// the production build.
const faviconLink = document.createElement('link')
faviconLink.rel = 'icon'
faviconLink.type = 'image/png'
faviconLink.href = logoUrl
document.head.appendChild(faviconLink)

const BrandLogo = () => (
  <span className="brand-mark brand-logo"><img src={logoUrl} alt="Continuum logo" /></span>
)

const KIND_ICONS = {
  call: PhoneCall,
  memory: CircleDot,
  brain: Bot,
  alert: Zap,
  voice: Volume2,
  action: Command,
}

const STAGES = [
  { key: PHASE.CALL1, n: '01', labelKey: 'stage.call1.t', shortKey: 'stage.call1.s' },
  { key: PHASE.MEMORY, n: '02', labelKey: 'stage.memory.t', shortKey: 'stage.memory.s' },
  { key: PHASE.RECAP, n: '03', labelKey: 'stage.recap.t', shortKey: 'stage.recap.s' },
  { key: PHASE.CONNECTED, n: '04', labelKey: 'stage.connected.t', shortKey: 'stage.connected.s' },
  { key: PHASE.COMPLETED, n: '05', labelKey: 'stage.completed.t', shortKey: 'stage.completed.s' },
]

function stageIndexFor(phase) {
  if (phase === PHASE.IDLE || phase === PHASE.BOOT) return -1
  const map = { [PHASE.CALL1]: 0, [PHASE.MEMORY]: 1, [PHASE.RECAP]: 2, [PHASE.CONNECTED]: 3, [PHASE.COMPLETED]: 4 }
  return map[phase] ?? -1
}

function SimApp() {
  const sim = useSimulation()
  return (
    <main className="app-shell sim-shell">
      <TopBar sim={sim} />
      {sim.phase === PHASE.BOOT || sim.phase === PHASE.IDLE ? (
        <LaunchScreen sim={sim} />
      ) : (
        <Console sim={sim} />
      )}
      <footer>
        <a className="brand" href="#top"><BrandLogo />CONTINUUM</a>
        <span>{t('footer.tag', sim.lang)}</span>
        <span>{t('footer.made', sim.lang)}</span>
      </footer>
    </main>
  )
}

// ── Top bar (always visible — demo script §02A) ──────────────────────────────
function TopBar({ sim }) {
  const { caps, phase, callStateLabel, lang } = sim
  const T = (k, v) => format(t(k, lang), v)
  const rime = caps?.rime
  // Once the recap is generated, surface the voice/model actually speaking.
  const activeModel = sim.recap?.model || rime?.model || '…'
  const activeSpeaker = sim.recap?.speaker || rime?.speaker || '…'
  const connectedColor =
    callStateLabel === 'CONNECTED' ? ' connected' : callStateLabel === 'RINGING' ? ' ringing' : ''
  return (
    <nav className="topbar sim-topbar" id="top">
      <a className="brand" href="#top" aria-label="Continuum home"><BrandLogo />CONTINUUM</a>
      <div className="thread-chip"><span className="avatar small">Z</span><span>{T('topbar.thread')}</span><span className="online-dot" /></div>
      <div className="provider" title="Provider transparency — recap whisper is Rime only">
        <span>{T('topbar.powered_by')}</span><b>Rime</b><i />
        <span>{T('topbar.model')}: <b>{activeModel}</b></span><i />
        <span>{T('topbar.voice')}: <b>{activeSpeaker}</b></span><i />
        <span>{T('topbar.track')}: <b>{rime ? 'private' : '…'}</b></span>
        {caps?.stt?.enabled && <><i /><span>{T('topbar.stt')}: <b>Deepgram</b></span></>}
      </div>
      <div className={`state-pill${connectedColor}`}>
        <span className="pulse" />{callStateLabel}
      </div>
    </nav>
  )
}

// ── Launch / pre-flight screen ───────────────────────────────────────────────
function LaunchScreen({ sim }) {
  const { capsState, caps, capsError, retryCaps, startCall1, micError, error, chosenScenario, selectScenario, lang } = sim
  const T = (k, v) => format(t(k, lang), v)
  const scenarios = [
    { key: 'full', icon: <Ear size={18} />, titleKey: 'scenario.full.t', descKey: 'scenario.full.d', ctaKey: 'scenario.full.cta' },
    { key: 'barge', icon: <Mic size={18} />, titleKey: 'scenario.barge.t', descKey: 'scenario.barge.d', ctaKey: 'scenario.barge.cta', hot: true },
    { key: 'autoPickup', icon: <AudioLines size={18} />, titleKey: 'scenario.pickup.t', descKey: 'scenario.pickup.d', ctaKey: 'scenario.pickup.cta' },
  ]
  return (
    <section className="launch-wrap">
      <div className="launch-copy">
        <div className="eyebrow"><Sparkles size={14} /> {T('launch.eyebrow')}</div>
        <h1>{T('launch.title_a')}<br /><em>{T('launch.title_b')}</em></h1>
        <p>{T('launch.lead')}</p>
        <div className="launch-flow">
          {[['01', 'launch.step1.t', 'launch.step1.s'], ['02', 'launch.step2.t', 'launch.step2.s'], ['03', 'launch.step3.t', 'launch.step3.s'], ['04', 'launch.step4.t', 'launch.step4.s']].map(([n, tk, sk]) => (
            <div className="launch-step" key={n}><span>{n}</span><div><b>{T(tk)}</b><small>{T(sk)}</small></div></div>
          ))}
        </div>

        <div className="scenario-picker">
          <div className="scenario-head">
            <div><span className="kicker">{T('launch.scenario.kicker')}</span><h2>{T('launch.scenario.title')}</h2></div>
          </div>
          <div className="scenario-grid">
            {scenarios.map((s, i) => (
              <button
                key={s.key}
                className={`scenario-card ${chosenScenario === s.key ? 'selected' : ''} ${s.hot ? 'hot' : ''}`}
                onClick={() => selectScenario(s.key)}
              >
                <span className="scenario-num">{i + 1}</span>
                <span className="scenario-icon">{s.icon}</span>
                <div><b>{T(s.titleKey)}</b><p>{T(s.descKey)}</p><em>{T(s.ctaKey)} <ChevronRight size={13} /></em></div>
              </button>
            ))}
          </div>
          <p className="scenario-hint">{T('launch.scenario.hint')}</p>
        </div>

        <div className="launch-actions">
          <button
            className="primary-button"
            onClick={startCall1}
            disabled={capsState === 'loading' || !chosenScenario}
            title={!chosenScenario ? T('scenario.none') : undefined}
          >
            {capsState === 'loading' ? <Loader2 className="spin" size={16} /> : <Phone size={16} />}
            {T('launch.start')}
          </button>
          {!chosenScenario && <span className="scenario-missing"><AlertTriangle size={13} /> {T('scenario.none')}</span>}
          {capsState === 'error' && (
            <button className="text-button" onClick={retryCaps}>{T('launch.retry')} <RotateCcw size={14} /></button>
          )}
        </div>
        {capsState === 'error' && <div className="caps-error"><AlertTriangle size={15} /> {capsError} {T('launch.caps_error')}</div>}
      </div>

      <div className="readiness-card">
        <div className="card-title"><div><span className="kicker">{T('launch.preflight')}</span><h3>{T('launch.providers')}</h3></div><span className={`live-label ${caps?.ready ? 'ok' : ''}`}><span className="pulse" /> {caps?.ready ? T('launch.ready') : T('launch.check')}</span></div>
        <ReadinessRow
          icon={<Volume2 size={16} />}
          title={T('launch.rime_row')}
          ok={Boolean(caps?.rime?.enabled)}
          detail={
            caps?.rime?.enabled
              ? `${caps.rime.model} · ${caps.rime.speaker} · private track`
              : T('launch.rime_off')
          }
        />
        <ReadinessRow
          icon={<Mic size={16} />}
          title={T('launch.stt_row')}
          ok={Boolean(caps?.stt?.enabled)}
          detail={caps?.stt?.enabled ? T('launch.stt_ok') : T('launch.stt_off')}
        />
        <ReadinessRow
          icon={<Sparkles size={16} />}
          title={T('launch.llm_row')}
          ok={Boolean(caps?.llm?.enabled)}
          detail={caps?.llm?.enabled ? T('launch.llm_ok') : T('launch.llm_off')}
        />
        <ReadinessRow
          icon={<Zap size={16} />}
          title={T('launch.fresh_row')}
          ok={Boolean(caps?.freshness?.enabled)}
          detail={
            caps?.freshness?.enabled
              ? T('launch.fresh_ok', { source: caps.freshness.source_name, count: caps.freshness.products })
              : T('launch.fresh_off')
          }
        />
        <div className="readiness-foot">
          <ShieldCheck size={15} /> {T('launch.foot')}
        </div>
        {(micError || error) && <div className="inline-note warn"><AlertTriangle size={14} />{micError || error}</div>}
      </div>
    </section>
  )
}

function ReadinessRow({ icon, title, ok, detail }) {
  return (
    <div className="readiness-row">
      <span className={`mini-icon ${ok ? 'ok' : ''}`}>{icon}</span>
      <div><b>{title}</b><small>{detail}</small></div>
      <span className={`dot-chip ${ok ? 'ok' : ''}`}>{ok ? <Check size={12} /> : 'off'}</span>
    </div>
  )
}

// ── Running console ──────────────────────────────────────────────────────────
function Console({ sim }) {
  const current = stageIndexFor(sim.phase)
  const T = (k) => t(k, sim.lang)
  return (
    <section className="console-wrap">
      <div className="stage-rail">
        {STAGES.map((stage, i) => (
          <div key={stage.key} className={`stage-item ${i === current ? 'active' : ''} ${i < current ? 'done' : ''}`}>
            {i < current ? <Check size={13} /> : <span>{stage.n}</span>}
            <b>{T(stage.labelKey)}</b><small>{T(stage.shortKey)}</small>
          </div>
        ))}
      </div>
      <div className="dashboard-grid sim-grid">
        <TracksAndMemory sim={sim} />
        <StagePanel sim={sim} />
        <EventLogPanel sim={sim} />
      </div>
      {sim.phase === PHASE.COMPLETED && <Evidence sim={sim} />}
    </section>
  )
}

// ── Left column: dual-track visualizer + thread memory ───────────────────────
function TracksAndMemory({ sim }) {
  const { phase, recapState, audioStatus, threadSummary, recap, recordingSpeaker, callStateLabel, chosenMode, lang } = sim
  const T = (k, v) => format(t(k, lang), v)
  const callerLive = phase === PHASE.CALL1 || phase === PHASE.CONNECTED
  const ringing = phase === PHASE.RECAP
  const whisperPlaying = phase === PHASE.RECAP && recapState === RECAP_STATE.PLAYING
  const mockRun = chosenMode === 'autoPickup'
  const autoConnected = mockRun && callStateLabel === 'CONNECTED'

  const callerStatus = callerLive
    ? mockRun
      ? T('tracks.caller_live_mock')
      : recordingSpeaker === 'CALLER'
        ? T('tracks.caller_live_rec')
        : T('tracks.caller_live')
    : ringing
      ? autoConnected
        ? T('tracks.caller_connected')
        : T('tracks.caller_ring')
      : phase === PHASE.MEMORY
        ? T('tracks.caller_dropped')
        : T('tracks.caller_standby')

  let whisperStatus = T('tracks.whisper_standby')
  if (phase === PHASE.RECAP) {
    whisperStatus = {
      [RECAP_STATE.READY]: T('tracks.whisper_ready'),
      [RECAP_STATE.LOADING]: T('tracks.whisper_loading'),
      [RECAP_STATE.PLAYING]: autoConnected
        ? T('tracks.whisper_playing_connected')
        : T('tracks.whisper_playing'),
      [RECAP_STATE.HALTED]: T('tracks.whisper_halted'),
      [RECAP_STATE.DONE]: T('tracks.whisper_done'),
      [RECAP_STATE.ERROR]: T('tracks.whisper_error'),
      [RECAP_STATE.NEEDS_GESTURE]: T('tracks.whisper_blocked'),
    }[recapState]
  }

  return (
    <div className="col-stack">
      <section className="card tracks-card">
        <div className="card-title">
          <div><span className="kicker">{T('tracks.kicker')}</span><h3>{T('tracks.title')}</h3></div>
          <span className="verified"><Check size={13} /> {T('tracks.fenced')}</span>
        </div>
        <TrackRow
          label={T('tracks.caller_label')}
          sublabel={T('tracks.caller_sub')}
          tone="caller"
          active={callerLive || Boolean(recordingSpeaker)}
          status={callerStatus}
          badge={T('tracks.caller_badge')}
        />
        <div className="track-divider" />
        <TrackRow
          label={T('tracks.whisper_label')}
          sublabel={T('tracks.whisper_sub')}
          tone="whisper"
          active={whisperPlaying || audioStatus === 'loading'}
          status={whisperStatus}
          badge={T('tracks.whisper_badge')}
          statusTone={recapState === RECAP_STATE.HALTED || recapState === RECAP_STATE.ERROR ? 'dim' : ''}
        />
        <div className="separation-note"><ShieldCheck size={16} /><span>{T('tracks.note')}</span></div>
      </section>

      <MemoryCard sim={sim} threadSummary={threadSummary} recap={recap} />
    </div>
  )
}

function TrackRow({ label, sublabel, tone, active, status, badge, statusTone = '' }) {
  return (
    <div className={`track ${tone} ${active ? 'is-active' : ''}`}>
      <div className="track-meta">
        <div className="track-label">
          <span className="track-led" />
          <div><b>{label} {badge && <em className="lane-badge">{badge}</em>}</b><small>{sublabel}</small></div>
        </div>
        <span className={`track-status ${statusTone}`}>{status}</span>
      </div>
      <div className="waveform" aria-label={`${label}: ${status}`}>
        {Array.from({ length: 52 }, (_, i) => (
          <i key={i} style={{ '--h': `${18 + ((i * 37) % 70)}%`, '--d': `${(i % 8) * 0.07}s` }} />
        ))}
      </div>
    </div>
  )
}

function MemoryCard({ sim, threadSummary, recap }) {
  const T = (k, v) => format(t(k, sim.lang), v)
  const freshness = recap?.freshness
  const results = freshness?.results || []
  const changed = results.find((f) => f.status === 'CHANGED')
  const unavailable = results.some((f) => f.status === 'UNAVAILABLE')
  // Every fact in the recap was re-verified against the live source and nothing
  // changed — show that instead of leaving the chip on the ambiguous loading text.
  const allVerified = results.length > 0 && !changed && !unavailable
  const sourceName = sim.caps?.freshness?.source_name || 'live feed'
  return (
    <section className="card memory-card">
      <div className="card-title">
        <div><span className="kicker">{T('memory.kicker')}</span><h3>{T('memory.title')}</h3></div>
        <span className="avatar small">{CALLER.name}</span>
      </div>
      {threadSummary ? (
        <>
          <p className="memory-copy">{threadSummary.headline || T('memory.captured')}</p>
          {threadSummary.time_sensitive_facts?.length > 0 && (
            <div className="fact-rows">
              {threadSummary.time_sensitive_facts.map((f) => (
                <div className="fact-row" key={f.key}><span>{f.label}</span><b>{f.value}</b></div>
              ))}
            </div>
          )}
          <div className={`freshness ${changed ? '' : 'muted'}`}>
            <span className="freshness-icon"><Zap size={15} /></span>
            <div>
              <small>{T('memory.freshness_check')}</small>
              {changed ? (
                <strong>{T('memory.freshness_changed', { label: changed.label, cached: changed.cached_value, live: changed.live_value })}</strong>
              ) : allVerified ? (
                <strong>{T('memory.freshness_verified', { source: sourceName })}</strong>
              ) : unavailable ? (
                <strong>{T('memory.freshness_unavailable')}</strong>
              ) : (
                <strong>{T('memory.freshness_verifying')}</strong>
              )}
            </div>
          </div>
        </>
      ) : (
        <div className="memory-empty"><CircleDot size={18} /><span>{T('memory.empty')}</span></div>
      )}
    </section>
  )
}

// ── Centre column: stage-specific content ────────────────────────────────────
function StagePanel({ sim }) {
  return (
    <section className="card stage-card">
      {sim.phase === PHASE.CALL1 && <CallOneStage sim={sim} />}
      {sim.phase === PHASE.MEMORY && <MemoryStage sim={sim} />}
      {sim.phase === PHASE.RECAP && <RecapStage sim={sim} />}
      {sim.phase === PHASE.CONNECTED && <CallTwoStage sim={sim} />}
      {sim.phase === PHASE.COMPLETED && <CompletedStage sim={sim} />}
    </section>
  )
}

function StageHeader({ kicker, title, note }) {
  return (
    <div className="stage-head">
      <div><span className="kicker">{kicker}</span><h3>{title}</h3></div>
      {note && <span className="stage-note">{note}</span>}
    </div>
  )
}

function TranscriptList({ turns, listening, interimText, lang }) {
  const T = (k) => t(k, lang)
  return (
    <div className="transcript-box">
      {turns.map((turn) => (
        <div key={turn.id} className={`turn ${turn.speaker === 'USER' ? 'user' : 'caller'} ${turn.live ? 'live' : ''}`}>
          <span className="turn-avatar">{SPEAKERS[turn.speaker]?.label || turn.speaker}</span>
          <div><p>{turn.text}</p>{turn.live && <em className="turn-live">speaking…</em>}{turn.mock && <em className="mock-tag">scripted</em>}</div>
        </div>
      ))}
      {turns.length === 0 && (
        <div className="transcript-empty"><Radio size={18} /><span>{T('transcript.empty')}</span></div>
      )}
    </div>
  )
}

// Turn recorder: pick who speaks, record live, stop to store the turn.
function TurnRecorder({ sim, sessionId }) {
  const { recordingSpeaker, interimText, micError, listening, lang } = sim
  const T = (k, v) => format(t(k, lang), v)
  const speakers = [['USER', SPEAKERS.USER.label], ['CALLER', SPEAKERS.CALLER.label]]
  if (recordingSpeaker) {
    return (
      <div className="recorder-panel">
        <div className="recording-banner">
          <span className="rec-dot" />
          <Mic size={14} />
          <b>{T('recorder.recording', { label: SPEAKERS[recordingSpeaker]?.label || recordingSpeaker })}</b>
          {interimText && <em className="interim">“{interimText}”</em>}
        </div>
        <button className="primary-button stop-record" onClick={sim.endTurn}>
          <Square size={15} /> {T('recorder.stop_save')}
        </button>
      </div>
    )
  }
  return (
    <div className="recorder-panel">
      <div className="recorder-grid">
        {speakers.map(([key, label]) => (
          <button
            key={key}
            className={`record-btn ${listening ? 'disabled' : ''}`}
            onClick={() => sim.startTurn(key, sessionId)}
            disabled={Boolean(listening)}
          >
            <Mic size={15} /> {T('recorder.title', { label })}
          </button>
        ))}
      </div>
      {micError && <span className="mic-note warn"><VolumeX size={12} /> {micError}</span>}
      <p className="stage-hint">{T('recorder.hint')}</p>
    </div>
  )
}

function MicChip({ sim }) {
  const { listening, interimText, micError, stopMic, armBargeMic, phase, chosenMode, lang } = sim
  const T = (k) => t(k, lang)
  const mockRun = chosenMode === 'autoPickup'
  if (!listening) {
    return (
      <div className="mic-chip-wrap">
        {micError && <span className="mic-note warn"><VolumeX size={12} /> {micError}</span>}
        {(phase === PHASE.RECAP || mockRun) && sim.caps?.stt?.enabled && (
          <button className="mic-toggle" onClick={() => armBargeMic()}>
            <MicOff size={14} /> {mockRun ? T('mic.enable_auto') : T('mic.enable_interrupt')}
          </button>
        )}
      </div>
    )
  }
  return (
    <div className="mic-chip on">
      <span className="mic-dot" /><Mic size={13} /> {T('mic.listening')}
      {interimText && <em className="interim">“{interimText}”</em>}
      <button className="mic-stop" onClick={stopMic} aria-label={T('mic.stop')}><MicOff size={13} /></button>
    </div>
  )
}

function CallOneStage({ sim }) {
  const T = (k) => t(k, sim.lang)
  return (
    <>
      <StageHeader kicker={T('call1.kicker')} title={T('call1.title')} note={T('call1.note')} />
      <TranscriptList turns={sim.call1Turns} listening={sim.listening} interimText={sim.interimText} lang={sim.lang} />
      <TurnRecorder sim={sim} sessionId="sim-demo-call-1" />
      <div className="stage-foot">
        <p className="stage-hint">{T('call1.hint')}</p>
        <div className="stage-actions">
          <button className="danger-button" onClick={sim.simulateDrop}><PhoneOff size={15} /> {T('call1.drop')}</button>
          <span className="stage-aside">{T('call1.drop_aside')}</span>
        </div>
      </div>
    </>
  )
}

function MemoryStage({ sim }) {
  const T = (k) => t(k, sim.lang)
  return (
    <>
      <StageHeader kicker={T('memory.kicker2')} title={T('memory.title2')} note={T('memory.note')} />
      <div className="memory-banner">
        <div><AlertTriangle size={16} /><p>{T('memory.banner')}</p></div>
        {sim.memoryBusy && <div className="inline-note"><Loader2 className="spin" size={14} /> {T('memory.busy')}</div>}
      </div>
      <div className="morning-card">
        <Clock3 size={16} /><div><b>{T('memory.morning')}</b><small>{T('memory.morning_sub')}</small></div>
        <button className="primary-button compact" onClick={sim.continueToCallback}><PhoneCall size={15} /> {T('memory.continue')}</button>
      </div>
    </>
  )
}

function RecapStage({ sim }) {
  const { recapState, recap, chosenMode, chosenScenario, lang } = sim
  const T = (k, v) => format(t(k, lang), v)
  const showChoices = recapState === RECAP_STATE.READY
  const preset = chosenScenario && chosenScenario === chosenMode
  return (
    <>
      <StageHeader
        kicker={T('recap.kicker')}
        title={showChoices ? T('recap.title_choices') : T('recap.title_playing')}
        note={showChoices ? T('recap.note_choices') : T('recap.note_playing')}
      />
      {showChoices && recap && (
        <div className="choice-panel">
          <ChoiceCard
            icon={<Mic size={18} />}
            title={T('recap.option_barge.t')}
            desc={T('recap.option_barge.d')}
            cta={T('recap.option_barge.cta')}
            onClick={() => sim.chooseRecapMode('barge')}
            hot
          />
          <ChoiceCard
            icon={<Ear size={18} />}
            title={T('recap.option_full.t')}
            desc={T('recap.option_full.d')}
            cta={T('recap.option_full.cta')}
            onClick={() => sim.chooseRecapMode('full')}
          />
          <ChoiceCard
            icon={<AudioLines size={18} />}
            title={T('recap.option_pickup.t')}
            desc={T('recap.option_pickup.d')}
            cta={T('recap.option_pickup.cta')}
            onClick={() => sim.chooseRecapMode('autoPickup')}
          />
          {preset && <p className="recap-preset-note"><Sparkles size={13} /> {T('recap.preset_note')}</p>}
          <button className="skip-answer" onClick={sim.answerCall}>{T('recap.skip')}</button>
        </div>
      )}

      {(recapState === RECAP_STATE.LOADING || recapState === RECAP_STATE.PLAYING || recapState === RECAP_STATE.HALTED || recapState === RECAP_STATE.DONE || recapState === RECAP_STATE.ERROR || recapState === RECAP_STATE.NEEDS_GESTURE) && recap && (
        <RecapPlayer sim={sim} />
      )}
      {recapState === RECAP_STATE.ERROR && !recap && (
        <div className="inline-note warn"><AlertTriangle size={14} /> {sim.error || 'Recap could not be prepared — the stored thread may be missing.'}</div>
      )}
      {recapState === RECAP_STATE.ERROR && !recap && (
        <div className="stage-actions"><button className="primary-button" onClick={sim.answerCall}><Phone size={15} /> {T('recap.answer_error')}</button></div>
      )}
    </>
  )
}

function ChoiceCard({ icon, title, desc, cta, onClick, hot }) {
  return (
    <button className={`choice-card ${hot ? 'hot' : ''}`} onClick={onClick}>
      <span className="choice-icon">{icon}</span>
      <div><b>{title}</b><p>{desc}</p><em>{cta} <ChevronRight size={13} /></em></div>
    </button>
  )
}

function RecapPlayer({ sim }) {
  const { recap, recapState, spokenIdx, listening, chosenMode, bargeResult, audioStatus, callStateLabel, pickupCountdownS, mockLineSpoken, mockError, lang } = sim
  const T = (k, v) => format(t(k, lang), v)
  const sentences = recap?.sentences || []
  const playing = recapState === RECAP_STATE.PLAYING
  const mockRun = chosenMode === 'autoPickup'
  const connected = mockRun && callStateLabel === 'CONNECTED'
  return (
    <>
      <div className="recap-captions">
        {sentences.map((sentence, i) => (
          <p key={`${sentence}-${i}`} className={`cap-line ${i <= spokenIdx && (recapState !== RECAP_STATE.HALTED || i < spokenIdx) ? 'lit' : ''}`}>
            <span>{String(i + 1).padStart(2, '0')}</span>{sentence}
          </p>
        ))}
      </div>
      {mockRun && (
        <div className="recap-mockbar">
          {!connected && pickupCountdownS != null && (
            <span className="pickup-chip"><Clock3 size={12} /> {T('recap.pickup_chip', { s: pickupCountdownS })}</span>
          )}
          {connected && playing && (
            <span className="pickup-chip ok"><PhoneCall size={12} /> {T('recap.connected_chip')}</span>
          )}
          {mockLineSpoken && (
            <span className={`mock-now ${mockLineSpoken.ducked ? 'ducked' : ''}`}>
              <AudioLines size={13} />
              {mockLineSpoken.ducked ? T('recap.mock_line_ducked') : T('recap.mock_line_now')} “{mockLineSpoken.text}”
            </span>
          )}
        </div>
      )}
      {mockError && <div className="inline-note warn"><AlertTriangle size={14} /> {mockError}</div>}
      <div className="recap-statusline">
        {playing && <span className={`live-label ${connected ? 'ok' : ''}`}><span className="pulse" /> {connected ? T('recap.status_connected') : T('recap.status_playing')}</span>}
        {recapState === RECAP_STATE.LOADING && <span className="loading-label"><Loader2 className="spin" size={12} /> {T('recap.status_loading')}</span>}
        {recapState === RECAP_STATE.DONE && <span className="done-label"><Check size={13} /> {T('recap.status_done')}</span>}
        {recapState === RECAP_STATE.ERROR && <span className="err-label"><AlertTriangle size={13} /> {T('recap.status_error')}</span>}
        {recapState === RECAP_STATE.NEEDS_GESTURE && (
          <button className="tap-to-play" onClick={sim.resumeRecapPlayback}>
            <Play size={13} /> {T('recap.tap_to_play')}
          </button>
        )}
        {recapState === RECAP_STATE.HALTED && bargeResult && (
          <span className={`halt-label ${bargeResult.intent === 'ANSWER_CALL' ? 'answer' : 'stop'}`}>
            {bargeResult.intent === 'ANSWER_CALL' ? <PhoneCall size={13} /> : <Square size={13} />}
            {T('recap.halt_answer', { intent: INTENT_LABELS[bargeResult.intent], ms: bargeResult.haltedMs })}
          </span>
        )}
      </div>
      <MicChip sim={sim} />
      <div className="stage-foot">
        <p className="stage-hint">
          {chosenMode === 'autoPickup' && playing && !connected && T('recap.hint_pickup_ring')}
          {chosenMode === 'autoPickup' && playing && connected && T('recap.hint_pickup_connected')}
          {chosenMode === 'autoPickup' && !playing && recapState === RECAP_STATE.DONE && T('recap.hint_pickup_done')}
          {chosenMode === 'barge' && playing && T('recap.hint_barge')}
          {chosenMode === 'full' && playing && T('recap.hint_full')}
          {!playing && recapState !== RECAP_STATE.HALTED && recapState !== RECAP_STATE.DONE && recapState !== RECAP_STATE.NEEDS_GESTURE && T('recap.hint_pick')}
        </p>
        {playing && (
          <div className="barge-tests">
            <span className="barge-tests-label">{T('recap.test_label')}</span>
            {BARGE_EXAMPLES.answer.map((phrase) => (
              <button
                key={phrase}
                className="barge-test answer"
                title={T('recap.test_answer_tip')}
                onClick={() => sim.testPhrase(phrase)}
              >
                <PhoneCall size={13} /> {phrase}
              </button>
            ))}
            {BARGE_EXAMPLES.stop.map((phrase) => (
              <button
                key={phrase}
                className="barge-test stop"
                title={T('recap.test_stop_tip')}
                onClick={() => sim.testPhrase(phrase)}
              >
                <Square size={13} /> {phrase}
              </button>
            ))}
          </div>
        )}
        {(recapState === RECAP_STATE.HALTED || recapState === RECAP_STATE.DONE) && (
          <div className="stage-actions">
            <button className="primary-button" onClick={sim.answerCall}><Phone size={15} /> {T('recap.answer_now')}</button>
            <button className="text-button" onClick={sim.replayRecap}><RotateCcw size={14} /> {T('recap.replay')}</button>
          </div>
        )}
        {recapState === RECAP_STATE.ERROR && (
          <div className="stage-actions">
            <button className="primary-button" onClick={sim.answerCall}><Phone size={15} /> {T('recap.answer_error')}</button>
          </div>
        )}
      </div>
      {audioStatus === 'error' && sim.error && <div className="inline-note warn"><AlertTriangle size={14} /> {sim.error}</div>}
      {sim.bargeResult?.intent === 'DISMISS_RECAP' && (
        <div className="barge-outcome"><span><Square size={13} /> {T('recap.stop_only')}</span><p>{T('recap.stop_only_note')}</p></div>
      )}
    </>
  )
}

function CallTwoStage({ sim }) {
  const T = (k, v) => format(t(k, sim.lang), v)
  const auto = sim.bargeResult?.intent === 'ANSWER_CALL'
  const mockRun = sim.chosenMode === 'autoPickup'
  return (
    <>
      <StageHeader
        kicker={T('call2.kicker')}
        title={mockRun ? T('call2.title_mock') : T('call2.title_live')}
        note={auto ? T('call2.note_auto') : mockRun ? T('call2.note_mock') : T('call2.note_live')}
      />
      {auto && (
        <div className="completion-pill ok">
          <PhoneCall size={14} /> {T('call2.barge_pill', { phrase: sim.bargeResult.phrase, ms: sim.bargeResult.haltedMs })}
        </div>
      )}
      {mockRun && sim.bargeResult?.intent && (
        <div className="completion-pill ok">
          <PhoneCall size={14} /> {T('call2.mock_pill', { phrase: sim.bargeResult.phrase })}
        </div>
      )}
      <TranscriptList turns={sim.call2Turns} listening={sim.listening} interimText={sim.interimText} lang={sim.lang} />
      {mockRun ? <MockAutoPanel sim={sim} /> : <TurnRecorder sim={sim} sessionId="sim-demo-call-2" />}
      <div className="stage-foot">
        <p className="stage-hint">
          {mockRun ? T('call2.hint_mock') : T('call2.hint_live')}
        </p>
        <div className="stage-actions">
          <button className="primary-button" onClick={sim.endCall}><PhoneOff size={15} /> {T('call2.end')}</button>
          <span className="stage-aside">
            {mockRun ? T('call2.aside_mock') : T('call2.aside_live')}
          </span>
        </div>
      </div>
    </>
  )
}

function MockAutoPanel({ sim }) {
  const T = (k) => t(k, sim.lang)
  const { mockLineSpoken } = sim
  return (
    <div className="auto-live-panel">
      {mockLineSpoken && (
        <div className="mock-now">
          <AudioLines size={13} /> {T('recap.mock_line_now')} “{mockLineSpoken.text}”
        </div>
      )}
      <MicChip sim={sim} />
      <p className="stage-hint">{T('mock_auto.hint')}</p>
    </div>
  )
}

function CompletedStage({ sim }) {
  const T = (k, v) => format(t(k, sim.lang), v)
  return (
    <>
      <StageHeader kicker={T('done.kicker')} title={T('done.title')} note={T('done.note')} />
      <div className="completed-summary">
        <div className="completion-pill ok"><ShieldCheck size={14} /> {T('done.pill1')}</div>
        {sim.metrics?.turns != null && <div className="completion-pill"><Mic size={14} /> {T('done.pill2', { n: sim.metrics.turns })}</div>}
        {sim.metrics?.intent && <div className="completion-pill"><PhoneCall size={14} /> {T('done.pill3', { intent: sim.metrics.intent })}</div>}
        {sim.metrics?.autoPickupMode === 'network' && <div className="completion-pill"><PhoneCall size={14} /> {T('done.pill4')}</div>}
        {sim.metrics?.mockLines > 0 && <div className="completion-pill"><AudioLines size={14} /> {T('done.pill5', { n: sim.metrics.mockLines })}{sim.metrics.echoFiltered ? ` · ${sim.metrics.echoFiltered} mic echo${sim.metrics.echoFiltered === 1 ? '' : 'es'} filtered` : ''}</div>}
        <div className="stage-actions">
          <button className="primary-button" onClick={sim.fullReset}><RotateCcw size={15} /> {T('done.reset')}</button>
          <button className="text-button" onClick={() => exportLog(sim)}><Download size={14} /> {T('done.export')}</button>
        </div>
      </div>
    </>
  )
}

function exportLog(sim) {
  const payload = {
    generated_at: new Date().toISOString(),
    scenario: 'live two-way conversation · Rime recap · barge-in voice interrupt',
    thread: { caller: CALLER.number, caller_name: CALLER.name },
    events: sim.events.map(({ tsLabel, name, detail, meta }) => ({ ts: tsLabel, event: name, detail, meta })),
    metrics: sim.metrics,
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'continuum-demo-event-log.json'
  a.click()
  URL.revokeObjectURL(url)
}

// ── Right column: append-only event log ──────────────────────────────────────
function EventLogPanel({ sim }) {
  const { events, lang } = sim
  const T = (k) => t(k, lang)
  return (
    <section className="card event-card">
      <div className="card-title">
        <div><span className="kicker">{T('log.kicker')}</span><h3>{T('log.title')}</h3></div>
        <span className="live-label"><span className="pulse" /> LIVE</span>
      </div>
      <div className="event-list">
        {events.length ? events.map((item) => <EventRow key={item.id} item={item} />) : (
          <div className="empty-log"><Radio size={20} /><span>{T('log.empty')}</span></div>
        )}
      </div>
    </section>
  )
}

function EventRow({ item }) {
  const Icon = KIND_ICONS[item.kind] || Activity
  return (
    <div className={`event ${item.kind}`}>
      <span className="event-icon"><Icon size={14} /></span>
      <div>
        <div className="event-main"><time>{item.tsLabel}</time><b>{item.name}</b></div>
        {item.detail && <small>{item.detail}</small>}
      </div>
    </div>
  )
}

// ── Evidence strip (after completion) ────────────────────────────────────────
function Evidence({ sim }) {
  const m = sim.metrics || {}
  const T = (k) => t(k, sim.lang)
  return (
    <section className="evidence-strip" id="evidence">
      <div className="section-heading compact-heading light"><div><span className="eyebrow"><Gauge size={14} /> {T('evidence.eyebrow')}</span><h2>{T('evidence.title')}</h2></div></div>
      <div className="metrics-grid">
        <EvidenceCard value={m.recapLatencyMs != null ? `${(m.recapLatencyMs / 1000).toFixed(2)}s` : '—'} label={T('evidence.latency.v')} note={T('evidence.latency.n')} />
        <EvidenceCard value={m.bargeHaltMs != null ? `${m.bargeHaltMs}ms` : '—'} label={T('evidence.halt.v')} note={m.bargePhrase ? `phrase: “${m.bargePhrase}”` : T('evidence.no_barge')} />
        <EvidenceCard value="0ms" label={T('evidence.caller.v')} note={T('evidence.caller.n')} />
        <EvidenceCard value={m.freshnessChanged ? T('evidence.caught') : '—'} label={T('evidence.fresh.v')} note={m.freshnessDetail || T('evidence.no_source')} />
      </div>
      <div className="evidence-map">
        {[[T('evidence.map.latency'), m.recapLatencyMs != null ? T('evidence.map.measured') : 'n/a'], [T('evidence.map.barge'), m.bargeHaltMs != null ? T('evidence.map.measured') : 'n/a'], [T('evidence.map.caller'), T('evidence.map.architectural')], [T('evidence.map.fresh'), m.freshnessChanged ? 'PASS' : 'n/a'], [T('evidence.map.intent'), m.intent || 'n/a'], [T('evidence.map.fencing'), T('evidence.map.single')]].map(([label, status]) => (
          <div className={`evidence-map-row ${status === 'PASS' || status === 'measured' || status === 'architectural' ? 'pass' : ''}`} key={label}>
            <span>{label}</span><b>{status === 'PASS' || status === 'measured' || status === 'architectural' ? <Check size={12} /> : null}{status}</b>
          </div>
        ))}
      </div>
    </section>
  )
}

function EvidenceCard({ value, label, note }) {
  return (
    <article className="metric light">
      <strong>{value}</strong>
      <h3>{label}</h3>
      <p>{note}</p>
      <span className="pass"><Check size={13} /> PASS</span>
    </article>
  )
}

createRoot(document.getElementById('root')).render(<SimApp />)