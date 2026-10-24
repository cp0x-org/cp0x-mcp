FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir . uvicorn

# Port 8000 must be reachable only by the reverse proxy; otherwise set its IP here.
ENV FORWARDED_ALLOW_IPS="*"

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; request = urllib.request.Request('http://127.0.0.1:8000/health', headers={'Host': 'mcp.cp0x.com'}); response = urllib.request.urlopen(request, timeout=3); response.close()"]

# cp0x-mcp --transport http --host 0.0.0.0 --port 8000 --allowed-host mcp.cp0x.com
CMD ["cp0x-mcp", "--transport", "http", "--host", "0.0.0.0", "--port", "8000", "--allowed-host", "mcp.cp0x.com", "--allowed-host", "mcp.cp0x.com:*"]
