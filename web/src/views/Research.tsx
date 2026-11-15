import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import { api, fmtCr, fmtPct } from '../api'

/* eslint-disable @typescript-eslint/no-explicit-any */
type Doc = { sid: string; title: string; url: string; kind: string }
type Sections = Record<string, any>

function Cited({ text, docs }: { text?: string; docs: Doc[] }) {
  if (!text) return null
  const parts: ReactNode[] = []
  const re = /\[(S\d+)\s*p\.?\s*(\d+)[^\]]*\]|\[N:([\w]+)\]|\b(S\d+) p\.(\d+)\b/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(text))) {
    parts.push(text.slice(last, m.index))
    const sid = m[1] || m[4], page = m[2] || m[5]
    if (sid) {
      const d = docs.find((x) => x.sid === sid)
      parts.push(<a key={m.index} className="cite" href={d ? `${d.url}#page=${page}` : undefined} target="_blank" rel="noreferrer"
        title={d?.title}>{sid} p.{page}</a>)
    } else {
      parts.push(<a key={m.index} className="cite" href="#numbers">{m[3] === 'quarterly' ? 'qtr numbers' : m[3] === 'annual' ? 'annual numbers' : 'flags'}</a>)
    }
    last = m.index + m[0].length
  }
  parts.push(text.slice(last))
  return <>{parts.map((p, i) => <Fragment key={i}>{p}</Fragment>)}</>
}

function Bars({ values, labels, fmt = fmtCr, rel = false }: { values: (number | null)[]; labels?: string[]; fmt?: (v: number | null) => string; rel?: boolean }) {
  const v0 = values.map((x) => x ?? 0)
  // ratios (margins, days) are read relative to their own range, otherwise the trend disappears
  const lo = rel && Math.min(...v0) > 0 ? Math.min(...v0) * 0.85 : 0
  const v = v0.map((x) => (x > 0 ? x - lo : x))
  const max = Math.max(...v.map(Math.abs), 1e-9)
  return (
    <>
      <div className="bars" role="img" aria-label={`Latest ${fmt(values[values.length - 1] ?? null)}`}>
        {v.map((x, i) => <div key={i} style={{ height: `${Math.max(3, (Math.abs(x) / max) * 100)}%`, opacity: x < 0 ? 0.45 : 1 }} title={`${labels?.[i] ?? ''} ${fmt(values[i])}`} />)}
      </div>
      {labels && <div className="bars-x"><span>{labels[0]}</span><span>{labels[labels.length - 1]}</span></div>}
    </>
  )
}

function Flags({ f }: { f?: { tone: string; text: string }[] }) {
  if (!f?.length) return null
  return <ul className="flags">{f.map((x, i) => <li key={i} className={x.tone}>{x.text}</li>)}</ul>
}

function Kpis({ k }: { k?: any[] }) {
  if (!k?.length) return null
  return (
    <div className="kpis">
      {k.map((x) => (
        <div className="kpi" key={x.label}>
          <small>{x.label}</small>
          <b>{x.unit === '₹ Cr' ? `₹${fmtCr(x.value)}` : `${typeof x.value === 'number' ? x.value.toLocaleString('en-IN', { maximumFractionDigits: 2 }) : x.value}${x.unit === '%' ? '%' : x.unit === 'x' ? '×' : ''}`}</b>
          {x.yoy != null && <span className={`d ${x.yoy >= 0 ? 'up' : 'down'}`}>{fmtPct(x.yoy, 0)} YoY</span>}
          {x.delta_pp != null && <span className={`d ${x.delta_pp >= 0 ? 'up' : 'down'}`}>{x.delta_pp > 0 ? '+' : ''}{x.delta_pp}pp YoY</span>}
        </div>
      ))}
    </div>
  )
}

const VERDICT: Record<string, string> = {
  delivered: 'Delivered', on_track: 'On track', partial: 'Near miss', at_risk: 'At risk', missed: 'Missed',
  off_track: 'Off track', pending: 'Too early', unverifiable: 'Can’t check',
}
const isMargin = (topic: string) => topic === 'opm' || topic === 'net_margin'
const fmtQ = (topic: string, v: number) => (isMargin(topic) ? `${v}%` : `${v > 0 ? '+' : ''}${v}%`)

