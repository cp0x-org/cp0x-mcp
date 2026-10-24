"""Extract referral hints without treating unrelated path segments as codes."""

from urllib.parse import parse_qs, urlsplit


def code_hint(link: str) -> str | None:
    parsed = urlsplit(link)
    query = parse_qs(parsed.query)
    for key in ("ref", "referral", "r", "code", "via", "invite"):
        for value in query.get(key, []):
            if value:
                return value
    segments = parsed.path.split("/")
    for index, segment in enumerate(segments[:-1]):
        if segment in {"join", "invite", "refer", "r", "i"}:
            if segments[index + 1]:
                return segments[index + 1]
    return None
