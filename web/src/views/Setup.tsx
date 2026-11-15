import { useEffect, useState } from 'react'
import { api, CAT, type Settings } from '../api'

type Usage = Awaited<ReturnType<typeof api.usage>>
type Holding = { symbol: string; name: string; sector: string; band: string }

export function Setup() {
  const [h, setH] = useState<Holding[]>([])
  const [s, setS] = useState<Settings | null>(null)
  const [u, setU] = useState<Usage | null>(null)
  const [add, setAdd] = useState('')

  const load = () => {
    api.portfolio().then((p) => setH(p.holdings)).catch(() => {})
    api.settings().then(setS).catch(() => {})
    api.usage().then(setU).catch(() => {})
  }
  useEffect(load, [])

  const save = async (p: Partial<Settings>) => { setS(await api.saveSettings(p)); api.portfolio().then((x) => setH(x.holdings)) }
  const remove = (sym: string) => s && save({ removed_symbols: [...s.removed_symbols, sym], extra_symbols: s.extra_symbols.filter((x) => x !== sym) })
  const addSym = () => {
    const x = add.trim().toUpperCase()
    if (!x || !s) return
    save({ extra_symbols: [...new Set([...s.extra_symbols, x])], removed_symbols: s.removed_symbols.filter((y) => y !== x) })
    setAdd('')
  }

  const calls = u?.models.reduce((a, m) => a + m.calls - m.cache_hits, 0) ?? 0
  const hits = u?.models.reduce((a, m) => a + m.cache_hits, 0) ?? 0
  const tok = u?.models.reduce((a, m) => a + m.in_tokens + m.out_tokens, 0) ?? 0
  const rulesShare = u && u.classifier.rules + u.classifier.llm ? Math.round((u.classifier.rules / (u.classifier.rules + u.classifier.llm)) * 100) : null
  const bias = Object.entries(s?.category_bias || {}).filter(([, v]) => v)

  return (
    <>
      <div className="sec-h" style={{ marginTop: 20 }}><h2>What it cost to run</h2><span>{u?.llm_ready ? u.provider : 'no model key set'}</span></div>
      <div className="meter">
        <div><b>{calls}</b><small>model calls made</small></div>
        <div><b>{hits}</b><small>answered from cache, free</small></div>
        <div><b>{tok >= 1000 ? `${(tok / 1000).toFixed(1)}k` : tok}</b><small>tokens in and out</small></div>
        <div><b>{rulesShare != null ? `${rulesShare}%` : '–'}</b><small>filings sorted by rules, no model</small></div>
      </div>
      {u && <p className="prose">Bulk reading uses {u.cheap}. Only the final research judgement and your questions use {u.strong}.</p>}

      {bias.length > 0 && <>
        <div className="sec-h"><h2>What FINN has learned</h2><button className="btn" onClick={() => save({ category_bias: {} })}>Forget</button></div>
        <div className="list">{bias.map(([c, v]) => <div className="row" key={c}>{CAT[c] || c}<span>{v > 0 ? `ranked higher (+${v})` : `ranked lower (${v})`}</span></div>)}</div>
      </>}

      <div className="sec-h"><h2>Portfolio</h2><span>{h.length} holdings</span></div>
      <form className="search" style={{ margin: '0 0 10px' }} onSubmit={(e) => { e.preventDefault(); addSym() }}>
        <input value={add} onChange={(e) => setAdd(e.target.value)} placeholder="Add an NSE symbol" aria-label="Add symbol" />
        <button className="btn primary">Add</button>
      </form>
      <div className="list">
        {h.map((x) => <div className="row" key={x.symbol}><b>{x.symbol}</b><span>{x.sector} {x.band && `(${x.band.toLowerCase()} cap)`}</span><button onClick={() => remove(x.symbol)} aria-label={`Remove ${x.symbol}`}>Remove</button></div>)}
      </div>

      <div className="sec-h"><h2>Get alerts on your phone</h2></div>
      <p className="prose">FINN checks filings through the day and prices after the close. To get alerts as Telegram messages, create a bot with @BotFather and set <code>TELEGRAM_BOT_TOKEN</code> and <code>TELEGRAM_CHAT_ID</code> on the server. To keep FINN on your home screen, use your browser's "Add to Home Screen".</p>
    </>
  )
}
