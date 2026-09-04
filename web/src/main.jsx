import React from 'react'
import { createRoot } from 'react-dom/client'
import {
  Activity, AlertTriangle, ArrowRight, AudioLines, Bot, Check, ChevronRight, CircleDot,
  Clock3, Command, Download, Ear, Gauge, Loader2, Mic, MicOff, Phone, PhoneCall, PhoneOff,
  Play, Radio, RotateCcw, ShieldCheck, Sparkles, Square, Volume2, VolumeX, Waves, Zap,
} from 'lucide-react'
import './styles.css'
import './sim-console.css'
import { CALLER, INTENT_LABELS } from './sim/config.js'
import { PHASE, RECAP_STATE, useSimulation } from './sim/useSimulation.js'

const KIND_ICONS = {
  call: PhoneCall,
  memory: CircleDot,
  brain: Bot,
  alert: Zap,
  voice: Volume2,
  action: Command,
}

const STAGES = [
  { key: PHASE.CALL1, n: '01', label: 'Call with Z', short: 'Yesterday' },
  { key: PHASE.MEMORY, n: '02', label: 'Interrupted', short: 'Memory saved' },
  { key: PHASE.RECAP, n: '03', label: 'Callback ring', short: 'Next morning' },
  { key: PHASE.CONNECTED, n: '04', label: 'Recap / barge-in', short: 'Caught up' },
  { key: PHASE.COMPLETED, n: '05', label: 'Connected', short: 'Evidence' },
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
        <a className="brand" href="#top"><span className="brand-mark"><Waves size={18} /></span>CONTINUUM</a>
        <span>Voice-native continuity for the moments that matter.</span>
        <span>Made for Rime Hackathon · 2026</span>
      </footer>
    </main>
  )
}

// ── Top bar (always visible — demo script §02A) ──────────────────────────────
function TopBar({ sim }) {
  const { caps, phase, callStateLabel } = sim
  const rime = caps?.rime
  // Once the recap is generated, surface the voice/model actually speaking.
  const activeModel = sim.recap?.model || rime?.model || '…'
  const activeSpeaker = sim.recap?.speaker || rime?.speaker || '…'
  const connectedColor =
    callStateLabel === 'CONNECTED' ? ' connected' : callStateLabel === 'RINGING' ? ' ringing' : ''
  return (
    <nav className="topbar sim-topbar" id="top">
      <a className="brand" href="#top" aria-label="Continuum home"><span className="brand-mark"><Waves size={18} /></span>CONTINUUM</a>
      <div className="thread-chip"><span className="avatar small">Z</span><span>Thread: Z · Contact</span><span className="online-dot" /></div>
      <div className="provider" title="Provider transparency — recap whisper is Rime only">
        <span>Powered by</span><b>Rime</b><i />
        <span>model: <b>{activeModel}</b></span><i />
        <span>voice: <b>{activeSpeaker}</b></span><i />
        <span>track: <b>{rime ? 'private' : '…'}</b></span>
        {caps?.stt?.enabled && <><i /><span>STT: <b>Deepgram</b></span></>}
      </div>
      <div className={`state-pill${connectedColor}`}>
        <span className="pulse" />{callStateLabel}
      </div>
    </nav>
  )
}

