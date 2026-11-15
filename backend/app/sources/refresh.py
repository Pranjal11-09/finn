"""Keep slow upstream feeds off the hosted reviewer's request path."""
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

_running: dict[str, asyncio.Task] = {}
_attempted: dict[str, float] = {}
_limit = asyncio.Semaphore(6)
_COOLDOWN = 120


def schedule(key: str, fetch: Callable[[], Awaitable]) -> None:
    now = time.monotonic()
    if key in _running or now - _attempted.get(key, -_COOLDOWN) < _COOLDOWN:
        return
    if len(_running) >= 100:
        return
    for old_key, attempted in list(_attempted.items()):
        if now - attempted >= _COOLDOWN:
            _attempted.pop(old_key, None)
    _attempted[key] = now

    async def run():
        try:
            async with _limit:
                await fetch()
        except Exception:
            logging.getLogger(__name__).exception("Background refresh failed for %s", key)
        finally:
            _running.pop(key, None)

    _running[key] = asyncio.create_task(run())
