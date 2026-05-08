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
Claude Code session starts
        │
        ▼  SessionStart hook (optional)
  hooks/kg_session_start.py
        │
        └─ injects previous context into Claude (if enabled in config)

                    ┄┄┄ session happens ┄┄┄

Claude Code session ends
        │
        ▼  SessionEnd hook
  hooks/kg_extractor.py
        │
        ├─ reads transcript.jsonl
        ├─ calls Claude API to extract entities, relationships, decisions
        ├─ tracks mention counts and relationship weights
        ├─ finds semantically similar entities
        │
        ▼
  Obsidian Vault/ClaudeCode/
        ├─ INDEX.md                              ← all sessions + hot entities
        ├─ 2025-01-15-refactored-auth.md         ← session note
        └─ entities/
            ├─ auth-service.md                   ← CORE  (8×, 6 rels)
            └─ jose-library.md                   ← IMPORTANT (5×, 2 rels)

During next session
        │
        ▼  MCP server
  hooks/kg_mcp_server.py
        │
        ├─ kg_search("auth")          → ranked by relevance + importance
        ├─ kg_project_context(cwd)    → entities grouped by importance tier
        ├─ kg_get_entity("AuthService")
        ├─ kg_hot_entities()          → codebase attention map
        └─ kg_get_decisions()         → past architectural choices
```

---

## Project structure

```
claude-kg/
├── install.py               # One-command installer (Windows, macOS, Linux)
├── kg_config.json           # All settings — copy to ~/.claude/kg_config.json
├── settings_example.json    # Claude Code settings.json template
│
├── hooks/                   # Copy these to ~/.claude/hooks/
│   ├── kg_extractor.py      # SessionEnd — builds KG after each session
│   ├── kg_mcp_server.py     # MCP server — exposes KG as tools to Claude
│   └── kg_session_start.py  # SessionStart — injects context (opt-in)
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
- Anthropic API key - get one at [console.anthropic.com](https://console.anthropic.com)

### One-command install

```bash
git clone https://github.com/YOUR_USERNAME/claude-kg
cd claude-kg
pip install mcp
python install.py
```

The installer will:
- Copy all three hook scripts to `~/.claude/hooks/`
- Ask for your Obsidian vault path and API key
- Update `~/.claude/settings.json` automatically
- Set environment variables

That's it. Restart Claude Code and start a session.

### Manual install

Copy the three hook scripts:

**Windows:**
```powershell
mkdir "$env:USERPROFILE\.claude\hooks" -Force
copy hooks\kg_extractor.py     "$env:USERPROFILE\.claude\hooks\"
copy hooks\kg_mcp_server.py    "$env:USERPROFILE\.claude\hooks\"
copy hooks\kg_session_start.py "$env:USERPROFILE\.claude\hooks\"
```

**macOS / Linux:**
```bash
mkdir -p ~/.claude/hooks
cp hooks/kg_extractor.py     ~/.claude/hooks/
cp hooks/kg_mcp_server.py    ~/.claude/hooks/
cp hooks/kg_session_start.py ~/.claude/hooks/
```

Then merge `settings_example.json` into your `~/.claude/settings.json`.

Set three environment variables:

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Your key from console.anthropic.com |
| `OBSIDIAN_VAULT` | Full path to your Obsidian vault |
| `KG_FOLDER` | Subfolder inside vault (default: `ClaudeCode`) |

---

## Configuration

Copy `kg_config.json` to `~/.claude/kg_config.json` and edit as needed. All settings are optional — if the file does not exist, defaults are used.

```jsonc
{
  "features": {
    "mentions":    true,  // track how many sessions each entity appears in
    "weights":     true,  // track relationship weights across sessions
    "similarity":  true,  // find semantically similar entities
    "decisions":   true,  // extract architectural decisions
    "insights":    true,  // extract key insights

    // ⚠️ Injects previous context at session start.
    // Costs 1,000–5,000 tokens upfront every session.
    // If false, use kg_project_context via MCP instead (on-demand, cheaper).
    "auto_context_on_start": false
  },

  // Only used when auto_context_on_start is true
  "auto_context": {
    "max_sessions":       3,
    "include_entities":   true,
    "include_decisions":  true,
    "only_core_entities": true,   // only CORE + IMPORTANT entities (saves tokens)
    "max_tokens_hint":    2000    // trims context if it exceeds this
  },

  "mcp": {
    "importance_tiers": {
      "core":      20,  // score >= 20 → ⭐⭐⭐ CORE
      "important":  8,  // score >= 8  → ⭐⭐ IMPORTANT
      "moderate":   3   // score >= 3  → ⭐ MODERATE
    }
  }
}
```

**Importance score** is calculated as `mentions × 2 + relationship_count`. Entities that appear frequently and connect to many others rank higher — Claude uses this to prioritize attention.

---

## MCP Tools

Claude calls these automatically when it needs to find something:

| Tool | Description |
|---|---|
| `kg_search(query)` | Search by keyword — results ranked by relevance + importance |
| `kg_get_entity(name)` | Full entity profile with importance score, weights, similar entities |
| `kg_project_context(cwd)` | All sessions and entities grouped by importance tier |
| `kg_hot_entities(n?)` | Top N entities by importance score — the codebase attention map |
| `kg_get_decisions(filter?)` | All architectural decisions, optionally filtered by project |
| `kg_recent_sessions(n?)` | Last N sessions with summaries |

---

## Chrome Extension (for claude.ai)

Captures claude.ai conversations and sends them to the local server.

1. Start the local server: `backend/start_server.bat` (Windows) or `python backend/server.py`
2. Open `chrome://extensions/` (or `brave://extensions/`)
3. Enable **Developer mode**
4. Click **Load unpacked** → select the `extension/` folder

The extension auto-sends conversations after each Claude response. A toast confirms when processing starts. You can also trigger it manually via the extension popup.

---

## Obsidian setup

Recommended Community Plugins:

| Plugin | Purpose |
|---|---|
| **Dataview** | Query sessions like a database |
| **Juggl** | Enhanced graph with relationship types |
| **Graph Analysis** | Relationship strength visualization |
| **Strange New Worlds** | Backlink counts inline |

Example Dataview query — sessions this week:
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
# Test manually (Windows)
$t = "PATH\TO\YOUR\session.jsonl"
echo "{`"transcript_path`":`"$t`",`"session_id`":`"test`",`"cwd`":`"C:/`"}" | python "$env:USERPROFILE\.claude\hooks\kg_extractor.py"
```

**MCP server not connecting:**
```bash
pip install mcp
python ~/.claude/hooks/kg_mcp_server.py
```

**API 404 error:**
Check that `MODEL` in `kg_extractor.py` matches an available model. Default: `claude-sonnet-4-6`.

**Extension can't reach server:**
Make sure `backend/start_server.bat` is running. The popup shows **Server running ✓** when connected.

---

## License

MIT