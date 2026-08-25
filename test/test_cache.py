"""

    Tests for the Redis cache wrapper (src/cache.py)
    Copyright © 2026 Miðeind ehf.

    Verifies that flush() deletes exactly the application's own keys
    (_OWNED_KEY_PATTERNS) and leaves other tenants' keys untouched,
    since the Valkey/Redis server may be shared with other applications.

"""

from __future__ import annotations

from cache import memcache


def test_flush_is_scoped_to_owned_keys() -> None:
    r = memcache.get_redis_client()
    # Keys the application owns, one per pattern family
    memcache.set("0-99", {"x": 1}, time=60, namespace="userlist")
    memcache.set("human", [1, 2], time=60, namespace="rating")
    memcache.set("all:is_IS", [1], time=60, namespace="rating-locale")
    memcache.init_set("live:is_IS", {"u1", "u2"}, time=60)
    # Simulated NDB global-cache entry (prefix from google/cloud/ndb/_cache.py)
    r.set(b"NDB30\x01\x02fake-entity-key", b"payload", ex=60)
    # A foreign tenant's key, which flush() must leave alone
    r.set("gsapi:foreign-key", b"untouchable", ex=60)
    try:
        memcache.flush()
        assert memcache.get("0-99", namespace="userlist") is None
        assert memcache.get("human", namespace="rating") is None
        assert memcache.get("all:is_IS", namespace="rating-locale") is None
        assert memcache.query_set("live:is_IS", ["u1", "u2"]) == [False, False]
        assert r.get(b"NDB30\x01\x02fake-entity-key") is None
        assert r.get("gsapi:foreign-key") == b"untouchable"
    finally:
        r.delete("gsapi:foreign-key")

