# cp0x MCP

[![tests](https://github.com/cp0x-org/cp0x-mcp/actions/workflows/tests.yml/badge.svg)](https://github.com/cp0x-org/cp0x-mcp/actions/workflows/tests.yml) [![cp0x MCP MCP server – quality and maintenance score on Glama](https://glama.ai/mcp/servers/cp0x-org/cp0x-mcp/badges/score.svg)](https://glama.ai/mcp/servers/cp0x-org/cp0x-mcp)

A read-only MCP server over cp0x public data, owned by [cp0x](https://cp0x.com).

## Tools

| Tool | Returns | Arguments |
| --- | --- | --- |
| `list_deals` | Matching deals with bonuses, referral links and codes, race summaries, and the total match count. | Optional `query`: case-insensitive substring of venue title or slug (up to 100 characters); optional `limit`: 1–100, all matches when omitted. |
| `get_deal` | The complete deal record, including its description and races, with adjacent `benefit` comparisons and `race_cases` examples (null when unavailable); known slugs if the deal is missing. | Required `slug`: deal slug (up to 100 characters). |
| `get_referral_code` | A matching venue's deal, referral code, and link, or candidate names and slugs if ambiguous. | Required `venue`: venue name or slug (up to 100 characters); exact matches take priority over substring matches. |
| `compare_referral_benefits` | Compact deals with `benefit` comparisons against each venue's own referral offer and `race_cases` from active leaderboards, ordered by additional benefit. | Optional `category`: venue category (up to 40 characters); all deals when omitted. |
| `list_races` | Race codes, titles, statuses, dates, and the deal slug for each race. | Optional `status`: `active` or `completed`, both when omitted; optional `slug`: deal slug (up to 100 characters). |
| `get_leaderboard` | Race details, column definitions, leading entries, and the total entry count. | Required `slug` (up to 100 characters); optional `race_code` (default `leaderboard`); optional `top`: 1–100 (default 20). |
| `check_interface_restrictions` | An interface's declared restrictions, observed probes, alternatives, legend, snapshot version, and `country_match`; candidate interfaces if no exact match exists. | Required `protocol`: interface name or ID (up to 100 characters); optional `country`: ISO 3166 alpha-2 code, all observed countries when omitted. |
| `list_restricted_interfaces` | Interfaces with national, close-only, regional, or observed restrictions, including `scope`, `declared_layers`, `close_only_layers`, `regions`, and `observed_block`. | Required `country`: ISO 3166 alpha-2 code. |
| `about_cp0x` | Leads with `distributed_to_users`: the total passed to users at today's token prices, every distribution with token amounts or cash prizes, and the value at distribution. Includes the shipped cp0x fact sheet: mission, values, activities, sites, channels, grant, and 2025 figures. | None. |
| `list_cp0x_open_source` | Public cp0x repositories with descriptions, URLs, homepages, kinds, stars, topics, push dates, fork flags, and a count, sorted by latest push. Archived and private repositories and forks outside `pi-` interfaces are excluded. | Optional `kind`: `interface` or `project`, both when omitted. |
| `list_x402_facilitators` | The public facilitator catalog, including names and URLs. | None. |
| `list_cp0x_x402_resources` | cp0x x402 test resource catalog entries, including prices, tags, and target URLs. | Optional `tag`: case-insensitive tag match. |

Results include source attribution and a `stale` flag; failures can include an `error` field. Referral codes are returned as published, without inventing missing codes.

Freshness and retry fields for upstream data (`about_cp0x` keeps these fields inside `distributed_to_users.prices`; its top-level `stale` remains false). Missing token prices produce a partial total and are named in the summary; if no token has a price, the summary uses the value at distribution. Price errors remain inside `distributed_to_users.prices`:

- `stale`: true when expired cached data is returned because a refresh failed or requests are paused.
- `fetched_at`: UTC timestamp of the oldest upstream response used, or null when none is available.
- `age_s`: age in seconds of the oldest response, or null when none is available.
- `stale_since`: UTC timestamp when the oldest response's cache TTL expired for a stale result; otherwise null.
- `retry_after_s`: included with upstream errors; integer seconds before retrying when a budget, backoff, or negative cache blocks the request, or null for the initial ordinary failure.

For `check_interface_restrictions`, `country_match` contains `national` and `close_only` flags, matching regional codes in `regions`, and `status`, the status of the declaration that produced the match (null when no declaration matches); `country_match` is null when no country is supplied. For each entry from `list_restricted_interfaces`, `scope` is `national`, `close_only`, `regional`, or `observed`, in that priority order. The `declared_status` field carries the originating layer's status for national, close-only, and regional matches; it is null for observed-only matches. When multiple declarations match, both status fields use the first layer in that scope priority order. The `close_only_layers` field lists layers that allow closing positions only; `regions` lists matching subdivisions such as `CA-ON`.

Example questions: “What referral deals are available for Extended?”, “Which races are active?”, and “What interface restrictions does the monitor report for Aave in the US?”

## Connect

Public Streamable HTTP URL: **https://mcp.cp0x.com/mcp**

No authentication is required.

### Claude (connectors / Desktop)

Add a remote MCP server by URL using `https://mcp.cp0x.com/mcp` in Claude connectors or Claude Desktop, with no authentication.

### ChatGPT

Add a remote MCP server by URL using `https://mcp.cp0x.com/mcp` as a custom MCP connector, with no authentication.

### Cursor

Add a remote MCP server by URL in `mcp.json`:

```json
{
  "mcpServers": {
    "cp0x": {
      "url": "https://mcp.cp0x.com/mcp"
    }
  }
}
```

### Perplexity

Add a remote MCP server by URL using `https://mcp.cp0x.com/mcp`; select authentication `None`.

## Data sources and freshness

| Source | Public endpoints | Cache TTL |
| --- | --- | --- |
| cp0x deals and races | [Deals API](https://cp0x.com/api/v1/deals); leaderboards at `https://cp0x.com/api/v1/deals/{slug}/races/{race_code}`. | 60 seconds for deals and leaderboards. |
| DeFi interface restrictions monitor | [Interface catalog](https://raw.githubusercontent.com/cp0x-org/pi-restricted-interfaces/main/monitor/current/catalog/interfaces.json) and [observations](https://raw.githubusercontent.com/cp0x-org/pi-restricted-interfaces/main/monitor/current/catalog/observations.json) from the public [monitor repository](https://github.com/cp0x-org/pi-restricted-interfaces). | 600 seconds. |
| cp0x open-source repositories | [api.github.com public repository API](https://api.github.com/orgs/cp0x-org/repos?per_page=100&type=public&sort=pushed) for [cp0x-org](https://github.com/cp0x-org); no API key required. | 10 minutes (600 seconds). |
| Token prices | [CoinGecko public endpoint](https://api.coingecko.com/api/v3/simple/price?ids=hyperliquid,lighter,derive,resolv,paradex&vs_currencies=usd&include_last_updated_at=true) for HYPE, LIT, DRV, RESOLV, and DIME prices in USD in one request; no API key required. Used by `distributed_to_users`. | 60 seconds. |
| cp0x static fact sheet | `cp0x_mcp/data/about.json`, shipped with the server; figures from the [cp0x 2025 annual report](https://cp0x.com/docs/reports/2025). | Loaded once into memory; no network request or timed refresh. |
| cp0x x402 catalogs | [Facilitators](https://x402-api.cp0x.com/api/free/facilitators) and [cp0x resources](https://x402-api.cp0x.com/api/free/cp0x-resources). | 300 seconds. |

Monitor data is a published repository snapshot, not a live probe. Its version comes from the catalog's `meta.generated` field and is returned as `data_version` by `check_interface_restrictions`. Observations describe the recorded checks; missing probes do not establish availability.

Caches are local to each server instance and refresh on demand after expiry. If an upstream request fails, an existing cached response can be returned with `stale` set to true; without cached data, the result contains an `error`. Cache TTL does not guarantee that the upstream data has changed.

## Rate limits

The HTTP server limits requests per caller IP to **60 requests/minute** by default, configurable with `--per-ip-per-minute`. Requests over the limit receive HTTP `429` with a `Retry-After` header in seconds.

The upstream cp0x.com API also limits requests to **60 requests/minute per IP**. The server's outgoing IP is shared by its upstream requests; cached reads reduce upstream traffic.

Each server instance shares a budget of **45 upstream requests per minute per host**, keyed by host and port, across all tools in a rolling 60-second window. Only actual upstream calls consume budget; cache hits do not. When the budget is exhausted, expired cached data is returned with `stale` set to true; without cached data, results include an `error` and `retry_after_s`. An upstream HTTP `429` triggers host-wide backoff according to `Retry-After` (60 seconds if missing or nonnumeric), with the same stale fallback. Ordinary failures without cached data are negatively cached for 30 seconds per URL; repeats return an error and remaining `retry_after_s` without another upstream call. The initial ordinary failure reports `retry_after_s` as null.

## Run locally

Install from the repository with Python 3.10 or later:

```sh
pip install -e .
```

Run over stdio:

```sh
cp0x-mcp --transport stdio
```

Run over HTTP:

```sh
cp0x-mcp --transport http --host 127.0.0.1 --port 8000 --allowed-host localhost:8000 --allowed-host 127.0.0.1:8000
```

The HTTP routes are `/mcp`, `/health` and `/usage`. `/usage` returns daily aggregate tool-call counts per tool and client application name for the last 30 days, without IP addresses or arguments. Configure `--allowed-host` to match the client's `Host` header, including a port where needed. When no allowlist is supplied, localhost and 127.0.0.1 are allowed with or without ports.

## Deploy behind a reverse proxy

Uvicorn reads `FORWARDED_ALLOW_IPS` to decide which proxies may supply forwarded client IPs. Set it to the reverse proxy's IP address so the caller rate limit uses the original client IP from `X-Forwarded-For`. Without a trusted proxy setting, all callers through an untrusted proxy share one rate-limit bucket keyed by the proxy IP.

The Docker image sets `FORWARDED_ALLOW_IPS="*"`. With this setting, port 8000 must be reachable only by the reverse proxy. Otherwise, replace `*` with the proxy IP using an environment override. For a proxy on the Docker host, bind the published port to loopback:

Build and run the Docker image:

```sh
docker build -t cp0x-mcp .
docker run -p 127.0.0.1:8000:8000 cp0x-mcp
```

Forward `/mcp` and `/health` to port 8000 and preserve the public `Host` header. The image binds to all interfaces and permits `Host` headers `mcp.cp0x.com` and `mcp.cp0x.com:*`. Local requests to the container must send an allowed `Host` header. Its health-check requests `/health` on loopback with `Host: mcp.cp0x.com`; this route also enforces the host allowlist and caller rate limit.

## Publish

Keep `server.json` in the repository root. It declares `com.cp0x/public-data`, version `0.2.0`, and the public Streamable HTTP endpoint; publishing this remote server does not require a package.

Before publishing to the MCP Registry, verify ownership of `cp0x.com` using a DNS TXT record at the domain apex or an HTTP proof at `https://cp0x.com/.well-known/mcp-registry-auth`. Authenticate with `mcp-publisher` using the corresponding domain verification method, then run from the repository root:

```sh
mcp-publisher validate
mcp-publisher publish
```

Glama reads the root `glama.json` for maintainer metadata when indexing the GitHub repository.

## Disclosure

Deal links contain a cp0x referral code. The server only reads public data; it does not place trades or execute paid x402 requests. MIT license, see `LICENSE`. Privacy policy: see `PRIVACY.md`.
