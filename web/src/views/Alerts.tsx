import { useEffect, useRef, useState } from 'react'
import { api, CAT, type Alert, type Settings } from '../api'

const WATCHABLE = ['results', 'M&A', 'management_change', 'fund_raise', 'credit_rating', 'litigation', 'pledging',
  'capex', 'insider_trading', 'bonus_split', 'dividend', 'press_release']

function Num({ v, step, min, max, onChange, label }: { v: number; step: number; min: number; max: number; onChange: (n: number) => void; label: string }) {
  return <input type="number" aria-label={label} value={v} step={step} min={min} max={max} inputMode="decimal"
    onChange={(e) => { const n = parseFloat(e.target.value); if (!Number.isNaN(n)) onChange(n) }} />
}

export function Alerts({ onAsk }: { onAsk: (s: string, q?: string) => void }) {
  const [s, setS] = useState<Settings | null>(null)
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const [tg, setTg] = useState(false)
  const t = useRef<number>(0)

  const load = () => api.alerts().then((r) => { setAlerts(r.alerts); setS(r.settings) })
  useEffect(() => { load(); fetch('/api/health').then((r) => r.json()).then((h) => setTg(!!h.telegram)).catch(() => {}) }, [])

  const patch = (p: Partial<Settings>) => {
    if (!s) return
    const next = { ...s, ...p }
    setS(next)
    clearTimeout(t.current)
    t.current = window.setTimeout(() => api.saveSettings(next).then(() => setNote('Saved. Applies from the next check.')), 400)
  }
  const toggle = (c: string) => s && patch({ alert_categories: s.alert_categories.includes(c) ? s.alert_categories.filter((x) => x !== c) : [...s.alert_categories, c] })
  const check = async () => {
    setBusy(true); setNote('')
    try { const r = await api.scan(); setNote(r.new ? `${r.new} new alert${r.new > 1 ? 's' : ''}${r.pushed ? `, ${r.pushed} sent to Telegram` : ''}.` : 'Nothing new crossed your lines.'); await load() }
    catch (e) { setNote(`Check failed: ${(e as Error).message}`) }
    setBusy(false)
  }

  return (
    <>
      <div className="sec-h" style={{ marginTop: 20 }}><h2>Your lines in the sand</h2></div>
      {s && <div className="rule-card">
        Ping me when a stock trades more than <Num label="Volume multiple" v={s.volume_multiple} step={0.5} min={1} max={10} onChange={(n) => patch({ volume_multiple: n })} />× its{' '}
        <Num label="Lookback days" v={s.volume_lookback} step={5} min={5} max={60} onChange={(n) => patch({ volume_lookback: Math.round(n) })} />-day average volume, or moves more than{' '}
        ±<Num label="Price move percent" v={s.price_move_pct} step={0.5} min={0.5} max={20} onChange={(n) => patch({ price_move_pct: n })} />% in a day.
        <div style={{ marginTop: 10 }}>And when any of these get filed:</div>
        <div className="chips">
          {WATCHABLE.map((c) => <button key={c} className="chip" aria-pressed={s.alert_categories.includes(c)} onClick={() => toggle(c)}>{CAT[c]}</button>)}
        </div>
      </div>}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '12px 0' }}>
        <button className="btn primary" onClick={check} disabled={busy}>{busy ? 'Checking…' : 'Check now'}</button>
        <span className="prose">{note || (tg ? 'Alerts also go to your Telegram.' : 'Automatic alerts require the scheduler and Telegram setup.')}</span>
      </div>

      <div className="sec-h"><h2>Triggered</h2><span>{alerts.length}</span></div>
      {alerts.length === 0 && <div className="empty"><h3>No alerts yet.</h3><p>Tap Check now to scan today's filings and closing prices against your lines.</p></div>}
      {alerts.map((a) => (
        <div className="alert" key={a.id}>
          <div className="ic" aria-hidden>{a.kind === 'volume' ? 'V' : a.kind === 'price' ? '%' : 'F'}</div>
          <div>
            <h4>{a.title}</h4>
            <p>{a.why}</p>
            <small>
              {new Date(a.ts * 1000).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}
              {a.sent && ', sent to Telegram'}
              {' '}<button className="btn" style={{ padding: '1px 8px', fontSize: 12, marginLeft: 6 }} onClick={() => onAsk(a.symbol)}>Research</button>
              {a.payload.url && <> <a href={a.payload.url} target="_blank" rel="noreferrer">Filing</a></>}
            </small>
          </div>
        </div>
      ))}
    </>
  )
}
