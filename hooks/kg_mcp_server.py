#!/usr/bin/env python3
"""
Knowledge Graph MCP Server for Claude Code.
Exposes KG data as tools Claude can call during sessions.

All responses include frequency/weight signals so Claude knows
which entities matter most — without reading the codebase.
"""

import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime

OBSIDIAN_VAULT = os.getenv("OBSIDIAN_VAULT", str(Path.home() / "ObsidianVault"))
KG_FOLDER      = os.getenv("KG_FOLDER", "ClaudeCode")

def _load_config() -> dict:
    defaults = {
        "mcp": {
            "importance_tiers": {"core": 20, "important": 8, "moderate": 3},
            "max_search_results": 10,
            "max_sessions_in_context": 8,
        }
    }
    config_path = Path.home() / ".claude" / "kg_config.json"
    if config_path.exists():
        try:
            raw = re.sub(r"//.*", "", config_path.read_text(encoding="utf-8"))
            user = json.loads(raw)
            if "mcp" in user:
                defaults["mcp"].update(user["mcp"])
            defaults.update({k: v for k, v in user.items() if k != "mcp"})
        except Exception as e:
            print(f"[KG-MCP] Config error: {e}", file=sys.stderr)
    return defaults

CFG  = _load_config()
MCFG = CFG.get("mcp", {})

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp import types
    HAS_MCP = True
except ImportError:
    HAS_MCP = False


