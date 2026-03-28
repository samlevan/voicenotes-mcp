# voicenotes-mcp

MCP server for [VoiceNotes](https://voicenotes.com). Search, browse, and create notes from Claude.

## Setup

1. Get your VoiceNotes API key at [voicenotes.com/app#settings](https://voicenotes.com/app?open-claw=true#settings)

2. Add to `~/.claude.json`:

```json
"voicenotes": {
  "type": "http",
  "url": "https://mcp-voicenotes-production.up.railway.app/{your_api_key}/mcp"
}
```

3. Reconnect via `/mcp` in Claude Code (use **Reconnect**, not Authenticate)

## Tools

| Tool | Description |
|------|-------------|
| `search_notes` | Semantic search across your notes |
| `list_notes` | List notes, optionally filtered by tags or date range |
| `get_note` | Fetch full transcript of a note by ID |
| `create_note` | Create a new text note |

## Self-hosting

```bash
git clone https://github.com/samlevan/voicenotes-mcp
cd voicenotes-mcp
railway link
railway up
```

No env vars required. The VoiceNotes API key is passed in the URL path at request time.
