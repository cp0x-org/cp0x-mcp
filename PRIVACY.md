# Privacy

The cp0x MCP server at `https://mcp.cp0x.com/mcp` is a read-only service over public data. It has no accounts, no sign-in and no paid features.

## What the server receives

Each tool call carries the tool name and its arguments, for example a venue name, a deal slug or a country code. Each HTTP request also carries standard metadata: IP address, time and user agent.

## What is stored

The server process keeps daily aggregate counts of tool calls per tool and per client application name (the name a client reports when it connects, for example `claude-ai`). It does not record IP addresses, arguments or individual calls. Counts for the last 30 days are kept in memory, lost on restart, and published at `https://mcp.cp0x.com/usage`. Apart from these counts, it keeps only public upstream responses in an in-memory cache, which is lost on restart. The reverse proxy in front of the server writes standard access logs (IP address, time, path, status code) to cp0x's internal analytics database. cp0x uses them for rate limiting, abuse prevention and aggregate traffic counts. The logs are not deleted on a fixed schedule; to have log entries tied to your IP address removed, write to admin@cp0x.com.

## Sharing

cp0x does not sell or share this data. To answer a call, the server requests public data from cp0x.com, x402-api.cp0x.com, raw.githubusercontent.com, api.github.com and api.coingecko.com. These requests do not include anything about the caller.

## Contact

admin@cp0x.com
