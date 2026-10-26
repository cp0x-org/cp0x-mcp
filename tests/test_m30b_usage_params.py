"""m30b: the usage middleware runs before params validation, so malformed tools/call params must pass through uncounted."""
from types import SimpleNamespace

import anyio
import pytest

from tests.test_m30_usage import counter


def usage_middleware(service):
    from cp0x_mcp.server import build_server

    usage = counter()
    server = build_server(service, usage=usage)
    return server.middleware[-1], usage


def run_middleware(middleware, params, client_params=None):
    ctx = SimpleNamespace(method="tools/call", params=params, session=SimpleNamespace(client_params=client_params))

    async def call_next(inner_ctx):
        assert inner_ctx is ctx
        return "handled"

    return anyio.run(middleware, ctx, call_next)


@pytest.mark.parametrize("params", [
    None,
    {},
    {"arguments": {}},
    {"name": None},
    {"name": 7},
    {"name": ["list_races"]},
    {"name": {"tool": "list_races"}},
])
def test_malformed_tool_call_params_pass_through_uncounted(service, params):
    middleware, usage = usage_middleware(service)
    assert run_middleware(middleware, params) == "handled"
    assert usage.snapshot()["days"] == {}


def test_well_formed_call_is_still_counted(service):
    middleware, usage = usage_middleware(service)
    client_params = SimpleNamespace(client_info=SimpleNamespace(name="Claude-AI Test"))
    assert run_middleware(middleware, {"name": "list_races", "arguments": {}}, client_params) == "handled"
    assert run_middleware(middleware, {"name": "list_races"}, SimpleNamespace(client_info=None)) == "handled"
    assert usage.snapshot()["days"] == {"2026-10-26": {"list_races": {"claude-ai-test": 1, "unknown": 1}}}


def test_other_methods_pass_through_uncounted(service):
    middleware, usage = usage_middleware(service)
    ctx = SimpleNamespace(method="tools/list", params=None, session=SimpleNamespace(client_params=None))

    async def call_next(inner_ctx):
        return "listed"

    assert anyio.run(middleware, ctx, call_next) == "listed"
    assert usage.snapshot()["days"] == {}
