#!/usr/bin/env python3
"""
Knowledge Graph MCP Server for Claude Code.
Exposes KG data as tools Claude can call during sessions.

Install: pip install mcp
Run via Claude Code settings.json (stdio transport)
"""

import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────────────────
OBSIDIAN_VAULT = os.getenv("OBSIDIAN_VAULT", str(Path.home() / "ObsidianVault"))
KG_FOLDER      = os.getenv("KG_FOLDER", "ClaudeCode")
# ─────────────────────────────────────────────────────────────────────────────

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp import types
    HAS_MCP = True
except ImportError:
    HAS_MCP = False


# ══════════════════════════════════════════════════════════════════════════════
#  KG Reader — all logic for reading Obsidian notes
# ══════════════════════════════════════════════════════════════════════════════

class KGReader:
    def __init__(self):
        self.vault  = Path(OBSIDIAN_VAULT)
        self.folder = self.vault / KG_FOLDER

    def _read_note(self, path: Path) -> dict:
        """Parse a markdown note into frontmatter + body."""
        if not path.exists():
            return {}
        text = path.read_text(encoding="utf-8")
        fm: dict = {}
        body = text

        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                for line in parts[1].splitlines():
                    if ":" in line:
                        k, _, v = line.partition(":")
                        fm[k.strip()] = v.strip().strip('"')
                body = parts[2].strip()

        return {"frontmatter": fm, "body": body, "path": str(path)}

    def get_recent_sessions(self, n: int = 5) -> list[dict]:
        """Return the N most recent session notes."""
        if not self.folder.exists():
            return []

        notes = []
        for f in self.folder.glob("????-??-??-*.md"):
            note = self._read_note(f)
            if note.get("frontmatter", {}).get("type") == "claude-code-session":
                notes.append({
                    "title":   note["frontmatter"].get("title", f.stem),
                    "date":    note["frontmatter"].get("date", ""),
                    "tags":    note["frontmatter"].get("tags", ""),
                    "cwd":     note["frontmatter"].get("cwd", ""),
                    "summary": self._extract_summary(note["body"]),
                    "file":    f.name,
                })

        notes.sort(key=lambda x: x["date"], reverse=True)
        return notes[:n]

    def search(self, query: str) -> list[dict]:
        """Full-text search across all KG notes."""
        if not self.folder.exists():
            return []

        query_lower = query.lower()
        results = []

        for f in self.folder.rglob("*.md"):
            if f.name == "INDEX.md":
                continue
            try:
                text = f.read_text(encoding="utf-8")
                if query_lower in text.lower():
                    note = self._read_note(f)
                    fm   = note.get("frontmatter", {})
                    # Count occurrences for relevance
                    count = text.lower().count(query_lower)
                    results.append({
                        "file":    str(f.relative_to(self.folder)),
                        "title":   fm.get("title", f.stem),
                        "type":    fm.get("type", "unknown"),
                        "matches": count,
                        "excerpt": self._find_excerpt(text, query_lower),
                    })
            except Exception:
                pass

        results.sort(key=lambda x: x["matches"], reverse=True)
        return results[:10]

    def get_entity(self, name: str) -> dict:
        """Get full details of an entity by name."""
        slug = self._slugify(name)
        path = self.folder / "entities" / f"{slug}.md"

        # Try fuzzy match if exact not found
        if not path.exists():
            entity_dir = self.folder / "entities"
            if entity_dir.exists():
                for f in entity_dir.glob("*.md"):
                    if name.lower() in f.stem.lower():
                        path = f
                        break

        if not path.exists():
            return {"error": f"Entity '{name}' not found"}

        note = self._read_note(path)
        return {
            "name":    note["frontmatter"].get("title", name),
            "type":    note["frontmatter"].get("type", ""),
            "content": note["body"],
        }

    def get_project_context(self, cwd: str) -> dict:
        """Get all sessions and entities related to a project path."""
        if not self.folder.exists():
            return {"sessions": [], "entities": []}

        cwd_lower  = cwd.lower().replace("\\", "/")
        sessions   = []
        entity_set = set()

        for f in self.folder.glob("????-??-??-*.md"):
            note = self._read_note(f)
            fm   = note.get("frontmatter", {})
            note_cwd = fm.get("cwd", "").lower().replace("\\", "/")

            if cwd_lower in note_cwd or note_cwd in cwd_lower:
                sessions.append({
                    "title":   fm.get("title", f.stem),
                    "date":    fm.get("date", ""),
                    "summary": self._extract_summary(note["body"]),
                    "file":    f.name,
                })
                # Collect entity links from this session
                for m in re.finditer(r"\[\[entities/([^\]|]+)", note["body"]):
                    entity_set.add(m.group(1))

        sessions.sort(key=lambda x: x["date"], reverse=True)

        entities = []
        for slug in list(entity_set)[:20]:
            ep = self.folder / "entities" / f"{slug}.md"
            if ep.exists():
                en = self._read_note(ep)
                entities.append({
                    "name": en["frontmatter"].get("title", slug),
                    "type": en["frontmatter"].get("type", ""),
                    "desc": en["body"].split("\n")[0][:120] if en["body"] else "",
                })

        return {"sessions": sessions[:10], "entities": entities}

    def get_decisions(self, project_filter: str = "") -> list[dict]:
        """Get all decisions made across sessions, optionally filtered by project."""
        if not self.folder.exists():
            return []

        decisions = []
        for f in self.folder.glob("????-??-??-*.md"):
            note = self._read_note(f)
            fm   = note.get("frontmatter", {})

            if project_filter:
                cwd = fm.get("cwd", "").lower()
                if project_filter.lower() not in cwd:
                    continue

            # Extract decisions section
            body = note["body"]
            in_decisions = False
            current: dict = {}

            for line in body.splitlines():
                if line.startswith("## ⚡") or line.startswith("## Decisions"):
                    in_decisions = True
                    continue
                if in_decisions and line.startswith("## "):
                    in_decisions = False
                    if current:
                        decisions.append(current)
                        current = {}
                if in_decisions:
                    if line.startswith("### "):
                        if current:
                            decisions.append(current)
                        current = {
                            "decision": line[4:].strip(),
                            "session":  fm.get("title", f.stem),
                            "date":     fm.get("date", ""),
                            "rationale": "",
                        }
                    elif line.startswith("**Rationale:**") and current:
                        current["rationale"] = line.replace("**Rationale:**", "").strip()

            if current:
                decisions.append(current)

        decisions.sort(key=lambda x: x["date"], reverse=True)
        return decisions[:20]

    def _extract_summary(self, body: str) -> str:
        for line in body.splitlines():
            line = line.strip()
            if line.startswith(">") and len(line) > 5:
                return line[1:].strip()
            if len(line) > 30 and not line.startswith("#"):
                return line[:200]
        return ""

    def _find_excerpt(self, text: str, query: str) -> str:
        idx = text.lower().find(query)
        if idx == -1:
            return ""
        start = max(0, idx - 60)
        end   = min(len(text), idx + 120)
        return "..." + text[start:end].replace("\n", " ") + "..."

    def _slugify(self, text: str) -> str:
        text = re.sub(r"[^\w\s-]", "", text.lower())
        text = re.sub(r"[\s_-]+", "-", text).strip("-")
        return text[:60]


