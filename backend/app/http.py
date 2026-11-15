"""Shared HTTP plumbing. NSE needs a warmed cookie jar; BSE needs a Referer; everyone wants a browser UA."""
from __future__ import annotations

import asyncio
import time

import httpx

UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Mobile Safari/537.36")
BASE_HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9", "Accept": "*/*"}

_client: httpx.AsyncClient | None = None
_nse_client: httpx.AsyncClient | None = None
_nse_warmed_at = 0.0
_nse_lock = asyncio.Lock()


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(headers=BASE_HEADERS, timeout=httpx.Timeout(25.0, connect=10.0),
                                    follow_redirects=True, http2=False)
    return _client


async def nse_client() -> httpx.AsyncClient:
    """NSE's JSON API 401s without cookies set by a prior page visit. Re-warm every 10 minutes."""
    global _nse_client, _nse_warmed_at
    async with _nse_lock:
        if _nse_client is None:
            _nse_client = httpx.AsyncClient(
                headers={**BASE_HEADERS, "Referer": "https://www.nseindia.com/",
                         "Accept": "application/json, text/plain, */*"},
                timeout=httpx.Timeout(20.0, connect=10.0), follow_redirects=True)
        if time.time() - _nse_warmed_at > 600:
            try:
                await _nse_client.get("https://www.nseindia.com/")
                await _nse_client.get("https://www.nseindia.com/companies-listing/corporate-filings-announcements")
                _nse_warmed_at = time.time()
            except httpx.HTTPError:
                pass
    return _nse_client