class KGReader:
    def __init__(self):
        self.vault  = Path(OBSIDIAN_VAULT)
        self.folder = self.vault / KG_FOLDER

    # ── helpers ───────────────────────────────────────────────────────────────

    def _read_note(self, path: Path) -> dict:
        if not path.exists():
            return {}
        text = path.read_text(encoding="utf-8")
        fm, body = {}, text
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                for line in parts[1].splitlines():
                    if ":" in line:
                        k, _, v = line.partition(":")
                        fm[k.strip()] = v.strip().strip('"')
                body = parts[2].strip()
        return {"frontmatter": fm, "body": body}

    def _slugify(self, text: str) -> str:
        text = re.sub(r"[^\w\s-]", "", text.lower())
        return re.sub(r"[\s_-]+", "-", text).strip("-")[:60]

    def _excerpt(self, text: str, query: str) -> str:
        idx = text.lower().find(query)
        if idx == -1:
            return ""
        s, e = max(0, idx - 60), min(len(text), idx + 120)
        return "..." + text[s:e].replace("\n", " ") + "..."

    def _summary(self, body: str) -> str:
        for line in body.splitlines():
            line = line.strip()
            if line.startswith(">") and len(line) > 5:
                return line[1:].strip()
            if len(line) > 30 and not line.startswith("#"):
                return line[:200]
        return ""

    def _importance_label(self, mentions: int, rel_count: int) -> str:
        tiers = MCFG.get("importance_tiers", {"core": 20, "important": 8, "moderate": 3})
        score = mentions * 2 + rel_count
        if score >= tiers["core"]:
            return f"⭐⭐⭐ CORE  (mentioned {mentions}×, {rel_count} relationships)"
        elif score >= tiers["important"]:
            return f"⭐⭐ IMPORTANT  (mentioned {mentions}×, {rel_count} relationships)"
        elif score >= tiers["moderate"]:
            return f"⭐ MODERATE  (mentioned {mentions}×, {rel_count} relationships)"
        else:
            return f"○ LOW  (mentioned {mentions}×, {rel_count} relationships)"

    def _read_entity_signals(self, path: Path) -> dict:
        """Extract mentions + relationship count from an entity note."""
        if not path.exists():
            return {"mentions": 0, "rel_count": 0, "similar": [], "type": "", "title": path.stem}
        note = self._read_note(path)
        fm   = note.get("frontmatter", {})
        body = note.get("body", "")

        mentions  = int(fm.get("mentions", 0))
        rel_count = len(re.findall(r"\(weight:\s*\d+\)", body))
        similar   = re.findall(r"\[\[entities/([^\]|]+)[^\]]*\]\]",
                               body[body.find("## 🔀"):] if "## 🔀" in body else "")

        return {
            "title":     fm.get("title", path.stem),
            "type":      fm.get("type", ""),
            "mentions":  mentions,
            "rel_count": rel_count,
            "similar":   similar[:5],
        }

    # ── tools ─────────────────────────────────────────────────────────────────

    def search(self, query: str) -> str:
        if not self.folder.exists():
            return "Knowledge graph is empty — run a Claude Code session first."

        query_lower = query.lower()
        results = []

        for f in self.folder.rglob("*.md"):
            if f.name == "INDEX.md":
                continue
            try:
                text = f.read_text(encoding="utf-8")
                if query_lower not in text.lower():
                    continue
                note     = self._read_note(f)
                fm       = note.get("frontmatter", {})
                matches  = text.lower().count(query_lower)
                mentions = int(fm.get("mentions", 0))
                # Combined relevance: text matches + entity importance
                score    = matches + mentions * 2
                results.append({
                    "title":    fm.get("title", f.stem),
                    "type":     fm.get("type", ""),
                    "mentions": mentions,
                    "score":    score,
                    "excerpt":  self._excerpt(text, query_lower),
                    "is_entity": "entities" in str(f),
                })
            except Exception:
                pass

        if not results:
            return f'No results for "{query}" in the knowledge graph.'

        results.sort(key=lambda x: x["score"], reverse=True)

        lines = [f'Search results for "{query}" — sorted by relevance + importance:\n']
        for r in results[:10]:
            signals = self._read_entity_signals(
                self.folder / "entities" / f"{self._slugify(r['title'])}.md"
            ) if r["is_entity"] else {}
            importance = self._importance_label(
                signals.get("mentions", r["mentions"]),
                signals.get("rel_count", 0)
            ) if r["is_entity"] else ""
            lines.append(f"### {r['title']} ({r['type']})")
            if importance:
                lines.append(f"Importance: {importance}")
            if r["excerpt"]:
                lines.append(f"Context: {r['excerpt']}")
            lines.append("")

        return "\n".join(lines)


    def get_entity(self, name: str) -> str:
        slug = self._slugify(name)
        path = self.folder / "entities" / f"{slug}.md"

        if not path.exists():
            entity_dir = self.folder / "entities"
            if entity_dir.exists():
                for f in entity_dir.glob("*.md"):
                    if name.lower() in f.stem.lower():
                        path = f
                        break

        if not path.exists():
            return f"Entity '{name}' not found in knowledge graph."

        note    = self._read_note(path)
        fm      = note.get("frontmatter", {})
        body    = note.get("body", "")
        signals = self._read_entity_signals(path)

        lines = [
            f"# {signals['title']} ({signals['type']})",
            f"Importance: {self._importance_label(signals['mentions'], signals['rel_count'])}",
        ]
        if signals["similar"]:
            lines.append(f"Semantically similar to: {', '.join(signals['similar'])}")
        lines += ["", body]

        return "\n".join(lines)


    def get_project_context(self, cwd: str) -> str:
        if not self.folder.exists():
            return "No knowledge graph found. Complete a Claude Code session first."

        cwd_lower  = cwd.lower().replace("\\", "/")
        sessions   = []
        entity_set = set()

        for f in self.folder.glob("????-??-??-*.md"):
            note     = self._read_note(f)
            fm       = note.get("frontmatter", {})
            note_cwd = fm.get("cwd", "").lower().replace("\\", "/")
            if cwd_lower in note_cwd or note_cwd in cwd_lower:
                sessions.append({
                    "title":   fm.get("title", f.stem),
                    "date":    fm.get("date", ""),
                    "summary": self._summary(note.get("body", "")),
                })
                for m in re.finditer(r"\[\[entities/([^\]|]+)", note.get("body", "")):
                    entity_set.add(m.group(1))

        sessions.sort(key=lambda x: x["date"], reverse=True)

        # Load entity signals and sort by importance
        entity_signals = []
        for slug in entity_set:
            ep      = self.folder / "entities" / f"{slug}.md"
            signals = self._read_entity_signals(ep)
            entity_signals.append(signals)

        entity_signals.sort(
            key=lambda x: x["mentions"] * 2 + x["rel_count"],
            reverse=True
        )

        lines = [f"## Project context for {cwd}\n"]

        if not sessions:
            lines.append("No previous sessions for this project.")
        else:
            lines.append(f"### Previous sessions ({len(sessions)})\n")
            for s in sessions[:8]:
                lines.append(f"**{s['date']} — {s['title']}**")
                lines.append(f"  {s['summary']}\n")

        if entity_signals:
            lines.append(f"\n### Known entities — sorted by importance\n")
            lines.append("Use this to prioritize where to focus. High-importance entities")
            lines.append("appear frequently and have many relationships — they are the core of this codebase.\n")

            # Group by importance tier
            core       = [e for e in entity_signals if e["mentions"]*2+e["rel_count"] >= 20]
            important  = [e for e in entity_signals if 8 <= e["mentions"]*2+e["rel_count"] < 20]
            moderate   = [e for e in entity_signals if 3 <= e["mentions"]*2+e["rel_count"] < 8]
            low        = [e for e in entity_signals if e["mentions"]*2+e["rel_count"] < 3]

            if core:
                lines.append("**⭐⭐⭐ CORE — always relevant:**")
                for e in core:
                    sim = f" ~ {', '.join(e['similar'][:2])}" if e["similar"] else ""
                    lines.append(f"  • {e['title']} ({e['type']}) — {e['mentions']}× mentioned, {e['rel_count']} relationships{sim}")
                lines.append("")

            if important:
                lines.append("**⭐⭐ IMPORTANT — frequently used:**")
                for e in important:
                    lines.append(f"  • {e['title']} ({e['type']}) — {e['mentions']}× mentioned, {e['rel_count']} relationships")
                lines.append("")

            if moderate:
                lines.append("**⭐ MODERATE — contextually relevant:**")
                for e in moderate:
                    lines.append(f"  • {e['title']} ({e['type']}) — {e['mentions']}×")
                lines.append("")

            if low:
                lines.append(f"**○ LOW — {len(low)} rarely-mentioned entities** (omitted for brevity)")
                lines.append("")

        return "\n".join(lines)


    def get_decisions(self, project_filter: str = "") -> str:
        if not self.folder.exists():
            return "No decisions documented yet."

        decisions = []
        for f in self.folder.glob("????-??-??-*.md"):
            note = self._read_note(f)
            fm   = note.get("frontmatter", {})
            if project_filter and project_filter.lower() not in fm.get("cwd", "").lower():
                continue
            body, in_dec, cur = note.get("body", ""), False, {}
            for line in body.splitlines():
                if "## ⚡" in line or "## Decisions" in line:
                    in_dec = True
                    continue
                if in_dec and line.startswith("## "):
                    in_dec = False
                    if cur:
                        decisions.append(cur)
                        cur = {}
                if in_dec:
                    if line.startswith("### "):
                        if cur:
                            decisions.append(cur)
                        cur = {"decision": line[4:].strip(), "session": fm.get("title", ""), "date": fm.get("date", ""), "rationale": ""}
                    elif "**Rationale:**" in line and cur:
                        cur["rationale"] = line.replace("**Rationale:**", "").strip()
            if cur:
                decisions.append(cur)

        if not decisions:
            return "No architectural decisions documented yet."

        decisions.sort(key=lambda x: x["date"], reverse=True)
        lines = [f"## Documented decisions ({len(decisions)})\n",
                 "Review these before making architectural choices — they capture past reasoning.\n"]
        for d in decisions[:20]:
            lines.append(f"**{d['date']} — {d['decision']}**")
            if d["rationale"]:
                lines.append(f"  Rationale: {d['rationale']}")
            lines.append(f"  Session: {d['session']}\n")
        return "\n".join(lines)


    def get_hot_entities(self, n: int = 10) -> str:
        """Return top N entities by importance score — Claude's attention map."""
        entity_dir = self.folder / "entities"
        if not entity_dir.exists():
            return "No entities yet."

        entities = []
        for f in entity_dir.glob("*.md"):
            signals = self._read_entity_signals(f)
            score   = signals["mentions"] * 2 + signals["rel_count"]
            entities.append((score, signals))

        entities.sort(reverse=True)

        lines = [
            f"## Top {n} entities by importance\n",
            "This is your codebase's attention map — the higher the score,",
            "the more central this entity is to the project.\n",
            f"{'Entity':<30} {'Type':<15} {'Mentions':>8} {'Rels':>5} {'Score':>6}",
            "-" * 70,
        ]
        for score, s in entities[:n]:
            sim = f"  ~ {s['similar'][0]}" if s["similar"] else ""
            lines.append(
                f"{s['title']:<30} {s['type']:<15} {s['mentions']:>8} {s['rel_count']:>5} {score:>6}{sim}"
            )
        return "\n".join(lines)


    def get_recent_sessions(self, n: int = 5) -> str:
        if not self.folder.exists():
            return "No sessions yet."
        notes = []
        for f in self.folder.glob("????-??-??-*.md"):
            note = self._read_note(f)
            fm   = note.get("frontmatter", {})
            if fm.get("type") == "claude-code-session":
                notes.append({
                    "title":   fm.get("title", f.stem),
                    "date":    fm.get("date", ""),
                    "cwd":     fm.get("cwd", ""),
                    "summary": self._summary(note.get("body", "")),
                })
        notes.sort(key=lambda x: x["date"], reverse=True)
        lines = [f"## Last {min(n, len(notes))} sessions\n"]
        for s in notes[:n]:
            lines += [f"**{s['date']} — {s['title']}**", f"  Project: {s['cwd']}", f"  {s['summary']}\n"]
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
#  MCP Server
# ══════════════════════════════════════════════════════════════════════════════

