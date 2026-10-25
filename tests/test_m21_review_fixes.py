"""m21: leaderboards that store the reward in a `points` column instead of `prize`."""
from datetime import date

from tests.conftest import load


def test_points_column_is_read_as_the_race_reward(http, clock):
    from cp0x_mcp import sources
    from cp0x_mcp.service import Cp0xService
    from cp0x_mcp.upstream import Fetcher

    http.routes[sources.race_url("risex", "leaderboard")] = "leaderboard_points_reward.json"
    service = Cp0xService(Fetcher(http, clock=clock), benefits=load("benefits.json"), today=lambda: date(2026, 10, 25))
    rc = service.get_deal("risex")["race_cases"]
    cases = {c["case"]: c for c in rc["cases"]}
    assert [c["case"] for c in rc["cases"]] == ["first", "top10", "last_paid"]
    assert (cases["first"]["rank"], cases["first"]["race_prize"]) == (1, 400)
    assert (cases["top10"]["rank"], cases["top10"]["race_prize"]) == (10, 0)
    assert (cases["last_paid"]["rank"], cases["last_paid"]["race_prize"], cases["last_paid"]["volume"]) == (8, 20, 200)
    assert rc["race"]["prize_currency"] == "points" and rc["race"]["ranked_by"] == "volume"
