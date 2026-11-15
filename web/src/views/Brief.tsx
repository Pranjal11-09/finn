import { useEffect, useMemo, useState } from 'react'
import { api, ago, CAT, fmtPct, type Digest, type Item } from '../api'
import { Slip } from '../components/Slip'

const WINDOWS = [[24, '24h'], [72, '3d'], [168, '7d'], [720, '30d']] as const

function Lede({ text }: { text: string }) {
  const m = text.match(/^(\d+) things need you: (.*)$/)
  if (!m) return <h1 className="lede">{text}</h1>
  return <>
    <h1 className="lede"><span className="count">{m[1]} things</span> need you.</h1>
    <p className="lede-sub">{m[2][0].toUpperCase() + m[2].slice(1)}</p>
  </>
}

export function Brief({ onAsk, onCount }: { onAsk: (s: string, q?: string) => void; onCount: (n: number) => void }) {
  const [hours, setHours] = useState(24)
  const [d, setD] = useState<Digest | null>(null)
  const [err, setErr] = useState('')
  const [gone, setGone] = useState<Set<string>>(new Set())

  useEffect(() => { api.settings().then((s) => setHours(s.window_hours)).catch(() => {}) }, [])
  useEffect(() => {
    setD(null); setErr('')
    api.digest(hours).then(setD).catch((e) => setErr(String(e.message || e)))
  }, [hours])

  const visible = (i: Item) => !gone.has(i.id) && i.state !== 'done' && i.state !== 'less'
  const act = useMemo(() => d?.items.filter((i) => i.tier === 'act' && visible(i)) ?? [], [d, gone])
  const know = useMemo(() => d?.items.filter((i) => i.tier === 'know' && visible(i)) ?? [], [d, gone])
  const routine = d?.items.filter((i) => i.tier === 'routine') ?? []
  useEffect(() => { onCount(act.length) }, [act.length])

  const pick = (h: number) => { setHours(h); api.saveSettings({ window_hours: h }).catch(() => {}) }
  const dismiss = (id: string) => setGone((g) => new Set(g).add(id))
  const listen = () => {
    if (!d || !('speechSynthesis' in window)) return
    speechSynthesis.cancel()
    const parts = [d.headline, ...act.map((i) => `${i.name || i.symbol}: ${CAT[i.category]}. ${i.line || ''}`)]
    speechSynthesis.speak(Object.assign(new SpeechSynthesisUtterance(parts.join('. ')), { lang: 'en-IN', rate: 1.05 }))
  }
  const today = new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'short' })
  const failed = d ? Object.values(d.feed_status).filter((s) => s === 'error' || s === 'stale' || s === 'refreshing').length : 0

  return (
    <>
      <div className="dateline">
        <span>{today}</span>
        <div className="window-pick" role="group" aria-label="Time window">
          {WINDOWS.map(([h, l]) => <button key={h} aria-pressed={hours === h} onClick={() => pick(h)}>{l}</button>)}
        </div>
      </div>
      {err && <p className="err">Couldn't load the brief: {err}</p>}
      {!d && !err && <><div className="skeleton" style={{ height: 30, width: '90%' }} /><div className="skeleton" style={{ height: 30, width: '70%' }} /></>}
      {d && <>
        <Lede text={!act.length && !d.movers.length ? (failed ? `No urgent items in the available data.` : `Nothing needs you right now.`) : gone.size === 0 ? d.headline : `${act.length + d.movers.length} things need you: ${act.length} filings, ${d.movers.length} unusual moves.`} />
        <p className="sub">
          {d.items.length} filings across {d.tape.length} holdings in the last {hours >= 48 ? `${hours / 24} days` : `${hours} hours`}.{' '}
          {'speechSynthesis' in window && <button className="btn" style={{ padding: '2px 8px', fontSize: 12.5 }} onClick={listen}>Listen</button>}
        </p>
        {d.fixtures && <p className="banner">Synthetic test data. Live feeds are off in this build.</p>}
        {failed > 0 && <p className="banner">{failed} exchange feeds are refreshing or unavailable. Saved filings are filtered to the selected window.</p>}

        <div className="tape" aria-label="Portfolio today">
          {d.tape.map((t) => (
            <button key={t.symbol} className={`tick${d.movers.includes(t.symbol) ? ' unusual' : ''}`} onClick={() => onAsk(t.symbol)}>
              <b>{t.symbol}</b><small>{t.date}{t.stale ? " · cached" : ""}</small>
              <span className={`chg ${t.chg_pct >= 0 ? 'up' : 'down'}`}>{fmtPct(t.chg_pct)}</span>
              <small>{t.vol_mult != null ? `${t.vol_mult.toFixed(1)}× vol` : ''}</small>
            </button>
          ))}
        </div>

        <div className="sec-h"><h2>Needs you</h2><span>{act.length ? 'Swipe right when done' : ''}</span></div>
        {act.length === 0 && <div className="empty"><h3>{failed ? 'No urgent filings in the available data.' : 'You’re clear.'}</h3><p>Try a longer window, or check Alerts for price moves.</p></div>}
        {act.map((i) => <Slip key={i.id} item={i} onTriage={dismiss} onAsk={onAsk} />)}

        {know.length > 0 && <>
          <div className="sec-h"><h2>Worth knowing</h2><span>{know.length}</span></div>
          <div className="lines">
            {know.map((i) => (
              <div className="line" key={i.id}>
                <div className="t"><b>{i.symbol}</b>{i.line || i.headline}</div>
                <button aria-label="Dismiss" onClick={() => { dismiss(i.id); api.triage(i.id, 'done') }}>×</button>
                <div className="meta"><span>{CAT[i.category]}</span><span>{ago(i.ts)}</span>{i.url && <a href={i.url} target="_blank" rel="noreferrer">Filing</a>}</div>
              </div>
            ))}
          </div>
        </>}

        {routine.length > 0 && <>
          <div className="sec-h"><h2>Filed away</h2></div>
          <details className="drawer">
            <summary><span>{routine.length} routine filings</span><span>Show</span></summary>
            <div className="cats">{Object.entries(d.routine_by_category).map(([c, n]) => <span key={c}>{CAT[c] || c} {n}</span>)}</div>
            <ul>{routine.map((i) => <li key={i.id}><b>{i.symbol}</b><a href={i.url} target="_blank" rel="noreferrer">{i.headline}</a></li>)}</ul>
          </details>
        </>}
      </>}
    </>
  )
}
