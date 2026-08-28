from app.retrieve.rephrase_cache import BoundedCache


def test_miss_returns_none():
    cache = BoundedCache()
    assert cache.get("missing") is None


def test_set_then_get_round_trips():
    cache = BoundedCache()
    cache.set("k", ["a", "b"])
    assert cache.get("k") == ["a", "b"]


def test_tuple_keys_work():
    """Both real callers key on tuples (question, provider, model, ...)."""
    cache = BoundedCache()
    cache.set(("q", "anthropic", "haiku", 1), "рough")
    assert cache.get(("q", "anthropic", "haiku", 1)) == "рough"
    assert cache.get(("q", "anthropic", "haiku", 2)) is None


def test_clear_empties_the_cache():
    cache = BoundedCache()
    cache.set("k", "v")
    cache.clear()
    assert cache.get("k") is None
    assert len(cache) == 0


def test_evicts_the_least_recently_used_entry_once_over_capacity():
    cache = BoundedCache(max_size=2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)  # over capacity — "a" is the least recently used, evicted

    assert cache.get("a") is None
    assert cache.get("b") == 2
    assert cache.get("c") == 3


def test_reading_an_entry_counts_as_using_it_for_eviction_purposes():
    cache = BoundedCache(max_size=2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.get("a")  # "a" is now more recently used than "b"
    cache.set("c", 3)  # "b" is the least recently used now, not "a"

    assert cache.get("a") == 1
    assert cache.get("b") is None
    assert cache.get("c") == 3