# ══════════════════════════════════════════════════════════════════════════════
#  MCP Server
# ══════════════════════════════════════════════════════════════════════════════

def run_mcp_server():
    kg     = KGReader()
    server = Server("knowledge-graph")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="kg_search",
                description="Search the knowledge graph for entities, concepts, files, or decisions. Use this before exploring the codebase to check if something is already documented.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search term (e.g. 'auth', 'JWT', 'database migration')"
                        }
                    },
                    "required": ["query"]
                }
            ),
            types.Tool(
                name="kg_get_entity",
                description="Get full details about a specific entity (file, concept, library, etc.) from the knowledge graph, including its relationships and which sessions it appeared in.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Entity name (e.g. 'AuthService', 'jose', 'UserModel')"
                        }
                    },
                    "required": ["name"]
                }
            ),
            types.Tool(
                name="kg_project_context",
                description="Get all previously documented sessions, entities, and decisions for the current project. Call this at the start of a session to understand what has been done before.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "cwd": {
                            "type": "string",
                            "description": "Project directory path"
                        }
                    },
                    "required": ["cwd"]
                }
            ),
            types.Tool(
                name="kg_get_decisions",
                description="Get all architectural decisions and conclusions documented across sessions. Useful before making technology choices or architectural changes.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project_filter": {
                            "type": "string",
                            "description": "Optional: filter by project path substring"
                        }
                    }
                }
            ),
            types.Tool(
                name="kg_recent_sessions",
                description="Get the most recent Claude Code sessions with their summaries.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "n": {
                            "type": "integer",
                            "description": "Number of sessions to return (default: 5)"
                        }
                    }
                }
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        try:
            if name == "kg_search":
                results = kg.search(arguments.get("query", ""))
                if not results:
                    text = "No results found in knowledge graph."
                else:
                    lines = [f"Found {len(results)} results:\n"]
                    for r in results:
                        lines.append(f"**{r['title']}** ({r['type']})")
                        lines.append(f"  {r['excerpt']}\n")
                    text = "\n".join(lines)

            elif name == "kg_get_entity":
                result = kg.get_entity(arguments.get("name", ""))
                if "error" in result:
                    text = result["error"]
                else:
                    text = f"# {result['name']} ({result['type']})\n\n{result['content']}"

            elif name == "kg_project_context":
                result = kg.get_project_context(arguments.get("cwd", ""))
                lines  = []
                if result["sessions"]:
                    lines.append(f"## Previous sessions ({len(result['sessions'])})\n")
                    for s in result["sessions"]:
                        lines.append(f"**{s['date']} — {s['title']}**")
                        lines.append(f"  {s['summary']}\n")
                else:
                    lines.append("No previous sessions for this project.")
                if result["entities"]:
                    lines.append(f"\n## Known entities ({len(result['entities'])})\n")
                    for e in result["entities"]:
                        lines.append(f"- **{e['name']}** ({e['type']}): {e['desc']}")
                text = "\n".join(lines)

            elif name == "kg_get_decisions":
                results = kg.get_decisions(arguments.get("project_filter", ""))
                if not results:
                    text = "No decisions documented yet."
                else:
                    lines = [f"## Documented decisions ({len(results)})\n"]
                    for d in results:
                        lines.append(f"**{d['date']} — {d['decision']}**")
                        if d["rationale"]:
                            lines.append(f"  Rationale: {d['rationale']}")
                        lines.append(f"  Session: {d['session']}\n")
                    text = "\n".join(lines)

            elif name == "kg_recent_sessions":
                n       = arguments.get("n", 5)
                results = kg.get_recent_sessions(n)
                if not results:
                    text = "No sessions in knowledge graph yet."
                else:
                    lines = [f"## Last {len(results)} sessions\n"]
                    for s in results:
                        lines.append(f"**{s['date']} — {s['title']}**")
                        lines.append(f"  Project: {s['cwd']}")
                        lines.append(f"  {s['summary']}\n")
                    text = "\n".join(lines)

            else:
                text = f"Unknown tool: {name}"

        except Exception as e:
            text = f"Error: {e}"

        return [types.TextContent(type="text", text=text)]

    import asyncio

    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(main())


# ══════════════════════════════════════════════════════════════════════════════
#  Fallback — if mcp not installed, print install instructions
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if not HAS_MCP:
        print("ERROR: mcp package not installed.", file=sys.stderr)
        print("Run: pip install mcp", file=sys.stderr)
        sys.exit(1)

    run_mcp_server()
