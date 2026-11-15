import { useEffect, useRef, useState } from 'react'
import { api, ago, CAT, fmtCr, fmtPct, type Enrichment, type Item, type MgmtChange, type ResultsCard } from '../api'

const STAMP: Record<string, string> = { done: 'Filed', keep: 'Kept', less: 'Noted' }

export function ResultsTable({ r }: { r: ResultsCard }) {
  if (r.error) return <p className="err">{r.error}</p>
  const p = r.periods || {}
  return (
    <>
      <table className="res">
        <thead><tr><th>₹ Cr</th><th>{p.current || 'This qtr'}</th><th>QoQ</th><th>YoY</th></tr></thead>
        <tbody>
          {r.metrics.map((m) => (
            <tr key={m.key}>
              <td>{m.label}{m.margin != null && <span className="m">{m.margin}% margin{m.margin_yago != null && `, was ${m.margin_yago}%`}</span>}</td>
              <td>{fmtCr(m.cur)}</td>
              <td className={(m.qoq ?? 0) >= 0 ? 'up' : 'down'}>{fmtPct(m.qoq, 0)}</td>
              <td className={(m.yoy ?? 0) >= 0 ? 'up' : 'down'}>{fmtPct(m.yoy, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <details className="drawer">
        <summary>Compare quarters &amp; check evidence</summary>
        <div className="table-scroll"><table className="res">
          <thead><tr><th>₹ Cr</th><th>{p.current}</th><th>{p.previous}</th><th>{p.year_ago}</th></tr></thead>
          <tbody>{r.metrics.map(m => <tr key={m.key}><td>{m.label}</td><td>{fmtCr(m.cur)}</td><td>{fmtCr(m.prev)}</td><td>{fmtCr(m.yago)}</td></tr>)}</tbody>
        </table></div>
        {r.source_url && <a href={`${r.source_url}#page=${r.page || 1}`} target="_blank" rel="noreferrer">Open source page {r.page}</a>}
        <p className="src">{r.verification || 'Model extraction; check the original filing.'}</p>
        {r.calculation && <p className="src">{r.calculation}</p>}
      </details>
      {r.verdict && <p className="verdict">{r.verdict}</p>}
      <p className="src">
        {r.basis && `${r.basis[0].toUpperCase()}${r.basis.slice(1)}, `}from {r.source}{r.page ? `, p.${r.page}` : ''}
        {r.check && (r.check.ok ? <span className="ok">, matches {r.check.vs}</span> : <span className="down">, differs from {r.check.vs} by {r.check.diff_pct}%</span>)}
        {r.note && <><br />{r.note}</>}
      </p>
    </>
  )
}

export function Person({ c }: { c: MgmtChange }) {
  const initials = (c.person || '?').split(' ').filter(Boolean).slice(-2).map((x) => x[0]).join('')
  return (
    <div className="person">
      <div className="avatar" aria-hidden>{initials}</div>
      <div>
        <h4>{c.person}</h4>
        <p><b>{c.action[0]?.toUpperCase() + c.action.slice(1)}</b> as {c.role}{c.effective ? `, effective ${c.effective}` : ''}{c.reason ? `. ${c.reason}` : ''}</p>
        {c.profile ? <p>{c.profile}</p> : !c.web?.bio && c.action === 'appointed' && <p className="src">The filing discloses no background for this person.</p>}
        {c.web?.bio && <p>{c.web.bio} <a className="cite" href={c.web.urls?.[0]} target="_blank" rel="noreferrer">web</a></p>}
        {!!c.prior_roles?.length && <ul>{c.prior_roles.slice(0, 3).map((r) => <li key={r}>{r}</li>)}</ul>}
        {c.linkedin && <p><a href={c.linkedin} target="_blank" rel="noreferrer">Find on LinkedIn</a></p>}
      </div>
    </div>
  )
}

export function Slip({ item, onTriage, onAsk }: { item: Item; onTriage: (id: string, s: string) => void; onAsk: (sym: string, q: string) => void }) {
  const [enr, setEnr] = useState<Enrichment | null>(null)
  const [err, setErr] = useState('')
  const [stamp, setStamp] = useState<string | null>(item.state === 'keep' ? 'keep' : null)
  const [filed, setFiled] = useState(false)
  const [dx, setDx] = useState(0)
  const start = useRef<number | null>(null)
  const ref = useRef<HTMLElement>(null)

  useEffect(() => {
    let live = true
    api.enrich(item.id).then((e) => live && setEnr(e)).catch((e) => live && setErr(String(e.message || e)))
    return () => { live = false }
  }, [item.id])

  const act = async (s: string) => {
    try { await api.triage(item.id, s) }
    catch { setErr('Your action could not be saved. Please retry.'); return }
    setStamp(s)
    if (s !== 'keep') {
      if (ref.current) ref.current.style.maxHeight = `${ref.current.offsetHeight}px`
      setTimeout(() => setFiled(true), 520)
      setTimeout(() => onTriage(item.id, s), 900)
    }
  }

  const q = item.category === 'results' ? 'What did management say drove this quarter, and is it repeatable?'
    : item.category === 'management_change' ? 'What has management said about leadership and succession?'
    : `What has management said about ${CAT[item.category]?.toLowerCase() || 'this'}?`

  return (
    <article ref={ref} className={`slip${filed ? ' filed' : ''}`} style={{ transform: dx ? `translateX(${dx}px) rotate(${dx / 60}deg)` : undefined }}
      onPointerDown={(e) => { if (e.pointerType !== 'mouse') start.current = e.clientX }}
      onPointerMove={(e) => { if (start.current != null) setDx(Math.max(-120, Math.min(120, e.clientX - start.current))) }}
      onPointerUp={() => { if (dx > 90) act('done'); else if (dx < -90) act('less'); start.current = null; setDx(0) }}
      onPointerCancel={() => { start.current = null; setDx(0) }}>
      {stamp && <div className="stamp press" aria-live="polite">{STAMP[stamp]}</div>}
      <div className="slip-top">
        <span className="sym">{item.symbol}</span>
        <span className="co">{item.name}</span>
        <time dateTime={item.ts}>{ago(item.ts)}</time>
      </div>
      <span className="kind">{CAT[item.category] || item.category}</span>
      {!enr && <p className="headline">{item.text || item.headline}</p>}
      {!enr && !err && <><div className="skeleton" style={{ width: '92%' }} /><div className="skeleton" style={{ width: '64%' }} /></>}
      {err && <p role="alert" className="err">{err}</p>}
      {enr?.results && <ResultsTable r={enr.results} />}
      {enr?.mgmt && (enr.mgmt.changes.length ? enr.mgmt.changes.map((c, i) => <Person key={i} c={c} />) : <p className="headline">{item.text || item.headline}</p>)}
      {enr?.line && <p className="verdict">{enr.line}</p>}
      <div className="why" aria-label="Why this is here">{item.why.slice(1).map((w) => <span key={w}>{w}</span>)}</div>
      <div className="acts">
        <button onClick={() => act('done')}>Done</button>
        <button onClick={() => act('keep')}>Keep</button>
        <button onClick={() => act('less')} title="Rank this kind of filing lower for me">Less like this</button>
        <span className="grow" />
        <button onClick={() => onAsk(item.symbol, q)}>Ask</button>
        {item.url && <a href={item.url} target="_blank" rel="noreferrer">Filing</a>}
      </div>
    </article>
  )
}