def run_mcp_server():
    kg     = KGReader()
    server = Server("knowledge-graph")

    @server.list_tools()
    async def list_tools():
        return [
            types.Tool(
                name="kg_search",
                description=(
                    "Search the knowledge graph by keyword. Results are ranked by relevance AND entity importance "
                    "(mentions × sessions). Use this before exploring files — the KG may already know the answer "
                    "and tell you which entities are most important."
                ),
                inputSchema={"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}
            ),
            types.Tool(
                name="kg_get_entity",
                description=(
                    "Get full details about an entity including its importance score, relationship weights, "
                    "and semantically similar entities. Higher importance = more central to the codebase."
                ),
                inputSchema={"type":"object","properties":{"name":{"type":"string"}},"required":["name"]}
            ),
            types.Tool(
                name="kg_project_context",
                description=(
                    "Get all sessions and entities for the current project, grouped by importance tier: "
                    "CORE / IMPORTANT / MODERATE / LOW. Use this at session start to understand "
                    "what matters most without reading files."
                ),
                inputSchema={"type":"object","properties":{"cwd":{"type":"string"}},"required":["cwd"]}
            ),
            types.Tool(
                name="kg_hot_entities",
                description=(
                    "Get the top N most important entities sorted by importance score "
                    "(mentions × 2 + relationship count). This is the codebase attention map — "
                    "tells you where complexity and activity concentrate."
                ),
                inputSchema={"type":"object","properties":{"n":{"type":"integer","default":10}}}
            ),
            types.Tool(
                name="kg_get_decisions",
                description="Get all architectural decisions and their rationale. Check before making tech choices.",
                inputSchema={"type":"object","properties":{"project_filter":{"type":"string"}}}
            ),
            types.Tool(
                name="kg_recent_sessions",
                description="Get the most recent sessions with summaries.",
                inputSchema={"type":"object","properties":{"n":{"type":"integer","default":5}}}
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        try:
            if name == "kg_search":
                text = kg.search(arguments.get("query", ""))
            elif name == "kg_get_entity":
                text = kg.get_entity(arguments.get("name", ""))
            elif name == "kg_project_context":
                text = kg.get_project_context(arguments.get("cwd", ""))
            elif name == "kg_hot_entities":
                text = kg.get_hot_entities(arguments.get("n", 10))
            elif name == "kg_get_decisions":
                text = kg.get_decisions(arguments.get("project_filter", ""))
            elif name == "kg_recent_sessions":
                text = kg.get_recent_sessions(arguments.get("n", 5))
            else:
                text = f"Unknown tool: {name}"
        except Exception as e:
            text = f"Error: {e}"
        return [types.TextContent(type="text", text=text)]

    import asyncio
    async def main():
        async with stdio_server() as (r, w):
            await server.run(r, w, server.create_initialization_options())
    asyncio.run(main())


if __name__ == "__main__":
    if not HAS_MCP:
        print("ERROR: run: pip install mcp", file=sys.stderr)
        sys.exit(1)
    run_mcp_server()