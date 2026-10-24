"""Contracts added after the Codex review of m4 and the controller's read of m5: the status of the originating declaration
survives close-only and regional matches, and the negative cache does not grow without bound."""
import pytest

from tests.conftest import FakeClock, FakeHTTP

HOST_A = "https://cp0x.test"


# ---------- 1. close-only and regional matches keep the declaration's evidence status ----------

def test_declared_status_is_preserved_for_close_only_and_regional_matches(service):
    th = {i["id"]: i for i in service.list_restricted_interfaces("TH")["interfaces"]}
    assert th["polymarket"]["scope"] == "close_only" and th["polymarket"]["declared_status"] == "yes"
    ca = {i["id"]: i for i in service.list_restricted_interfaces("CA")["interfaces"]}
    assert ca["hyperliquid"]["scope"] == "regional" and ca["hyperliquid"]["declared_status"] == "yes"
    ua = {i["id"]: i for i in service.list_restricted_interfaces("UA")["interfaces"]}
    assert ua["polymarket"]["scope"] == "regional" and ua["polymarket"]["declared_status"] == "yes"
    assert ua["uniswap"]["scope"] == "national" and ua["uniswap"]["declared_status"] == "reported"
    for country in ("TH", "CA", "UA", "US", "BR"):
        for item in service.list_restricted_interfaces(country)["interfaces"]:
            if item["scope"] == "observed":  # no declaration matched: nothing to report
                assert item["declared_status"] is None
            else:
                assert item["declared_status"] is not None


def test_country_match_carries_the_declaration_status(service):
    assert service.check_interface_restrictions("polymarket", country="TH")["country_match"]["status"] == "yes"
    assert service.check_interface_restrictions("hyperliquid", country="ca")["country_match"]["status"] == "yes"
    assert service.check_interface_restrictions("uniswap", country="UA")["country_match"]["status"] == "reported"
    assert service.check_interface_restrictions("aave", country="BR")["country_match"] == {
        "national": False, "close_only": False, "regions": [], "status": None,
    }
    assert service.check_interface_restrictions("aave")["country_match"] is None


# ---------- 2. the negative cache is bounded ----------

def make(budget=100, negative_ttl=30):
    from cp0x_mcp.upstream import Fetcher

    http = FakeHTTP({f"{HOST_A}/u{i}": "facilitators.json" for i in range(10)})
    clock = FakeClock()
    return Fetcher(http, clock=clock, budget_per_minute=budget, negative_ttl_s=negative_ttl), http, clock


def test_negative_cache_drops_expired_entries_on_write():
    from cp0x_mcp.upstream import UpstreamError

    fetcher, http, clock = make()
    for i in range(5):
        http.fail.add(f"{HOST_A}/u{i}")
        with pytest.raises(UpstreamError):
            fetcher.get(f"{HOST_A}/u{i}", ttl_s=60)
    assert fetcher.stats() == {"cached": 0, "negative": 5, "backing_off": 0}
    clock.advance(31)
    http.fail.add(f"{HOST_A}/u5")
    with pytest.raises(UpstreamError):
        fetcher.get(f"{HOST_A}/u5", ttl_s=60)
    assert fetcher.stats()["negative"] == 1  # the five expired entries are gone without being requested again


def test_stats_counts_cache_entries_and_hosts_backing_off():
    from cp0x_mcp.upstream import UpstreamThrottled

    fetcher, http, clock = make()
    fetcher.get(f"{HOST_A}/u0", ttl_s=60)
    fetcher.get(f"{HOST_A}/u1", ttl_s=60)
    assert fetcher.stats() == {"cached": 2, "negative": 0, "backing_off": 0}

    def throttling(url):
        http.calls.append(url)
        raise UpstreamThrottled(retry_after_s=30, url=url)

    fetcher._get_json = throttling
    fetcher.get(f"{HOST_A}/u0", ttl_s=0)  # expired, throttled: served stale, host backs off
    assert fetcher.stats()["backing_off"] == 1
    clock.advance(31)
    assert fetcher.stats()["backing_off"] == 0



# ---------- 3. a shorter Retry-After never cancels a longer outstanding backoff ----------

def test_backoff_keeps_the_longest_outstanding_deadline():
    """Two in-flight requests to one host are throttled with different Retry-After values: the longer pause wins.

    The SDK runs synchronous tools in worker threads, so two calls can be inside the upstream request at once.
    """
    import threading

    from cp0x_mcp.upstream import UpstreamError, UpstreamThrottled

    fetcher, http, clock = make()
    both_in_flight = threading.Barrier(2, timeout=5)
    first_applied = threading.Event()
    results = {}

    def throttling(url):
        http.calls.append(url)
        both_in_flight.wait()  # the upstream call must run outside any Fetcher lock, or this never passes
        if url.endswith("/u0"):
            raise UpstreamThrottled(retry_after_s=120, url=url)
        assert first_applied.wait(5)  # the 1-second answer lands after the 120-second pause was applied
        raise UpstreamThrottled(retry_after_s=1, url=url)

    fetcher._get_json = throttling

    def call(name):
        try:
            fetcher.get(f"{HOST_A}/{name}", ttl_s=60)
        except UpstreamError as exc:
            results[name] = exc.retry_after_s
        if name == "u0":
            first_applied.set()

    threads = [threading.Thread(target=call, args=(name,)) for name in ("u0", "u1")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert results == {"u0": 120, "u1": 120}  # each throttled call reports the host's effective remaining pause
    with pytest.raises(UpstreamError) as err:  # the host-wide pause is still the long one
        fetcher.get(f"{HOST_A}/u2", ttl_s=60)
    assert err.value.retry_after_s == 120
    assert len(http.calls) == 2
