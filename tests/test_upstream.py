"""Contract of cp0x_mcp.upstream.Fetcher: per-URL cache with TTL, stale-on-error, loud error without cache."""
import pytest

from tests.conftest import FakeClock, FakeHTTP


def make(routes=None):
    from cp0x_mcp.upstream import Fetcher

    http = FakeHTTP(routes or {"https://example.test/a": "facilitators.json"})
    clock = FakeClock()
    return Fetcher(http, clock=clock), http, clock


def test_first_get_fetches_and_second_within_ttl_uses_cache():
    fetcher, http, clock = make()
    first = fetcher.get("https://example.test/a", ttl_s=60)
    clock.advance(30)
    second = fetcher.get("https://example.test/a", ttl_s=60)
    assert http.calls == ["https://example.test/a"]
    assert first.data == second.data
    assert first.stale is False and second.stale is False
    assert second.fetched_at == first.fetched_at


def test_after_ttl_refetches():
    fetcher, http, clock = make()
    fetcher.get("https://example.test/a", ttl_s=60)
    clock.advance(61)
    again = fetcher.get("https://example.test/a", ttl_s=60)
    assert len(http.calls) == 2
    assert again.stale is False
    assert again.fetched_at == clock.now


def test_error_after_cache_returns_stale_copy():
    fetcher, http, clock = make()
    warm = fetcher.get("https://example.test/a", ttl_s=60)
    clock.advance(61)
    http.fail.add("https://example.test/a")
    stale = fetcher.get("https://example.test/a", ttl_s=60)
    assert stale.stale is True
    assert stale.data == warm.data
    assert stale.fetched_at == warm.fetched_at


def test_error_without_cache_raises_upstream_error():
    from cp0x_mcp.upstream import UpstreamError

    fetcher, http, clock = make()
    http.fail.add("https://example.test/a")
    with pytest.raises(UpstreamError) as err:
        fetcher.get("https://example.test/a", ttl_s=60)
    assert "https://example.test/a" in str(err.value)


def test_cache_is_per_url():
    routes = {"https://example.test/a": "facilitators.json", "https://example.test/b": "cp0x_resources.json"}
    fetcher, http, clock = make(routes)
    a = fetcher.get("https://example.test/a", ttl_s=60)
    b = fetcher.get("https://example.test/b", ttl_s=60)
    assert a.data != b.data
    assert http.calls == ["https://example.test/a", "https://example.test/b"]
