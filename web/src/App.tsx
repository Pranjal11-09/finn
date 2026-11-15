import { useEffect, useState, type ReactElement } from 'react'
import { Alerts } from './views/Alerts'
import { Brief } from './views/Brief'
import { Research } from './views/Research'
import { Setup } from './views/Setup'

type Tab = 'brief' | 'alerts' | 'research' | 'setup'

const ICONS: Record<Tab, ReactElement> = {
  brief: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="4" y="3.5" width="16" height="17" rx="2" /><path d="M8 8.5h8M8 12h8M8 15.5h5" /></svg>,
  alerts: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z" /><path d="M10 20.5a2 2 0 0 0 4 0" /></svg>,
  research: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="10.5" cy="10.5" r="6" /><path d="m15 15 5 5" /></svg>,
  setup: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M4 7h10M18 7h2M4 17h4M12 17h8" /><circle cx="16" cy="7" r="2" /><circle cx="10" cy="17" r="2" /></svg>,
}
const LABEL: Record<Tab, string> = { brief: 'Brief', alerts: 'Alerts', research: 'Research', setup: 'Setup' }

export default function App() {
  const [tab, setTab] = useState<Tab>(() => (location.hash.slice(1) as Tab) || 'brief')
  const [jump, setJump] = useState<{ symbol: string; q?: string } | null>(null)
  const [count, setCount] = useState(0)

  useEffect(() => { history.replaceState(null, '', `#${tab}`); window.scrollTo(0, 0) }, [tab])
  useEffect(() => { document.title = count ? `(${count}) FINN` : 'FINN' }, [count])

  const ask = (symbol: string, q?: string) => { setJump({ symbol, q }); setTab('research') }

  return (
    <div className="app">
      <main>
        <div hidden={tab !== 'brief'}><Brief onAsk={ask} onCount={setCount} /></div>
        {tab === 'alerts' && <Alerts onAsk={ask} />}
        <div hidden={tab !== 'research'}><Research initial={jump} onConsumed={() => setJump(null)} /></div>
        {tab === 'setup' && <Setup />}
      </main>
      <nav className="tabs" aria-label="Main">
        <div>
          {(Object.keys(LABEL) as Tab[]).map((t) => (
            <button key={t} aria-current={tab === t ? 'page' : undefined} onClick={() => setTab(t)}>
              {ICONS[t]}{LABEL[t]}
              {t === 'brief' && count > 0 && <span className="dot">{count}</span>}
            </button>
          ))}
        </div>
      </nav>
    </div>
  )
}
