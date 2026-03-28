"""VoiceNotes MCP server - multi-user, VoiceNotes API key in URL path."""

import os
import re
from contextvars import ContextVar

import httpx
import uvicorn
from fastmcp import FastMCP
from starlette.responses import JSONResponse, PlainTextResponse

BASE_URL = "https://api.voicenotes.com/api/integrations/open-claw"
UUID_RE = re.compile(r"^[a-zA-Z0-9]{8}$")

_api_key: ContextVar[str] = ContextVar("voicenotes_api_key")

mcp = FastMCP("voicenotes-mcp")


def client() -> httpx.Client:
    key = _api_key.get(None)
    if not key:
        raise RuntimeError("No VoiceNotes API key in context")
    return httpx.Client(headers={"Authorization": key}, timeout=30)


# ============ TOOLS ============


@mcp.tool()
def search_notes(query: str) -> str:
    """Semantic search across your VoiceNotes. Returns notes ordered by relevance."""
    with client() as http:
        resp = http.get(f"{BASE_URL}/search/semantic", params={"query": query})
        resp.raise_for_status()

    results = resp.json()
    if not results:
        return "No results found."

    lines = []
    for r in results:
        note_type = r.get("type", "note")
        uuid = r.get("uuid", "")
        title = r.get("title") or "(untitled)"
        tags = ", ".join(r.get("tags", [])) or "none"
        created = r.get("created_at", "")[:10]
        transcript = r.get("transcript", "").replace("<br>", "\n").replace("<b>", "").replace("</b>", "")
        preview = transcript[:200].strip()
        if len(transcript) > 200:
            preview += "..."

        lines.append(f"[{note_type}] {title} (id:{uuid}) [{created}] tags:{tags}")
        if preview:
            lines.append(f"  {preview}")

    return "\n\n".join(lines)


@mcp.tool()
def list_notes(
    tags: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    page: int = 1,
) -> str:
    """List VoiceNotes with optional filters.

    tags: filter by tag names (e.g. ["meeting", "idea"])
    start_date / end_date: ISO date strings, e.g. "2026-01-01"
    page: page number (10 results per page)
    """
    body: dict = {}
    if tags:
        body["tags"] = tags
    if start_date or end_date:
        start = f"{start_date}T00:00:00.000000Z" if start_date else "2000-01-01T00:00:00.000000Z"
        end = f"{end_date}T23:59:59.000000Z" if end_date else "2100-01-01T00:00:00.000000Z"
        body["date_range"] = [start, end]

    with client() as http:
        resp = http.post(f"{BASE_URL}/recordings", json=body, params={"page": page})
        resp.raise_for_status()

    data = resp.json()
    notes = data.get("data", [])
    meta = data.get("meta", {})
    links = data.get("links", {})

    if not notes:
        return "No notes found."

    lines = []
    for n in notes:
        title = n.get("title") or "(untitled)"
        uuid = n.get("id", "")
        tags_list = [t if isinstance(t, str) else t.get("name", "") for t in n.get("tags", [])]
        tags_str = ", ".join(tags_list) or "none"
        created = n.get("created_at", "")[:10]
        rtype = {1: "voice", 2: "meeting", 3: "text"}.get(n.get("recording_type"), "unknown")
        transcript = (n.get("transcript") or "").strip()
        preview = transcript[:100]
        if len(transcript) > 100:
            preview += "..."
        lines.append(f"[{rtype}] {title} (id:{uuid}) [{created}] tags:{tags_str}")
        if preview:
            lines.append(f"  {preview}")

    current = meta.get("current_page", page)
    has_next = links.get("next") is not None
    lines.append(f"\nPage {current}" + (" | more available, use page={current + 1}" if has_next else ""))

    return "\n\n".join(lines)


@mcp.tool()
def get_note(uuid: str) -> str:
    """Get the full transcript and details of a single note by its UUID (8-char ID)."""
    if not UUID_RE.match(uuid):
        return f"Invalid UUID format: '{uuid}'. Must be 8 alphanumeric characters."

    with client() as http:
        resp = http.get(f"{BASE_URL}/recordings/{uuid}")
        resp.raise_for_status()

    data = resp.json().get("data", {})
    title = data.get("title") or "(untitled)"
    rtype = {1: "voice", 2: "meeting", 3: "text"}.get(data.get("recording_type"), "unknown")
    created = data.get("created_at", "")[:10]
    duration_ms = data.get("duration", 0)
    duration_str = f"{duration_ms // 60000}m {(duration_ms % 60000) // 1000}s" if duration_ms else "n/a"
    tags_list = [t if isinstance(t, str) else t.get("name", "") for t in data.get("tags", [])]
    tags_str = ", ".join(tags_list) or "none"
    transcript = data.get("transcript", "").replace("<br>", "\n")

    lines = [
        f"Title: {title}",
        f"ID: {uuid}",
        f"Type: {rtype}",
        f"Created: {created}",
        f"Duration: {duration_str}",
        f"Tags: {tags_str}",
        "",
        "Transcript:",
        transcript,
    ]
    return "\n".join(lines)


@mcp.tool()
def create_note(content: str) -> str:
    """Create a new text note in VoiceNotes."""
    with client() as http:
        resp = http.post(
            f"{BASE_URL}/recordings/new",
            json={"recording_type": 3, "transcript": content, "device_info": "mcp"},
        )
        resp.raise_for_status()

    data = resp.json()
    recording = data.get("recording", {})
    uuid = recording.get("id", "?")
    return f"Created note (id:{uuid})"


# ============ MAIN ============


def main():
    mcp_app = mcp.http_app(stateless_http=True, transport="streamable-http")

    class ApiKeyMiddleware:
        """Extracts VoiceNotes API key from /{api_key}/mcp path, rewrites to /mcp."""

        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            path = scope.get("path", "")

            if path == "/health":
                response = PlainTextResponse("ok")
                await response(scope, receive, send)
                return

            # Expect /{voicenotes_api_key}/mcp
            parts = path.lstrip("/").split("/", 1)
            if len(parts) != 2 or parts[1] != "mcp":
                response = JSONResponse(
                    {"error": "Invalid path. Use /{voicenotes_api_key}/mcp"},
                    status_code=400,
                )
                await response(scope, receive, send)
                return

            api_key = parts[0]
            if not api_key:
                response = JSONResponse({"error": "Missing API key"}, status_code=401)
                await response(scope, receive, send)
                return

            token = _api_key.set(api_key)
            new_scope = dict(scope)
            new_scope["path"] = "/mcp"
            new_scope["raw_path"] = b"/mcp"

            try:
                await self.app(new_scope, receive, send)
            finally:
                _api_key.reset(token)

    app = ApiKeyMiddleware(mcp_app)
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