export function Research({ initial, onConsumed }: { initial: { symbol: string; q?: string } | null; onConsumed: () => void }) {
  const [input, setInput] = useState('')
  const [sym, setSym] = useState('')
  const [demo, setDemo] = useState<string[]>([])
  const [sugg, setSugg] = useState<{ symbol: string; name: string }[]>([])
  const [capturedAt, setCapturedAt] = useState<number | null>(null)
  const [meta, setMeta] = useState<any>(null)
  const [sec, setSec] = useState<Sections>({})
  const [docs, setDocs] = useState<Doc[]>([])
  const [coverage, setCoverage] = useState<{sid: string; pages_loaded: number}[]>([])
  const [guid, setGuid] = useState<any[]>([])
  const [status, setStatus] = useState<{ stage: string; text: string } | null>(null)
  const [err, setErr] = useState('')
  const [q, setQ] = useState('')
  const [qa, setQa] = useState<{ q: string; a?: string; cites?: any[] }[]>([])
  const [listening, setListening] = useState(false)
  const es = useRef<EventSource | null>(null)
  const streamTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const pendingQ = useRef<string | undefined>(undefined)

  useEffect(() => { api.portfolio().then((p) => setDemo(p.research_demo)).catch(() => {}) }, [])
  useEffect(() => {
    if (initial) { pendingQ.current = initial.q; open(initial.symbol); onConsumed() }
  }, [initial])
  useEffect(() => {
    if (input.length < 2 || input === sym) { setSugg([]); return }
    const t = setTimeout(() => api.search(input).then(setSugg).catch(() => {}), 250)
    return () => clearTimeout(t)
  }, [input])
  useEffect(() => () => { es.current?.close(); clearTimeout(streamTimer.current) }, [])

  function open(s: string, live = false) {
    s = s.trim().toUpperCase()
    if (!s) return
    es.current?.close()
    clearTimeout(streamTimer.current)
    setCapturedAt(null); setCoverage([])
    setSym(s); setInput(s); setSugg([]); setMeta(null); setSec({}); setDocs([]); setGuid([]); setErr(''); setQa([])
    setStatus({ stage: 'start', text: `Opening ${s}` })
    const src = new EventSource(`/api/research/${encodeURIComponent(s)}/stream${live ? '?live=true' : ''}`)
    es.current = src
    let completed = false
    const fail = (message: string) => {
      if (es.current !== src || completed) return
      src.close(); clearTimeout(streamTimer.current); setStatus(null); setErr(message)
    }
    streamTimer.current = setTimeout(() => fail('Research timed out. Any sections already loaded remain below. Retry to continue.'), 120000)
    let usingSnapshot = false
    src.onmessage = (m) => {
      const ev = JSON.parse(m.data)
      if (ev.type === 'snapshot') { usingSnapshot = true; setCapturedAt(ev.captured_at) }
      else if (ev.type === 'meta') setMeta(ev)
      else if (ev.type === 'section') setSec((p) => ({ ...p, [ev.key]: ev.data }))
      else if (ev.type === 'sources') setDocs(ev.docs)
      else if (ev.type === 'coverage') setCoverage(ev.documents)
      else if (ev.type === 'guidance') setGuid((g) => [...g, ev.data])
      else if (ev.type === 'status') {
        setStatus(ev)
        if (ev.stage === 'done') {
          completed = true; clearTimeout(streamTimer.current); src.close()
          if (pendingQ.current) { const pq = pendingQ.current; pendingQ.current = undefined; ask(pq, s, usingSnapshot) }
        }
      } else if (ev.type === 'error') { fail(ev.text) }
    }
    src.onerror = () => fail('The research connection ended before completion. Loaded sections remain available. Retry when connected.')
  }

  async function ask(question: string, s = sym, saved = capturedAt !== null) {
    if (!question.trim() || !s) return
    setQa((x) => [{ q: question }, ...x]); setQ('')
    try {
      const r = await api.ask(s, question, saved)
      setQa((x) => x.map((y) => (y.q === question && !y.a ? { ...y, a: r.answer, cites: r.cites } : y)))
    } catch (e) {
      setQa((x) => x.map((y) => (y.q === question && !y.a ? { ...y, a: `Couldn't answer: ${(e as Error).message}` } : y)))
    }
  }

  function mic() {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SR) { alert('Voice input needs Chrome or Safari.'); return }
    const r = new SR()
    r.lang = 'en-IN'; r.interimResults = false
    r.onresult = (e: any) => { const t = e.results[0][0].transcript; setQ(t); ask(t) }
    r.onend = () => setListening(false)
    setListening(true); r.start()
  }

  const syn = sec.synthesis
  const pc = sec.promises
  const busy = status && status.stage !== 'done'
  const fin = sec.financials, tr = sec.trajectory, bs = sec.balance_sheet, cq = sec.cash_quality, biz = sec.business, snap = sec.snapshot

  return (
    <>
      <form className="search" onSubmit={(e) => { e.preventDefault(); open(input) }}>
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Any NSE symbol, e.g. ASIANPAINT" aria-label="Company symbol" autoCapitalize="characters" autoCorrect="off" />
        <button className="btn primary">Research</button>
      </form>
      {sugg.length > 0 && <div className="suggest">{sugg.map((x) => <button key={x.symbol} onClick={() => open(x.symbol)}><b>{x.symbol}</b> <span className="prose">{x.name}</span></button>)}</div>}
      {!sym && <>
        <p className="prose">Built from the company's own annual report and earnings-call transcripts. No news, no broker notes. Document references link to source pages. Model interpretations require verification.</p>
        <div className="chips">{demo.map((d) => <button key={d} className="chip" onClick={() => open(d)}>{d}</button>)}</div>
      </>}
      {err && <div role="alert" className="banner"><p className="err">{err}</p><button className="btn" onClick={() => open(sym)}>Retry research</button></div>}

      {capturedAt && <div className="banner">
        Source-backed snapshot · {new Date(capturedAt * 1000).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' })}
        {' '}<button className="btn" onClick={() => open(sym, true)}>Refresh live</button>
      </div>}
      {meta && <div className="dossier-head">
        <h1>{meta.name}</h1>
        <p>{meta.symbol}, {meta.basis || 'consolidated'} figures{snap?.kpis?.find((k: any) => k.label === 'Market Cap') && `, market cap ₹${fmtCr(snap.kpis.find((k: any) => k.label === 'Market Cap').value)} Cr`}</p>
      </div>}
      {meta && <nav className="jump" aria-label="Sections">
        <a href="#promises">Promises</a><a href="#story">Story vs numbers</a><a href="#cases">Bull & bear</a>
        <a href="#numbers">Numbers</a><a href="#trajectory">Trajectory</a><a href="#bs">Balance sheet</a><a href="#cash">Cash</a><a href="#biz">Business</a><a href="#read">Sources</a>
      </nav>}
      {busy && <div className="status"><i />{status!.text}</div>}

      {qa.map((x, i) => (
        <div className="answer" key={i}>
          <div className="q">{x.q}</div>
          {x.a ? <div><Cited text={x.a} docs={docs} /></div> : <div role="status">Reading the evidence… This may take up to 45 seconds.</div>}
        </div>
      ))}

      {meta && <section className="panel" id="promises">
        <h3>Promised vs delivered</h3>
        {!pc && busy && <>
          <p className="lead">Reading {guid.length}/{docs.filter((d) => d.kind === 'transcript').length || '…'} calls for what management promised.</p>
          {guid.flatMap((g) => (g.guidance || []).slice(0, 2).map((x: any, i: number) => (
            <div className="promise" key={g.sid + i}><q>{x.quote}</q><div className="made">{g.quarter} call <Cited text={`[${g.sid} p.${x.page}]`} docs={docs} /></div></div>)))}
          <div className="skeleton" /><div className="skeleton" style={{ width: '70%' }} />
        </>}
        {!pc && !busy && <p className="banner">No earnings-call transcripts could be read, so there are no promises to check. The numbers below still stand.</p>}
        {pc && <>
          <div className="score">
            <div className="cred">Track record<b className={pc.scorecard.credibility === 'high' ? 'up' : pc.scorecard.credibility === 'low' ? 'down' : ''}>{pc.scorecard.credibility}</b></div>
            <div>
              <p className="lead" style={{ margin: 0 }}>{pc.scorecard.one_line}</p>
              <div className="tally">
                <span><b>{pc.scorecard.delivered + pc.scorecard.on_track}</b> held</span>
                <span><b>{pc.scorecard.partial + pc.scorecard.at_risk}</b> near miss</span>
                <span><b>{pc.scorecard.missed + pc.scorecard.off_track}</b> missed</span>
                <span><b>{pc.scorecard.unverifiable}</b> can’t check</span>
              </div>
            </div>
          </div>
          {pc.revisions.map((r: any, i: number) => (
            <p className={`goalpost ${r.direction}`} key={i}><b>Goalposts moved.</b> {r.text} <Cited text={`[${r.cite}]`} docs={docs} /></p>
          ))}
          {pc.rows.filter((p: any) => p.verdict !== 'unverifiable').map((p: any, i: number) => {
            const strip = (p.track?.length || 0) >= (p.quarters?.length || 0) ? p.track : p.quarters
            return (
              <div className="promise" key={i}>
                <q>{p.quote}</q>
                <div className="made"><b>{p.promise}</b>. {p.repeats > 1 ? `Repeated in ${p.repeats} calls since the ${p.made}` : `Said in the ${p.made}`} <Cited text={`[${p.cite}]`} docs={docs} /></div>
                <div className="actual"><em>Delivered:</em> {p.actual}{p.comment && <>. {p.comment}</>}</div>
                {strip?.length > 0 && <div className="qstrip" aria-label="Quarter by quarter">
                  {strip.map((x: any) => <span key={x.q} className={x.ok ? (x.beat ? 'beat' : 'ok') : 'miss'}><small>{x.q}</small>{fmtQ(p.topic, x.value)}</span>)}
                </div>}
                <span className={`vstamp v-${p.verdict}`}>{VERDICT[p.verdict] || p.verdict}</span>
              </div>
            )
          })}
          {pc.rows.some((p: any) => p.verdict === 'unverifiable') && <details className="drawer" style={{ marginTop: 10 }}>
            <summary><span>{pc.rows.filter((p: any) => p.verdict === 'unverifiable').length} promises the financials can’t test</span><span>Show</span></summary>
            <ul className="untestable">{pc.rows.filter((p: any) => p.verdict === 'unverifiable').map((p: any, i: number) => (
              <li key={i}><b>{p.promise}</b>: {p.actual}. <Cited text={`[${p.cite}]`} docs={docs} /></li>))}</ul>
          </details>}
          <p className="src">{pc.method}</p>
        </>}
      </section>}

      {syn?.error && <p role="status" className="banner">{syn.error}</p>}
      {syn?.narrative_vs_numbers && <section className="panel" id="story">
        <h3>Their story vs the numbers</h3>
        {syn.narrative_vs_numbers.map((n: any, i: number) => (
          <div className="nvn" key={i}>
            <div><span className={`agree-${n.agree}`}>{n.agree === 'yes' ? 'Agrees' : n.agree === 'no' ? 'Diverges' : 'Partly'}</span>: “{n.claim}” <Cited text={`[${n.cite}]`} docs={docs} /></div>
            <div className="says">Numbers: {n.numbers} <Cited text={`[${n.num_cite}]`} docs={docs} /></div>
          </div>
        ))}
        {!!syn.guidance_now?.length && <>
          <h3 style={{ marginTop: 14, fontSize: 16 }}>Guidance on the table</h3>
          <ul className="flags">{syn.guidance_now.map((g: any, i: number) => <li key={i}>{g.metric}: <b>{g.target}</b> {g.period && `for ${g.period}`} <Cited text={`[${g.cite}]`} docs={docs} /></li>)}</ul>
        </>}
      </section>}

      {syn?.bull && <section className="panel" id="cases">
        <div className="cases">
          <div><h4 className="up">Bull case</h4><ul>{syn.bull.map((b: string, i: number) => <li key={i}><Cited text={b} docs={docs} /></li>)}</ul></div>
          <div><h4 className="down">Bear case</h4><ul>{syn.bear.map((b: string, i: number) => <li key={i}><Cited text={b} docs={docs} /></li>)}</ul></div>
          {syn.watch && <div><h4>Check next quarter</h4><ul>{syn.watch.map((b: string, i: number) => <li key={i}><Cited text={b} docs={docs} /></li>)}</ul></div>}
        </div>
      </section>}

      {fin && <section className="panel" id="numbers">
        <h3>{fin.title}</h3>
        <Kpis k={fin.kpis} />
        {fin.quarterly && <div className="series" style={{ marginTop: 12 }}>
          <div><h5>Revenue, 12 quarters</h5><Bars values={fin.quarterly.revenue} labels={fin.quarterly.periods} /></div>
          <div><h5>Margin %</h5><Bars values={fin.quarterly.opm} labels={fin.quarterly.periods} fmt={(v) => `${v}%`} rel /></div>
        </div>}
      </section>}

      {tr && <section className="panel" id="trajectory">
        <h3>Trajectory</h3>
        {tr.cagr?.['3y'] && <p className="lead">3-year growth: revenue {fmtPct(tr.cagr['3y'].Revenue)} a year, profit {fmtPct(tr.cagr['3y'].PAT)}{tr.cagr['5y'] ? `; 5-year: ${fmtPct(tr.cagr['5y'].Revenue)} and ${fmtPct(tr.cagr['5y'].PAT)}` : ''}.</p>}
        <div className="series">
          {['Revenue', 'PAT', 'Margin %', 'EPS'].map((k) => tr.series[k]?.length ? <div key={k}><h5>{k}<span>{k === 'Margin %' ? `${tr.series[k].at(-1)}%` : fmtCr(tr.series[k].at(-1))}</span></h5><Bars values={tr.series[k]} labels={tr.periods} rel={k === 'Margin %'} /></div> : null)}
        </div>
        <Flags f={tr.flags} />
      </section>}

      {bs && <section className="panel" id="bs">
        <h3>Balance sheet</h3>
        <Kpis k={bs.kpis} />
        <div className="series" style={{ marginTop: 10 }}>
          {bs.series.Borrowings?.length > 0 && <div><h5>Borrowings</h5><Bars values={bs.series.Borrowings} labels={bs.periods} /></div>}
          {(bs.wc['Cash Conversion Cycle'] || bs.wc['Working Capital Days']) && <div><h5>Cash cycle, days</h5><Bars values={bs.wc['Cash Conversion Cycle'] || bs.wc['Working Capital Days']} labels={bs.wc.periods} fmt={(v) => `${v} d`} rel /></div>}
        </div>
        <Flags f={bs.flags} />
      </section>}

      {cq && <section className="panel" id="cash">
        <h3>Do profits turn into cash?</h3>
        <Kpis k={cq.kpis} />
        <div className="series" style={{ marginTop: 10 }}>
          <div><h5>Operating cash</h5><Bars values={cq.series.CFO} labels={cq.periods} /></div>
          <div><h5>Net profit</h5><Bars values={cq.series.PAT} labels={cq.periods} /></div>
        </div>
        <Flags f={cq.flags} />
        <p className="src">{cq.note}</p>
      </section>}

      {(biz || snap) && <section className="panel" id="biz">
        <h3>The business</h3>
        <p className="lead">{biz?.what ? <Cited text={biz.what} docs={docs} /> : snap?.about}</p>
        {!!biz?.segments?.length && <>
          <div className="seg">{biz.segments.filter((s: any) => s.share_pct).map((s: any) => <div key={s.name} style={{ width: `${s.share_pct}%` }} />)}</div>
          <ul className="flags">{biz.segments.map((s: any) => <li key={s.name}><b>{s.name}</b>{s.share_pct != null && ` ${s.share_pct}%`}{s.note && `: ${s.note}`} <Cited text={s.cite ? `[${s.cite}]` : ''} docs={docs} /></li>)}</ul>
          {biz.mix_basis && <p className="src">Mix as of {biz.mix_basis}</p>}
        </>}
        {!!biz?.drivers?.length && <ul className="flags">{biz.drivers.map((d: string, i: number) => <li key={i}><Cited text={d} docs={docs} /></li>)}</ul>}
        <Kpis k={snap?.kpis?.filter((k: any) => k.label !== 'Market Cap')} />
      </section>}

      {docs.length > 0 && <section className="panel" id="read">
        <h3>Source documents</h3>
        <p className="src">Analysis uses selected excerpts, not every page. Page links let you check the original context; a valid citation alone does not prove an interpretation.</p>
        <ul className="sources">
          {docs.map((d) => { const g = guid.find((x) => x.sid === d.sid); return (
            <li key={d.sid}><span className="cite">{d.sid}</span> <a href={d.url} target="_blank" rel="noreferrer">{d.title}</a>
              {coverage.find(c => c.sid === d.sid)?.pages_loaded === 0 && <span className="err"> — could not read; excluded from analysis</span>}
              {g?.pages_read && <span className="prose">, {g.pages_read} of {g.pages_total} pages sent to the model</span>}</li>) })}
          <li><span className="cite">numbers</span> <a href={meta?.url} target="_blank" rel="noreferrer">Filed financials via screener.in</a></li>
        </ul>
      </section>}

      {sym && meta && <div className="ask">
        <form onSubmit={(e) => { e.preventDefault(); ask(q) }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Ask about ${sym}`} aria-label="Ask a question" />
          <button type="button" className={listening ? 'live' : ''} onClick={mic} aria-label="Ask by voice">{listening ? 'Listening' : 'Mic'}</button>
          <button className="send" disabled={!q.trim()}>Ask</button>
        </form>
      </div>}
    </>
  )
}
