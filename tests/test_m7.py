"""Contract added after the Codex review of m6: when two requests for the same expired URL overlap, the request that
fails must not mark the other request's fresh result stale."""
import threading

import pytest

from tests.conftest import FakeClock, FakeHTTP, load

HOST_A = "https://cp0x.test"


def make():
    from cp0x_mcp.upstream import Fetcher

    http = FakeHTTP({f"{HOST_A}/u{i}": "facilitators.json" for i in range(3)})
    clock = FakeClock()
    return Fetcher(http, clock=clock, budget_per_minute=100, negative_ttl_s=30), http, clock


@pytest.mark.parametrize("kind", ["error", "throttled"])
def test_concurrent_refresh_keeps_the_fresh_entry_when_the_other_request_fails(kind):
    from cp0x_mcp.upstream import UpstreamThrottled

    fetcher, http, clock = make()
    fetcher.get(f"{HOST_A}/u0", ttl_s=10)
    clock.advance(11)  # expired: both requests below go upstream
    both_in_flight = threading.Barrier(2, timeout=5)
    winner_done = threading.Event()
    results = {}

    def racing(url):
        http.calls.append(url)
        both_in_flight.wait()
        if threading.current_thread().name == "winner":
            return load("facilitators.json")
        assert winner_done.wait(5)  # the failure lands after the winner's fresh result is cached
        if kind == "throttled":
            raise UpstreamThrottled(retry_after_s=30, url=url)
        raise ConnectionError("simulated failure")

    fetcher._get_json = racing

    def run(name):
        results[name] = fetcher.get(f"{HOST_A}/u0", ttl_s=10)
        if name == "winner":
            winner_done.set()

    threads = [threading.Thread(target=run, args=(name,), name=name) for name in ("winner", "loser")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert results["winner"].stale is False
    assert results["loser"].stale is False  # fresh entry returned unchanged, not as a stale copy
    assert results["loser"].fetched_at == results["winner"].fetched_at
    assert results["loser"].data == results["winner"].data
    assert fetcher.stats()["negative"] == 0
    assert fetcher.stats()["backing_off"] == (1 if kind == "throttled" else 0)  # the throttle signal itself still counts
    assert fetcher.get(f"{HOST_A}/u0", ttl_s=10) == results["winner"]  # and stays fresh
    assert len(http.calls) == 3
