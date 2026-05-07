# 🧠 claude-kg

Automatically builds an Obsidian knowledge graph from your Claude Code sessions. After every session, entities, relationships, decisions and insights are extracted and written as interlinked Markdown notes - ready to browse in Obsidian's Graph View.

Also includes an MCP server so Claude can query the knowledge graph during sessions instead of re-scanning the codebase.

---

## Why

Every time you start a new Claude Code session, Claude starts from zero. It has no memory of what you built last week, which files you touched, why you chose one library over another, or which bugs you already fixed. To get useful answers, you either paste a wall of context at the start of every session - burning tokens - or Claude spends the first few minutes scanning files it has already seen dozens of times.

**claude-kg solves this.** It turns your session history into a queryable knowledge base that Claude can read on demand.

**Fewer tokens wasted on exploration.** Instead of reading 40 files to find where authentication lives, Claude calls `kg_search("auth")` and gets the answer in one round trip. The more sessions you accumulate, the more often Claude finds what it needs in the KG instead of the filesystem.

**No more re-explaining context.** The KG remembers that you switched from `jsonwebtoken` to `jose` three weeks ago and why. It knows that `UserModel` is tightly coupled to `AuthService`. Claude walks into each session already knowing the shape of your project.

**Decisions stay documented.** Every architectural choice, library selection, and technical tradeoff gets recorded automatically. Six months later you can look up exactly why a decision was made — and so can Claude before it suggests you undo it.

**Your knowledge compounds.** Each session makes the next one cheaper and smarter. The graph grows richer over time, and Claude gets progressively better at navigating your specific codebase without you lifting a finger.

---

## How it works

```
Claude Code session ends
        │
        ▼  SessionEnd hook
  hooks/kg_extractor.py
        │
        ├─ reads transcript.jsonl
        ├─ calls Claude API (extracts entities, relationships, decisions)
        │
        ▼
  Obsidian Vault/ClaudeCode/
        ├─ INDEX.md
        ├─ 2025-01-15-refactored-auth.md
        └─ entities/
            ├─ auth-service.md
            └─ jose-library.md

Next session starts
        │
        ▼  MCP server
  hooks/kg_mcp_server.py
        │
        ├─ kg_search("auth")           → find relevant entities
        ├─ kg_project_context(cwd)     → load project history
        ├─ kg_get_entity("AuthService")
        └─ kg_get_decisions()          → see past architectural choices
```

---

## Project structure

```
claude-kg/
├── install.py               # One-command installer (Windows, macOS, Linux)
├── settings_example.json    # Claude Code settings.json template
│
├── hooks/                   # Drop these into ~/.claude/hooks/
│   ├── kg_extractor.py      # SessionEnd hook — builds KG after each session
│   └── kg_mcp_server.py     # MCP server — exposes KG as tools to Claude Code
│
├── extension/               # Chrome extension for claude.ai conversations
│   ├── manifest.json
│   ├── content.js
│   ├── popup.html
│   └── popup.js
│
└── backend/                 # Local HTTP server used by the Chrome extension
    ├── server.py
    └── start_server.bat     # Windows launcher
```

---

## Installation

### Requirements

- Python 3.10+
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
- [Obsidian](https://obsidian.md)
- Anthropic API key — get one at [console.anthropic.com](https://console.anthropic.com)

### One-command install

```bash
git clone https://github.com/YOUR_USERNAME/claude-kg
cd claude-kg
pip install mcp
python install.py
```

The installer will:
- Copy `hooks/kg_extractor.py` and `hooks/kg_mcp_server.py` to `~/.claude/hooks/`
- Ask for your Obsidian vault path and API key
- Update `~/.claude/settings.json` automatically
- Set environment variables

That's it. Restart Claude Code and start a session.

### Manual install (optional)

If you prefer to set things up yourself, see `settings_example.json` for the full `settings.json` template. You need three environment variables:

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Your key from console.anthropic.com |
| `OBSIDIAN_VAULT` | Full path to your Obsidian vault |
| `KG_FOLDER` | Subfolder name inside vault (default: `ClaudeCode`) |

---

## Chrome Extension (for claude.ai)

Captures claude.ai conversations and sends them to the local server.

### Setup

1. Start the local server: run `backend/start_server.bat` (Windows) or `python backend/server.py`
2. Open `chrome://extensions/`
3. Enable **Developer mode**
4. Click **Load unpacked** → select the `extension/` folder
5. Set `OBSIDIAN_VAULT` env var and restart the server

The extension auto-sends conversations to the KG after Claude finishes each response. A toast notification confirms when processing starts.

---

## MCP Tools available to Claude

| Tool | Description |
|---|---|
| `kg_search(query)` | Search entities, sessions, decisions by keyword |
| `kg_get_entity(name)` | Full profile of an entity with relationships |
| `kg_project_context(cwd)` | All sessions and entities for the current project |
| `kg_get_decisions(filter?)` | All architectural decisions, optionally filtered by project |
| `kg_recent_sessions(n?)` | Last N sessions with summaries |

Claude calls these automatically when it needs to find something — no manual prompting needed.

---

## Obsidian setup

Recommended plugins (Community Plugins):

- **Dataview** — query sessions like a database
- **Juggl** — enhanced graph with relationship types
- **Graph Analysis** — relationship strength visualization
- **Strange New Worlds** — backlink counts inline

Example Dataview query — all sessions this week:
```dataview
TABLE date, cwd, tags
FROM "ClaudeCode"
WHERE type = "claude-code-session"
AND date >= date(today) - dur(7 days)
SORT date DESC
```

---

## Troubleshooting

**Notes not appearing after session:**
```powershell
# Test the extractor manually (Windows)
$t = "PATH\TO\YOUR\session.jsonl"
echo "{`"transcript_path`":`"$t`",`"session_id`":`"test`",`"cwd`":`"C:/`"}" | python "$env:USERPROFILE\.claude\hooks\kg_extractor.py"
```

**MCP server not connecting:**
```bash
python ~/.claude/hooks/kg_mcp_server.py
# Should start without errors if mcp package is installed
```

**API 404 error:**
Make sure `MODEL` in `kg_extractor.py` matches an available model. Current default: `claude-sonnet-4-6`.

---

## License

MIT
