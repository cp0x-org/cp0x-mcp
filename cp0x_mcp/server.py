"""MCP tools and HTTP or stdio entry points for cp0x public data."""

import argparse
import time
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Any, Callable, Iterable, Literal

import httpx
from mcp.server import MCPServer
from mcp.server.transport_security import (
    TransportSecurityMiddleware,
    TransportSecuritySettings,
)
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from . import sources
from .limits import RateLimiter
from .service import Cp0xService
from .upstream import Fetcher, UpstreamThrottled


def _package_version() -> str:
    try:
        return version("cp0x-mcp")
    except PackageNotFoundError:
        return "0.1.0"


def get_json(url: str, *, transport: httpx.BaseTransport | None = None) -> Any:
    """Fetch public JSON and expose upstream 429 responses as throttle signals."""
    user_agent = f"cp0x-mcp/{_package_version()} (+https://cp0x.com)"
    with httpx.Client(
        timeout=10.0, headers={"User-Agent": user_agent}, transport=transport
    ) as client:
        response = client.get(url)
        if response.status_code == 429:
            try:
                retry_after_s = int(response.headers.get("Retry-After", "60"))
            except ValueError:
                retry_after_s = 60
            raise UpstreamThrottled(retry_after_s, url=url)
        response.raise_for_status()
        return response.json()


def _annotations(title: str) -> ToolAnnotations:
    return ToolAnnotations(
        title=title,
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )


def build_server(service: Cp0xService) -> MCPServer:
    """Expose eleven read-only tools, including cp0x facts and open-source repositories."""
    server = MCPServer(
        "cp0x",
        instructions=(
            "Eleven read-only tools for cp0x data: referral deals and races, a monitor of DeFi "
            "interface geo-restrictions, x402 facilitators and resources, "
            "a static cp0x fact sheet with mission, values, sites, channels and 2025 figures, "
            "and public open-source repositories from GitHub. "
            "Referral links include a cp0x referral code."
        ),
    )

    @server.tool(
        title="List referral deals",
        annotations=_annotations("List referral deals"),
        description=(
            "List cp0x referral deals with optional venue filtering. "
            "Use this when looking for deals by venue or browsing the deal catalog; "
            "links include a cp0x referral code."
        ),
    )
    def list_deals(
        query: Annotated[
            str | None, Field(description="Substring of the venue title or slug.", max_length=100)
        ] = None,
        limit: Annotated[
            int | None,
            Field(
                description="Maximum number of deals; omit to return all matches.",
                ge=1,
                le=100,
                # Keep bounds visible beside the nullable schema for MCP clients.
                json_schema_extra={"minimum": 1, "maximum": 100},
            ),
        ] = None,
    ) -> dict:
        return service.list_deals(query=query, limit=limit)

    @server.tool(
        title="Get referral deal",
        annotations=_annotations("Get referral deal"),
        description=(
            "Get a cp0x deal with its description and races. "
            "Use this when a deal slug is known and its full details are needed; "
            "links include a cp0x referral code."
        ),
    )
    def get_deal(
        slug: Annotated[str, Field(description="Deal slug from the cp0x catalog.", max_length=100)],
    ) -> dict:
        return service.get_deal(slug=slug)

    @server.tool(
        title="Get venue referral code",
        annotations=_annotations("Get venue referral code"),
        description=(
            "Find a venue's referral code and link in the cp0x catalog. "
            "Use this when a user requests referral details for a named venue; "
            "links include a cp0x referral code."
        ),
    )
    def get_referral_code(
        venue: Annotated[str, Field(description="Venue name or deal slug to match.", max_length=100)],
    ) -> dict:
        return service.get_referral_code(venue=venue)

    @server.tool(
        title="List races",
        annotations=_annotations("List races"),
        description=(
            "List cp0x races with dates and prizes. "
            "Use this when finding active or completed races, optionally for one deal."
        ),
    )
    def list_races(
        status: Annotated[
            Literal["active", "completed"] | None,
            Field(description="Race status to include; omit to include both statuses."),
        ] = None,
        slug: Annotated[
            str | None, Field(description="Deal slug to filter races by.", max_length=100)
        ] = None,
    ) -> dict:
        return service.list_races(status=status, slug=slug)

    @server.tool(
        title="Get race leaderboard",
        annotations=_annotations("Get race leaderboard"),
        description=(
            "Get a cp0x race leaderboard and its column definitions. "
            "Use this when viewing standings for a known deal and race."
        ),
    )
    def get_leaderboard(
        slug: Annotated[str, Field(description="Deal slug containing the race.", max_length=100)],
        race_code: Annotated[str, Field(description="Race code within the deal.")] = "leaderboard",
        top: Annotated[int, Field(description="Maximum leaderboard rows to return.", ge=1, le=100)] = 20,
    ) -> dict:
        return service.get_leaderboard(slug=slug, race_code=race_code, top=top)

    @server.tool(
        title="Check interface restrictions",
        annotations=_annotations("Check interface restrictions"),
        description=(
            "Read declared and observed geo-restrictions for a DeFi interface. "
            "Use this when checking a protocol's interface restrictions, optionally for a country."
        ),
    )
    def check_interface_restrictions(
        protocol: Annotated[
            str, Field(description="Protocol name or interface identifier to match.", max_length=100)
        ],
        country: Annotated[
            str | None,
            Field(
                description="ISO-3166 alpha-2 country code; omit for all observed countries.",
                max_length=2,
                pattern="^[A-Za-z]{2}$",
                json_schema_extra={"maxLength": 2},
            ),
        ] = None,
    ) -> dict:
        return service.check_interface_restrictions(protocol=protocol, country=country)

    @server.tool(
        title="List restricted interfaces",
        annotations=_annotations("List restricted interfaces"),
        description=(
            "List DeFi interfaces with declared or observed restrictions in a country. "
            "Use this when identifying which interfaces the cp0x monitor reports as restricted there."
        ),
    )
    def list_restricted_interfaces(
        country: Annotated[
            str,
            Field(description="ISO-3166 alpha-2 country code.", max_length=2, pattern="^[A-Za-z]{2}$"),
        ],
    ) -> dict:
        return service.list_restricted_interfaces(country=country)

    @server.tool(
        title="List x402 facilitators",
        annotations=_annotations("List x402 facilitators"),
        description=(
            "List x402 facilitators and their URLs from cp0x. "
            "Use this when looking up facilitator names and endpoints in the cp0x catalog."
        ),
    )
    def list_x402_facilitators() -> dict:
        return service.list_x402_facilitators()

    @server.tool(
        title="List cp0x x402 resources",
        annotations=_annotations("List cp0x x402 resources"),
        description=(
            "List cp0x x402 resources with prices and tags. "
            "Use this when finding available cp0x x402 resources or filtering them by tag."
        ),
    )
    def list_cp0x_x402_resources(
        tag: Annotated[str | None, Field(description="Resource tag to filter by.")] = None,
    ) -> dict:
        return service.list_cp0x_x402_resources(tag=tag)

    @server.tool(
        title="About cp0x",
        annotations=_annotations("About cp0x"),
        description=(
            "Who cp0x is and how much it has passed on to its users, valued at today's token prices: "
            "mission, values, sites, channels, 2025 figures and every distribution with token amounts. "
            "Use this when a user asks what cp0x is, what it gave its users, "
            "or where to find its sites and channels."
        ),
    )
    def about_cp0x() -> dict:
        return service.about_cp0x()

    @server.tool(
        title="List cp0x open-source repositories",
        annotations=_annotations("List cp0x open-source repositories"),
        description=(
            "List public open-source repositories of cp0x: permissionless DeFi interfaces "
            "and tools, from GitHub. "
            "Use this when looking for cp0x interfaces, tools or source code."
        ),
    )
    def list_cp0x_open_source(
        kind: Annotated[
            Literal["interface", "project"] | None,
            Field(description="Repository kind to include; omit to include both kinds."),
        ] = None,
    ) -> dict:
        return service.list_cp0x_open_source(kind=kind)

    return server


