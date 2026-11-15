export type Tier = 'act' | 'know' | 'routine'

export interface Item {
  id: string; symbol: string; name?: string; company?: string; ts: string; headline: string; text: string
  url: string; source: string; category: string; subtype: string; classified_by: string
  score: number; tier: Tier; why: string[]; state: string; line?: string
}

export interface Eod {
  symbol: string; name?: string; date: string; close: number; chg_pct: number; volume: number; avg_volume: number
  vol_mult: number | null; sigma: number | null; hi52: number; lo52: number; spark: number[]; stale: boolean
}

export interface Digest {
  hours: number; items: Item[]; counts: Record<string, number>; routine_by_category: Record<string, number>
  headline: string; tape: Eod[]; movers: string[]; feed_status: Record<string, string>; fixtures: boolean
}

export interface Metric { key: string; label: string; cur: number | null; prev: number | null; yago: number | null
  qoq: number | null; yoy: number | null; margin?: number | null; margin_yago?: number | null }

export interface ResultsCard { metrics: Metric[]; source: string; periods?: Record<string, string>; basis?: string
  unit?: string; page?: number; source_url?: string; verification?: string; calculation?: string; verdict?: string; check?: { ok: boolean; vs: string; diff_pct: number }; note?: string; error?: string }

export interface MgmtChange { person: string; role: string; action: string; effective?: string; reason?: string
  profile?: string; prior_roles?: string[]; linkedin?: string; web?: { bio: string; urls: string[] } }

export interface Enrichment { id: string; results?: ResultsCard; mgmt?: { changes: MgmtChange[] }; line?: string }

export interface Settings {
  window_hours: number; alert_categories: string[]; volume_multiple: number; volume_lookback: number
  price_move_pct: number; min_alert_priority: number; category_bias: Record<string, number>
  extra_symbols: string[]; removed_symbols: string[]
}

export interface Alert { id: string; kind: string; symbol: string; title: string; why: string
  payload: { url?: string; item_id?: string; eod?: Eod }; ts: number; sent: boolean }

async function j<T>(r: Promise<Response>): Promise<T> {
  const res = await r
  if (!res.ok) throw new Error((await res.text()).slice(0, 200) || res.statusText)
  return res.json()
}

const post = (url: string, body: unknown) =>
  fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export const api = {
  digest: (hours: number) => j<Digest>(fetch(`/api/digest?hours=${hours}`)),
  enrich: (id: string) => j<Enrichment>(fetch(`/api/item/enrich?id=${encodeURIComponent(id)}`)),
  triage: (id: string, state: string) => j<{ category_bias: Record<string, number> }>(post('/api/triage', { id, state })),
  alerts: () => j<{ alerts: Alert[]; settings: Settings }>(fetch('/api/alerts')),
  scan: () => j<{ new: number; pushed: number; checked: number }>(post('/api/alerts/scan', {})),
  settings: () => j<Settings>(fetch('/api/settings')),
  saveSettings: (p: Partial<Settings>) => j<Settings>(post('/api/settings', p)),
  portfolio: () => j<{ holdings: { symbol: string; name: string; sector: string; band: string }[]; research_demo: string[] }>(fetch('/api/portfolio')),
  search: (q: string) => j<{ symbol: string; name: string }[]>(fetch(`/api/search?q=${encodeURIComponent(q)}`)),
  ask: (symbol: string, q: string, saved = false) => j<{ answer: string; confidence?: string; cites: { sid: string; page: number; title: string }[] }>(post(`/api/research/${encodeURIComponent(symbol)}/ask`, { q, saved })),
  usage: () => j<{ models: { tier: string; model: string; calls: number; in_tokens: number; out_tokens: number; cache_hits: number }[]
    classifier: { rules: number; llm: number }; cheap: string; strong: string; llm_ready: boolean; provider: string }>(fetch('/api/usage')),
}

export const CAT: Record<string, string> = {
  results: 'Results', 'M&A': 'M&A', fund_raise: 'Fund-raise', management_change: 'Management change',
  litigation: 'Legal & regulatory', insider_trading: 'Insider trade', earnings_call: 'Earnings call',
  investor_meetings: 'Investor meetings', credit_rating: 'Credit rating', dividend: 'Dividend',
  bonus_split: 'Bonus / split', capex: 'Capex', press_release: 'Company update', postal_ballot: 'Postal ballot',
  agm_egm: 'AGM / EGM', pledging: 'Pledging', unclassified: 'Paperwork',
}

export const fmtCr = (v: number | null | undefined) => {
  if (v == null) return '–'
  return v.toLocaleString('en-IN', { maximumFractionDigits: Math.abs(v) < 10 ? 1 : 0 })
}
export const fmtPct = (v: number | null | undefined, d = 1) => (v == null ? '–' : `${v > 0 ? '+' : ''}${v.toFixed(d)}%`)
export const ago = (iso: string) => {
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (m < 60) return `${Math.max(m, 1)}m ago`
  const h = Math.round(m / 60)
  return h < 24 ? `${h}h ago` : `${Math.round(h / 24)}d ago`
}
