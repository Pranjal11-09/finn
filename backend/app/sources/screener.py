"""screener.in company page -> structured fundamentals + links to primary documents (ARs, concall transcripts).

Screener republishes the companies' own filed numbers in a standard layout, so the numeric parts of the
research view are computed deterministically from here; the LLM never does arithmetic.
"""
from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from .. import config, db
from ..http import client

TTL = 12 * 3600


def _num(s: str) -> float | None:
    s = (s or "").replace(",", "").replace("%", "").replace("₹", "").replace("Cr.", "").strip()
    if s in ("", "-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _label(td) -> str:
    t = td.get_text(" ", strip=True).replace("\xa0", " ")
    return re.sub(r"\s*\+\s*$", "", t).strip()


def _table(section) -> dict:
    if section is None:
        return {"periods": [], "rows": {}}
    tbl = section.select_one("table.data-table")
    if tbl is None:
        return {"periods": [], "rows": {}}
    periods = [th.get_text(" ", strip=True) for th in tbl.select("thead th")][1:]
    rows = {}
    for tr in tbl.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        lab = _label(tds[0])
        if lab:
            rows[lab] = [_num(td.get_text(strip=True)) for td in tds[1:]]
    return {"periods": periods, "rows": rows}


def _ranges(section) -> dict:
    out = {}
    if section is None:
        return out
    for t in section.select("table.ranges-table"):
        head = t.select_one("th")
        if not head:
            continue
        name = head.get_text(strip=True)
        vals = {}
        for tr in t.select("tr")[1:]:
            tds = tr.find_all("td")
            if len(tds) == 2:
                vals[tds[0].get_text(strip=True).rstrip(":")] = _num(tds[1].get_text(strip=True))
        out[name] = vals
    return out


def parse(html: str, symbol: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    name = (soup.select_one("h1") or soup.new_tag("x")).get_text(strip=True)
    about = soup.select_one(".company-profile .about p") or soup.select_one(".about p")
    ratios = {}
    for li in soup.select("#top-ratios li"):
        n, v = li.select_one(".name"), li.select_one(".number")
        if n and v:
            ratios[n.get_text(strip=True)] = _num(v.get_text(strip=True))
    docs = {"annual_reports": [], "concalls": []}
    for a in soup.select("#documents .annual-reports a"):
        docs["annual_reports"].append({"title": " ".join(a.get_text(" ", strip=True).split()), "url": a.get("href")})
    for li in soup.select("#documents .concalls li"):
        date_el = li.find("div")
        item = {"date": date_el.get_text(strip=True) if date_el else ""}
        for a in li.select("a[href]"):
            kind = a.get_text(strip=True).lower()
            if kind.startswith("transcript"):
                item["transcript"] = a.get("href")
            elif kind == "ppt":
                item["ppt"] = a.get("href")
            elif kind == "rec":
                item["rec"] = a.get("href")
        docs["concalls"].append(item)
    return {
        "symbol": symbol, "name": name, "url": url,
        "about": about.get_text(" ", strip=True) if about else "",
        "ratios": ratios,
        "quarters": _table(soup.select_one("section#quarters")),
        "pl": _table(soup.select_one("section#profit-loss")),
        "growth": _ranges(soup.select_one("section#profit-loss")),
        "bs": _table(soup.select_one("section#balance-sheet")),
        "cf": _table(soup.select_one("section#cash-flow")),
        "eff": _table(soup.select_one("section#ratios")),
        "shareholding": _table(soup.select_one("section#shareholding")),
        "docs": docs,
    }


def _has_data(d: dict) -> bool:
    return any(v and any(x is not None for x in v) for v in d["quarters"]["rows"].values())


async def company(symbol: str) -> dict | None:
    symbol = symbol.upper().strip()
    if config.FIXTURES:
        p = config.FIXTURE_DIR / "screener" / f"{symbol}.html"
        if not p.exists():
            p = config.FIXTURE_DIR / "screener" / "SAMPLE.html"
        return parse(p.read_text(), symbol, f"https://www.screener.in/company/{symbol}/consolidated/")
    hit = db.kv_get("screener_v2", symbol, TTL)
    if hit:
        return hit[0]
    out = None
    for suffix in ("consolidated/", ""):
        url = f"https://www.screener.in/company/{symbol}/{suffix}"
        try:
            r = await client().get(url)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            d = parse(r.text, symbol, url)
            d["basis"] = "consolidated" if suffix else "standalone"
            if _has_data(d):
                out = d
                break
            out = out or d
        except httpx.HTTPError:
            continue
    if out:
        db.kv_set("screener_v2", symbol, out)
        return out
    stale = db.kv_get_stale("screener_v2", symbol)
    return stale[0] if stale else None