class RequestMiddleware:
    """Apply SDK transport validation and caller limits to every HTTP route."""

    def __init__(self, app: ASGIApp, security: TransportSecuritySettings, limiter: RateLimiter):
        self.app = app
        self._security = TransportSecurityMiddleware(security)
        self._limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            response = await self._security.validate_request(Request(scope))
            if response is None:
                client = scope.get("client")
                allowed, retry_after = self._limiter.allow(client[0] if client else "unknown")
                if not allowed:
                    response = JSONResponse(
                        {"error": "rate limited"},
                        status_code=429,
                        headers={"Retry-After": str(retry_after)},
                    )
            if response is not None:
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def build_app(
    server: MCPServer,
    *,
    allowed_hosts: Iterable[str],
    allowed_origins: Iterable[str] = (),
    per_ip_per_minute: int = 60,
    clock: Callable[[], float] = time.monotonic,
) -> Starlette:
    """Build the SDK ASGI app with a health route and caller request limits."""
    package_version = _package_version()

    @server.custom_route("/health", ["GET"])
    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "server": "cp0x", "version": package_version})

    security = TransportSecuritySettings(
        allowed_hosts=list(allowed_hosts), allowed_origins=list(allowed_origins)
    )
    app = server.streamable_http_app(transport_security=security, host="127.0.0.1")
    app.add_middleware(
        RequestMiddleware,
        security=security,
        limiter=RateLimiter(per_ip_per_minute, clock=clock),
    )
    return app


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse transport, bind address, allowlists, and caller request limits."""
    parser = argparse.ArgumentParser(description="Serve read-only cp0x public data over MCP.")
    parser.add_argument("--transport", choices=("http", "stdio"), default="http")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--allowed-host", action="append")
    parser.add_argument("--allowed-origin", action="append", default=[])
    parser.add_argument("--per-ip-per-minute", type=int, default=60)
    args = parser.parse_args(argv)
    if args.allowed_host is None:
        args.allowed_host = ["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*"]
    return args


def main(argv: list[str] | None = None) -> None:
    """Run the cp0x MCP server using the selected transport."""
    args = parse_args(argv)
    server = build_server(Cp0xService(Fetcher(
        get_json, budget_per_minute=sources.UPSTREAM_BUDGET_PER_MINUTE,
    )))
    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        try:
            import uvicorn
        except ImportError as exc:
            raise SystemExit("HTTP transport requires uvicorn: pip install uvicorn") from exc
        uvicorn.run(
            build_app(
                server,
                allowed_hosts=args.allowed_host,
                allowed_origins=args.allowed_origin,
                per_ip_per_minute=args.per_ip_per_minute,
            ),
            host=args.host,
            port=args.port,
        )


if __name__ == "__main__":
    main()