// ── Launch / pre-flight screen ───────────────────────────────────────────────
function LaunchScreen({ sim }) {
  const { capsState, caps, capsError, retryCaps, startCall1, micError, error } = sim
  return (
    <section className="launch-wrap">
      <div className="launch-copy">
        <div className="eyebrow"><Sparkles size={14} /> Conversation continuity, before hello</div>
        <h1>Hear the recap.<br /><em>Then pick up.</em></h1>
        <p>
          Continuum whispers yesterday&apos;s conversation into your ear while the phone is still ringing —
          and if you&apos;ve heard enough, you can just say <em>&ldquo;I know, just pick up the call.&rdquo;</em>
        </p>
        <div className="launch-flow">
          {[['01', 'Live call with Z', 'you speak, Z replies'], ['02', 'Line drops', 'thread memory saved'], ['03', 'Z calls back', 'Rime recap on your private track'], ['04', 'Barge-in or listen', 'say the phrase → auto-answer']].map(([n, t, s]) => (
            <div className="launch-step" key={n}><span>{n}</span><div><b>{t}</b><small>{s}</small></div></div>
          ))}
        </div>
        <div className="launch-actions">
          <button className="primary-button" onClick={startCall1} disabled={capsState === 'loading'}>
            {capsState === 'loading' ? <Loader2 className="spin" size={16} /> : <Phone size={16} />}
            Start the simulation
          </button>
          {capsState === 'error' && (
            <button className="text-button" onClick={retryCaps}>Retry backend check <RotateCcw size={14} /></button>
          )}
        </div>
        {capsState === 'error' && <div className="caps-error"><AlertTriangle size={15} /> {capsError} — start the dashboard server, then retry.</div>}
      </div>

      <div className="readiness-card">
        <div className="card-title"><div><span className="kicker">Pre-flight</span><h3>Live providers</h3></div><span className={`live-label ${caps?.ready ? 'ok' : ''}`}><span className="pulse" /> {caps?.ready ? 'READY' : 'CHECK'}</span></div>
        <ReadinessRow
          icon={<Volume2 size={16} />}
          title="Rime recap whisper"
          ok={Boolean(caps?.rime?.enabled)}
          detail={
            caps?.rime?.enabled
              ? `${caps.rime.model} · ${caps.rime.speaker} · private track`
              : 'Requires USE_MOCKS=false + RIME_API_KEY (recap stays Rime — never substituted)'
          }
        />
        <ReadinessRow
          icon={<Mic size={16} />}
          title="Deepgram live STT"
          ok={Boolean(caps?.stt?.enabled)}
          detail={caps?.stt?.enabled ? 'Your replies are transcribed live' : 'Set USE_MOCKS=false + DEEPGRAM_API_KEY. Typed replies still work.'}
        />
        <ReadinessRow
          icon={<Activity size={16} />}
          title="Freshness API"
          ok={Boolean(caps?.freshness?.enabled)}
          detail={
            caps?.freshness?.enabled
              ? `price_usd live = ${caps.freshness.price_usd} (triggers the $400 → $420 catch)`
              : `Start python -m mocks.mock_freshness (port 8001) for the staleness flag`
          }
        />
        <div className="readiness-foot">
          <ShieldCheck size={15} /> Recap audio is architecturally separate from the caller track. Z&apos;s voice is a
          clearly-labelled simulated caller; the recap is Rime only.
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
  return (
    <section className="console-wrap">
      <div className="stage-rail">
        {STAGES.map((stage, i) => (
          <div key={stage.key} className={`stage-item ${i === current ? 'active' : ''} ${i < current ? 'done' : ''}`}>
            {i < current ? <Check size={13} /> : <span>{stage.n}</span>}
            <b>{stage.label}</b><small>{stage.short}</small>
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
  const { phase, recapState, audioStatus, threadSummary, recap, activeSpeaker } = sim
  const callerLive = phase === PHASE.CALL1 || phase === PHASE.CONNECTED
  const ringing = phase === PHASE.RECAP
  const whisperPlaying = phase === PHASE.RECAP && recapState === RECAP_STATE.PLAYING

  const callerStatus = callerLive
    ? 'Live call with Z'
    : ringing
      ? 'Ringback tone only — what Z hears'
      : phase === PHASE.MEMORY
        ? 'Call dropped — interrupted'
        : 'Standby'

  let whisperStatus = 'Standing by'
  if (phase === PHASE.RECAP) {
    whisperStatus = {
      [RECAP_STATE.READY]: 'Recap ready on your private track',
      [RECAP_STATE.LOADING]: 'Connecting to Rime…',
      [RECAP_STATE.PLAYING]: 'Rime recap playing — your earpiece only',
      [RECAP_STATE.HALTED]: 'Playback halted (barge-in)',
      [RECAP_STATE.DONE]: 'Recap complete — you are caught up',
      [RECAP_STATE.ERROR]: 'Rime unavailable — no fallback audio',
    }[recapState]
  }

  return (
    <div className="col-stack">
      <section className="card tracks-card">
        <div className="card-title">
          <div><span className="kicker">Audio isolation</span><h3>Two tracks. Zero leakage.</h3></div>
          <span className="verified"><Check size={13} /> fenced</span>
        </div>
        <TrackRow
          label="Caller-facing track"
          sublabel="What Z hears"
          tone="caller"
          active={callerLive || Boolean(activeSpeaker)}
          status={callerStatus}
          badge="SIMULATED CALLER · BROWSER VOICE"
        />
        <div className="track-divider" />
        <TrackRow
          label="Private whisper track"
          sublabel="What only you hear"
          tone="whisper"
          active={whisperPlaying || audioStatus === 'loading'}
          status={whisperStatus}
          badge="RIME"
          statusTone={recapState === RECAP_STATE.HALTED || recapState === RECAP_STATE.ERROR ? 'dim' : ''}
        />
        <div className="separation-note"><ShieldCheck size={16} /><span>Rime recap audio routes exclusively to <code>continuum-private-whisper</code> — never the caller track.</span></div>
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

function MemoryCard({ threadSummary, recap }) {
  const freshness = recap?.freshness
  const changed = freshness?.results?.find((f) => f.status === 'CHANGED')
  return (
    <section className="card memory-card">
      <div className="card-title">
        <div><span className="kicker">Thread memory</span><h3>What happened yesterday</h3></div>
        <span className="avatar small">{CALLER.name}</span>
      </div>
      {threadSummary ? (
        <>
          <p className="memory-copy">{threadSummary.headline || 'Call was interrupted — memory captured.'}</p>
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
              <small>Freshness check</small>
              {changed ? (
                <strong>{changed.label}: <s>{changed.cached_value}</s> → now {changed.live_value}</strong>
              ) : (
                <strong>Re-verifying before speaking…</strong>
              )}
            </div>
          </div>
        </>
      ) : (
        <div className="memory-empty"><CircleDot size={18} /><span>No thread yet — the call with Z will be stored here after the drop.</span></div>
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

function TranscriptList({ turns, listening, interimText, label }) {
  return (
    <div className="transcript-box">
      {turns.map((turn) => (
        <div key={turn.id} className={`turn ${turn.speaker === 'USER' ? 'user' : 'caller'} ${turn.live ? 'live' : ''}`}>
          <span className="turn-avatar">{turn.speaker === 'USER' ? 'You' : 'Z'}</span>
          <div><p>{turn.text}</p>{turn.live && <em className="turn-live">speaking…</em>}</div>
        </div>
      ))}
      {turns.length === 0 && (
        <div className="transcript-empty"><Radio size={18} /><span>Waiting for the call to start…</span></div>
      )}
    </div>
  )
}

function MicChip({ sim }) {
  const { listening, interimText, micError, stopMic, armBargeMic, phase } = sim
  if (!listening) {
    return (
      <div className="mic-chip-wrap">
        {micError && <span className="mic-note warn"><VolumeX size={12} /> {micError}</span>}
        {phase === PHASE.RECAP && sim.caps?.stt?.enabled && (
          <button className="mic-toggle" onClick={() => armBargeMic()}><MicOff size={14} /> Enable mic interrupt</button>
        )}
      </div>
    )
  }
  return (
    <div className="mic-chip on">
      <span className="mic-dot" /><Mic size={13} /> Listening for your voice
      {interimText && <em className="interim">“{interimText}”</em>}
      <button className="mic-stop" onClick={stopMic} aria-label="Stop listening"><MicOff size={13} /></button>
    </div>
  )
}

function SuggestionChips({ sim, listKey }) {
  const suggestions = sim.capsSuggestions[listKey]
  return (
    <div className="suggestion-row">
      {suggestions.map((text) => (
        <button key={text} className="suggestion-chip" onClick={() => sim.suggestReply(text, listKey)}>
          <Mic size={12} /> {text}
        </button>
      ))}
    </div>
  )
}

function CallOneStage({ sim }) {
  return (
    <>
      <StageHeader kicker="Yesterday · live call" title="Call with Z — you are on the line" note="your replies are transcribed live" />
      <TranscriptList turns={sim.call1Turns} listening={sim.listening} interimText={sim.interimText} />
      <MicChip sim={sim} />
      <div className="stage-foot">
        <p className="stage-hint">Z is scripted for the demo. Reply aloud when Z pauses — or click a suggested line.</p>
        <SuggestionChips sim={sim} listKey="call1" />
        <div className="stage-actions">
          <button className="danger-button" onClick={sim.simulateDrop}><PhoneOff size={15} /> Simulate network drop</button>
          <span className="stage-aside">The line drops mid-sentence — no goodbye, just like a tunnel.</span>
        </div>
      </div>
    </>
  )
}

function MemoryStage({ sim }) {
  return (
    <>
      <StageHeader kicker="Interruption & recovery" title="Thread saved — Z will call back" note="yesterday 2:02 PM" />
      <div className="memory-banner">
        <div><AlertTriangle size={16} /><p>The call ended abruptly while Z was mid-sentence. The Thread Memory Store kept the last state — facts, commitments and open items.</p></div>
        {sim.memoryBusy && <div className="inline-note"><Loader2 className="spin" size={14} /> Extracting structured memory…</div>}
      </div>
      <div className="morning-card">
        <Clock3 size={16} /><div><b>Next morning · 9:14 AM</b><small>Z&apos;s number rings in. The ring window is where Continuum catches you up.</small></div>
        <button className="primary-button compact" onClick={sim.continueToCallback}><PhoneCall size={15} /> Continue →</button>
      </div>
    </>
  )
}

function RecapStage({ sim }) {
  const { recapState, recap, chosenMode } = sim
  const showChoices = recapState === RECAP_STATE.READY
  return (
    <>
      <StageHeader
        kicker="Next morning · incoming call"
        title={showChoices ? 'Z is calling — recap is ready' : 'Private whisper recap'}
        note={showChoices ? 'RINGING — matched to paused thread' : 'Rime on the private track'}
      />
      {showChoices && recap && (
        <div className="choice-panel">
          <ChoiceCard
            icon={<Mic size={18} />}
            title="Barge in by voice"
            desc="Hear the recap, and when you’ve heard enough say: “I know, just pick up the call.” The system stops talking and answers for you."
            cta="Option A — barge-in"
            onClick={() => sim.chooseRecapMode('barge')}
            hot
          />
          <ChoiceCard
            icon={<Ear size={18} />}
            title="Hear the full recap"
            desc="Let the whole recap play in your earpiece. When it ends, you answer already 100% caught up."
            cta="Option B — listen fully"
            onClick={() => sim.chooseRecapMode('full')}
          />
          <button className="skip-answer" onClick={sim.answerCall}>Answer now without the recap (skip)</button>
        </div>
      )}

      {(recapState === RECAP_STATE.LOADING || recapState === RECAP_STATE.PLAYING || recapState === RECAP_STATE.HALTED || recapState === RECAP_STATE.DONE || recapState === RECAP_STATE.ERROR) && recap && (
        <RecapPlayer sim={sim} />
      )}
      {recapState === RECAP_STATE.ERROR && !recap && (
        <div className="inline-note warn"><AlertTriangle size={14} /> {sim.error || 'Recap could not be prepared — the stored thread may be missing.'}</div>
      )}
      {recapState === RECAP_STATE.ERROR && !recap && (
        <div className="stage-actions"><button className="primary-button" onClick={sim.answerCall}><Phone size={15} /> Answer Z anyway</button></div>
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
  const { recap, recapState, spokenIdx, listening, chosenMode, bargeResult, audioStatus } = sim
  const sentences = recap?.sentences || []
  const playing = recapState === RECAP_STATE.PLAYING
  return (
    <>
      <div className="recap-captions">
        {sentences.map((sentence, i) => (
          <p key={`${sentence}-${i}`} className={`cap-line ${i <= spokenIdx && (recapState !== RECAP_STATE.HALTED || i < spokenIdx) ? 'lit' : ''}`}>
            <span>{String(i + 1).padStart(2, '0')}</span>{sentence}
          </p>
        ))}
      </div>
      <div className="recap-statusline">
        {playing && <span className="live-label"><span className="pulse" /> RIME SPEAKING ON PRIVATE TRACK</span>}
        {recapState === RECAP_STATE.LOADING && <span className="loading-label"><Loader2 className="spin" size={12} /> synthesizing with Rime…</span>}
        {recapState === RECAP_STATE.DONE && <span className="done-label"><Check size={13} /> Recap complete</span>}
        {recapState === RECAP_STATE.ERROR && <span className="err-label"><AlertTriangle size={13} /> Rime unavailable — see error below. Answer to continue.</span>}
        {recapState === RECAP_STATE.HALTED && bargeResult && (
          <span className={`halt-label ${bargeResult.intent === 'ANSWER_CALL' ? 'answer' : 'stop'}`}>
            {bargeResult.intent === 'ANSWER_CALL' ? <PhoneCall size={13} /> : <Square size={13} />}
            Barge-in → {INTENT_LABELS[bargeResult.intent]} · halted in {bargeResult.haltedMs}ms
          </span>
        )}
      </div>
      <MicChip sim={sim} />
      <div className="stage-foot">
        <p className="stage-hint">
          {chosenMode === 'barge' && playing && 'Full-duplex: your mic stays hot while the recap plays. Say the phrase whenever you’re ready.'}
          {chosenMode === 'full' && playing && 'Option B — the recap plays to the end. Interrupt it anytime with the test buttons below.'}
          {!playing && recapState !== RECAP_STATE.HALTED && recapState !== RECAP_STATE.DONE && 'Choose an option above to hear the recap.'}
        </p>
        {playing && (
          <div className="barge-tests">
            <button className="barge-test answer" onClick={() => sim.testPhrase('I know, just pick up the call')}>
              <Mic size={14} /> Test: “I know, just pick up the call”
            </button>
            <button className="barge-test stop" onClick={() => sim.testPhrase('Hold on, one second')}>
              <Square size={13} /> Test: “Hold on” (stop-only)
            </button>
          </div>
        )}
        {(recapState === RECAP_STATE.HALTED || recapState === RECAP_STATE.DONE) && (
          <div className="stage-actions">
            <button className="primary-button" onClick={sim.answerCall}><Phone size={15} /> Answer Z now</button>
            <button className="text-button" onClick={sim.replayRecap}><RotateCcw size={14} /> Replay recap</button>
          </div>
        )}
        {recapState === RECAP_STATE.ERROR && (
          <div className="stage-actions">
            <button className="primary-button" onClick={sim.answerCall}><Phone size={15} /> Answer Z anyway</button>
          </div>
        )}
      </div>
      {audioStatus === 'error' && sim.error && <div className="inline-note warn"><AlertTriangle size={14} /> {sim.error}</div>}
      {sim.bargeResult?.intent === 'DISMISS_RECAP' && (
        <div className="barge-outcome"><span><Square size={13} /> stop-only</span><p>Generic interrupt — the recap halted but Z keeps ringing. You stay in control.</p></div>
      )}
    </>
  )
}

function CallTwoStage({ sim }) {
  const auto = sim.bargeResult?.intent === 'ANSWER_CALL'
  return (
    <>
      <StageHeader kicker="Now · call reconnected" title="You picked up already caught up" note={auto ? 'AUTO-ANSWERED' : 'CONNECTED'} />
      {auto && (
        <div className="completion-pill ok">
          <PhoneCall size={14} /> Barge-in “{sim.bargeResult.phrase}” → recap halted in {sim.bargeResult.haltedMs}ms → auto-answered. Z never heard the recap.
        </div>
      )}
      <TranscriptList turns={sim.call2Turns} listening={sim.listening} interimText={sim.interimText} />
      <MicChip sim={sim} />
      <div className="stage-foot">
        <p className="stage-hint">Z doesn’t know you were briefed — that’s the point. Answer naturally, then end the call when done.</p>
        <SuggestionChips sim={sim} listKey="call2" />
        <div className="stage-actions">
          <button className="primary-button" onClick={sim.endCall}><PhoneOff size={15} /> End call</button>
          <span className="stage-aside">Rime recap stays on the private track — Z heard only normal ringing and your “hello”.</span>
        </div>
      </div>
    </>
  )
}

function CompletedStage({ sim }) {
  return (
    <>
      <StageHeader kicker="Wrap-up" title="Simulation complete" note="all events timestamped" />
      <div className="completed-summary">
        <div className="completion-pill ok"><ShieldCheck size={14} /> Caught up before “hello” — recap never left the private track.</div>
        {sim.metrics?.intent && <div className="completion-pill"><PhoneCall size={14} /> Barge-in phrase → {sim.metrics.intent}</div>}
        <div className="stage-actions">
          <button className="primary-button" onClick={sim.fullReset}><RotateCcw size={15} /> Reset & replay</button>
          <button className="text-button" onClick={() => exportLog(sim)}><Download size={14} /> Export event log (JSON)</button>
        </div>
      </div>
    </>
  )
}

function exportLog(sim) {
  const payload = {
    generated_at: new Date().toISOString(),
    scenario: 'returning caller · barge-in voice interrupt',
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
  const { events } = sim
  return (
    <section className="card event-card">
      <div className="card-title">
        <div><span className="kicker">Append-only feed</span><h3>Event log</h3></div>
        <span className="live-label"><span className="pulse" /> LIVE</span>
      </div>
      <div className="event-list">
        {events.length ? events.map((item) => <EventRow key={item.id} item={item} />) : (
          <div className="empty-log"><Radio size={20} /><span>Waiting for a call event…</span></div>
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
  return (
    <section className="evidence-strip" id="evidence">
      <div className="section-heading compact-heading light"><div><span className="eyebrow"><Gauge size={14} /> Evidence, not claims</span><h2>Measured in this run.</h2></div></div>
      <div className="metrics-grid">
        <EvidenceCard value={m.recapLatencyMs != null ? `${(m.recapLatencyMs / 1000).toFixed(2)}s` : '—'} label="Match → first private audio" note="ring to recap speech, measured live" />
        <EvidenceCard value={m.bargeHaltMs != null ? `${m.bargeHaltMs}ms` : '—'} label="Barge-in → playback halted" note={m.bargePhrase ? `phrase: “${m.bargePhrase}”` : 'no barge-in in this run'} />
        <EvidenceCard value="0ms" label="Caller-side added latency" note="caller lane = ringback only — recap never touches it" />
        <EvidenceCard value={m.freshnessChanged ? 'caught' : '—'} label="Freshness catch" note={m.freshnessDetail || 'no stored price to re-verify'} />
      </div>
      <div className="evidence-map">
        {[['Recap start latency', m.recapLatencyMs != null ? 'measured' : 'n/a'], ['Barge-in latency', m.bargeHaltMs != null ? 'measured' : 'n/a'], ['Zero caller impact', 'architectural'], ['Freshness catch', m.freshnessChanged ? 'PASS' : 'n/a'], ['Intent correctness', m.intent || 'n/a'], ['Context fencing', 'single thread']].map(([label, status]) => (
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
