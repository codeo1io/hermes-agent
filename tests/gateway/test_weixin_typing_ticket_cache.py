"""Weixin typing tickets must not outlive their TTL or their session (cycle-3 W19).

``TypingTicketCache`` held one ticket per peer; expiry was only checked for the
entry actually read, so peers never re-queried accumulated stale entries, and
``disconnect()`` never cleared the cache — after a reconnect, a leftover ticket
from the dead iLink session could still be presented, and ``stop_typing`` with a
stale ticket no-ops (the WeChat client shows the typing indicator forever, the
original #38085 failure mode). Expiry is now swept across the cache on access,
and ``disconnect()`` clears it.
"""

import asyncio
import time

from gateway.platforms.weixin import TypingTicketCache, WeixinAdapter
from tests.gateway.test_weixin import _make_adapter


class TestTypingTicketCacheSweep:
    def test_access_sweeps_other_expired_entries(self):
        cache = TypingTicketCache(ttl_seconds=600.0)
        now = time.time()
        cache._cache["stale-user"] = ("stale-ticket", now - 700.0)
        cache._cache["live-user"] = ("live-ticket", now - 5.0)
        cache.set("fresh-user", "fresh-ticket")

        assert cache.get("other-user") is None  # plain miss
        # The never-accessed stale entry is gone too — it cannot be replayed later.
        assert "stale-user" not in cache._cache
        assert cache.get("stale-user") is None
        assert cache.get("live-user") == "live-ticket"
        assert cache.get("fresh-user") == "fresh-ticket"

    def test_clear_drops_all_entries(self):
        cache = TypingTicketCache()
        cache.set("user-a", "ticket-a")

        cache.clear()

        assert cache.get("user-a") is None
        assert cache._cache == {}


class TestDisconnectClearsTickets:
    def test_disconnect_clears_the_typing_cache(self):
        adapter: WeixinAdapter = _make_adapter()
        adapter._typing_cache.set("user-123", "ticket-123")
        assert adapter._typing_cache.get("user-123") == "ticket-123"

        asyncio.run(adapter.disconnect())

        # Tickets are scoped to the iLink session; none may leak across a reconnect.
        assert adapter._typing_cache._cache == {}
        assert adapter._typing_cache.get("user-123") is None
