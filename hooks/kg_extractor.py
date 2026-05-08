#!/usr/bin/env python3
"""
Claude Code → Obsidian Knowledge Graph Extractor
Triggered by SessionEnd hook. Reads the session transcript,
calls Claude API to extract entities/relationships,
then writes/updates Obsidian markdown notes.
"""

import json
import sys
import os
import re
from pathlib import Path
from datetime import datetime, timezone
import urllib.request
import urllib.error


# ── CONFIG ────────────────────────────────────────────────────────────────────
def _load_config() -> dict:
    """Load kg_config.json from ~/.claude/ if it exists, else return defaults."""
    defaults = {
        "model": "claude-sonnet-4-6",
        "min_session_length": 100,
        "features": {
            "mentions": True,
            "weights": True,
            "similarity": True,
            "decisions": True,
            "insights": True,
            "hot_index": True,
        }
    }
    config_path = Path.home() / ".claude" / "kg_config.json"
    if config_path.exists():
        try:
            raw = config_path.read_text(encoding="utf-8")
            # Strip JS-style comments before parsing
            raw = re.sub(r"//.*", "", raw)
            user = json.loads(raw)
            # Deep merge features
            if "features" in user:
                defaults["features"].update(user.pop("features"))
            defaults.update(user)
        except Exception as e:
            print(f"[KG] Config parse error: {e}, using defaults.", file=sys.stderr)
    return defaults


CFG = _load_config()
OBSIDIAN_VAULT = os.getenv("OBSIDIAN_VAULT", str(Path.home() / "ObsidianVault"))
KG_FOLDER = os.getenv("KG_FOLDER", CFG.get("kg_folder", "ClaudeCode"))
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = CFG.get("model", "claude-sonnet-4-6")
MIN_LENGTH = CFG.get("min_session_length", 100)
FEAT = CFG.get("features", {})


# ─────────────────────────────────────────────────────────────────────────────


def read_transcript(transcript_path: str) -> list[dict]:
    """Parse the JSONL transcript file Claude Code provides."""
    messages = []
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except FileNotFoundError:
        print(f"[KG] Transcript not found: {transcript_path}", file=sys.stderr)
    return messages


def extract_text_from_transcript(messages: list[dict]) -> str:
    """Convert raw JSONL transcript to a readable conversation string."""
    lines = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        # content can be a string or a list of content blocks
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        name = block.get("name", "tool")
                        inp = json.dumps(block.get("input", {}), ensure_ascii=False)[:300]
                        parts.append(f"[Tool: {name}] {inp}")
                    elif block.get("type") == "tool_result":
                        res = str(block.get("content", ""))[:300]
                        parts.append(f"[Result] {res}")
            content = "\n".join(parts)

        if role and content:
            lines.append(f"### {role.upper()}\n{content}")

    return "\n\n".join(lines)


def call_claude(prompt: str) -> str:
    """Call Claude API, returns the response text."""
    payload = {
        "model": MODEL,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}]
    }

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["content"][0]["text"]
    except Exception as e:
        print(f"[KG] API error: {e}", file=sys.stderr)
        return ""


def extract_knowledge_graph(conversation: str, session_meta: dict) -> dict:
    """Ask Claude to extract structured knowledge from the session."""

    cwd = session_meta.get("cwd", "unknown")
    session = session_meta.get("session_id", "unknown")[:12]
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    prompt = f"""You are a knowledge graph builder. Analyze this Claude Code session and extract structured knowledge.

SESSION METADATA:
- Date: {date}
- Working directory: {cwd}
- Session ID: {session}

CONVERSATION:
{conversation[:12000]}

Extract and return ONLY valid JSON (no markdown, no explanation) with this exact structure:
{{
  "session": {{
    "title": "Short descriptive title (max 8 words)",
    "summary": "2-3 sentence summary of what was accomplished",
    "date": "{date}",
    "cwd": "{cwd}",
    "session_id": "{session}",
    "tags": ["tag1", "tag2"]
  }},
  "entities": [
    {{
      "id": "PascalCaseID",
      "type": "File|Function|Concept|Library|Task|Decision|Bug|Architecture|Command|Config",
      "name": "Human readable name",
      "description": "1-2 sentence description",
      "properties": {{"key": "value"}}
    }}
  ],
  "relationships": [
    {{
      "from": "EntityID",
      "to": "EntityID",
      "type": "USES|MODIFIES|CREATES|FIXES|DEPENDS_ON|IMPLEMENTS|DISCUSSES|RESOLVES|EXTENDS",
      "description": "brief description"
    }}
  ],
  "decisions": [
    {{
      "title": "Decision made",
      "rationale": "Why this decision was made",
      "alternatives": ["alternative 1", "alternative 2"]
    }}
  ],
  "insights": [
    "Key insight or learning from this session"
  ]
}}

Focus on: files created/modified, key concepts discussed, decisions made, libraries/tools used, bugs fixed, architecture choices. Be specific and concise."""

    raw = call_claude(prompt)

    # strip possible markdown fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[KG] JSON parse error: {e}\nRaw:\n{raw[:500]}", file=sys.stderr)
        return {}


def slugify(text: str) -> str:
    """Convert text to a safe filename."""
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:60]


def write_session_note(kg: dict, vault: Path, folder: Path) -> Path:
    """Write the main session note to the Obsidian vault."""
    session = kg.get("session", {})
    entities = kg.get("entities", [])
    rels = kg.get("relationships", [])
    decisions = kg.get("decisions", [])
    insights = kg.get("insights", [])

    date = session.get("date", datetime.now().strftime("%Y-%m-%d"))
    title = session.get("title", "Untitled Session")
    slug = f"{date}-{slugify(title)}"
    tags = session.get("tags", [])
    cwd = session.get("cwd", "")

    # Build entity map for linking
    entity_map = {e["id"]: e["name"] for e in entities}

    lines = [
        f"---",
        f"title: \"{title}\"",
        f"date: {date}",
        f"session_id: {session.get('session_id', '')}",
        f"cwd: \"{cwd}\"",
        f"tags: [{', '.join(tags)}]",
        f"type: claude-code-session",
        f"---",
        "",
        f"# {title}",
        "",
        f"> {session.get('summary', '')}",
        "",
        f"**Date:** {date}  ",
        f"**Project:** `{cwd}`  ",
        f"**Session:** `{session.get('session_id', '')}`",
        "",
    ]

    # Entities section
    if entities:
        lines += ["## 🔷 Entities", ""]
        by_type: dict[str, list] = {}
        for e in entities:
            by_type.setdefault(e.get("type", "Other"), []).append(e)

        for etype, elist in sorted(by_type.items()):
            lines.append(f"### {etype}")
            for e in elist:
                note_link = f"[[{slugify(e['name'])}|{e['name']}]]"
                props = ""
                if e.get("properties"):
                    props = " · " + " · ".join(f"`{k}: {v}`" for k, v in e["properties"].items())
                lines.append(f"- {note_link} — {e.get('description', '')}{props}")
            lines.append("")

    # Relationships section
    if rels:
        lines += ["## 🔗 Relationships", ""]
        for r in rels:
            from_name = entity_map.get(r["from"], r["from"])
            to_name = entity_map.get(r["to"], r["to"])
            from_link = f"[[{slugify(from_name)}|{from_name}]]"
            to_link = f"[[{slugify(to_name)}|{to_name}]]"
            lines.append(
                f"- {from_link} **{r['type']}** {to_link}" + (f" — {r['description']}" if r.get("description") else ""))
        lines.append("")

    # Decisions
    if decisions:
        lines += ["## ⚡ Decisions", ""]
        for d in decisions:
            lines.append(f"### {d['title']}")
            lines.append(f"**Rationale:** {d.get('rationale', '')}")
            if d.get("alternatives"):
                lines.append(f"**Alternatives considered:** {', '.join(d['alternatives'])}")
            lines.append("")

    # Insights
    if insights:
        lines += ["## 💡 Insights", ""]
        for ins in insights:
            lines.append(f"- {ins}")
        lines.append("")

    # Backlinks note
    lines += [
        "---",
        f"*Auto-generated by [claude-kg](https://github.com/you/claude-kg) on {date}*"
    ]

    note_path = folder / f"{slug}.md"
    note_path.write_text("\n".join(lines), encoding="utf-8")
    return note_path


def write_entity_notes(kg: dict, vault: Path, folder: Path):
    """Write/update individual entity notes with backlinks."""
    entities = kg.get("entities", [])
    session = kg.get("session", {})
    rels = kg.get("relationships", [])
    session_slug = f"{session.get('date', '')}-{slugify(session.get('title', 'session'))}"

    entity_map = {e["id"]: e["name"] for e in entities}
    entity_dir = folder / "entities"
    entity_dir.mkdir(parents=True, exist_ok=True)

    for entity in entities:
        name = entity["name"]
        slug = slugify(name)
        path = entity_dir / f"{slug}.md"

        # Gather relationships for this entity
        outgoing = [r for r in rels if r["from"] == entity["id"]]
        incoming = [r for r in rels if r["to"] == entity["id"]]

        # Read existing file to append sessions list
        existing_sessions: list[str] = []
        if path.exists():
            content = path.read_text(encoding="utf-8")
            # Extract existing session references
            for m in re.finditer(r"\[\[([\d]{4}-[^\]]+)\]\]", content):
                if m.group(1) not in existing_sessions:
                    existing_sessions.append(m.group(1))

        if session_slug not in existing_sessions:
            existing_sessions.insert(0, session_slug)

        lines = [
            f"---",
            f"title: \"{name}\"",
            f"type: {entity.get('type', 'Unknown').lower()}",
            f"tags: [entity, {entity.get('type', 'unknown').lower()}]",
            f"---",
            "",
            f"# {name}",
            "",
            f"> **Type:** {entity.get('type', '')}",
            "",
            f"{entity.get('description', '')}",
            "",
        ]

        if entity.get("properties"):
            lines += ["## Properties", ""]
            for k, v in entity["properties"].items():
                lines.append(f"- **{k}:** {v}")
            lines.append("")

        if outgoing:
            lines += ["## Outgoing Relationships", ""]
            for r in outgoing:
                to_name = entity_map.get(r["to"], r["to"])
                lines.append(f"- **{r['type']}** [[{slugify(to_name)}|{to_name}]]" + (
                    f" — {r['description']}" if r.get("description") else ""))
            lines.append("")

        if incoming:
            lines += ["## Incoming Relationships", ""]
            for r in incoming:
                from_name = entity_map.get(r["from"], r["from"])
                lines.append(f"- [[{slugify(from_name)}|{from_name}]] **{r['type']}** this" + (
                    f" — {r['description']}" if r.get("description") else ""))
            lines.append("")

        lines += ["## Sessions", ""]
        for sess in existing_sessions[:20]:  # keep last 20
            lines.append(f"- [[{sess}]]")
        lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")


def update_index(kg: dict, vault: Path, folder: Path):
    """Update the main index file in the KG folder."""
    session = kg.get("session", {})
    date = session.get("date", datetime.now().strftime("%Y-%m-%d"))
    title = session.get("title", "Untitled")
    slug = f"{date}-{slugify(title)}"
    summary = session.get("summary", "")
    tags = session.get("tags", [])
    cwd = session.get("cwd", "")

    index_path = folder / "INDEX.md"

    # Read existing entries
    existing: list[str] = []
    if index_path.exists():
        content = index_path.read_text(encoding="utf-8")
        # Find the sessions table section and extract rows
        for line in content.splitlines():
            if line.startswith("| [[") or line.startswith("| ![["):
                existing.append(line)

    new_row = f"| [[{slug}\\|{title}]] | {date} | `{cwd}` | {', '.join(tags)} |"
    # Prepend newest entry
    entries = [new_row] + [e for e in existing if slug not in e]

    lines = [
        "---",
        "title: Claude Code Knowledge Graph",
        "type: index",
        "tags: [index, claude-code]",
        "---",
        "",
        "# 🧠 Claude Code Knowledge Graph",
        "",
        "> Auto-generated index of all Claude Code sessions.",
        "",
        "## Sessions",
        "",
        "| Session | Date | Project | Tags |",
        "| ------- | ---- | ------- | ---- |",
    ]
    lines += entries[:100]  # keep last 100 sessions
    lines += [
        "",
        "## Entity Index",
        "",
        "Browse all entities → [[entities/]]",
        "",
        "---",
        f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*"
    ]

    index_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    # Read hook input from stdin
    hook_input = {}
    try:
        raw_input = sys.stdin.read()
        if raw_input.strip():
            hook_input = json.loads(raw_input)
    except Exception:
        pass

    transcript_path = hook_input.get("transcript_path", "")
    session_id = hook_input.get("session_id", "unknown")
    cwd = hook_input.get("cwd", os.getcwd())

    if not transcript_path:
        print("[KG] No transcript_path in hook input.", file=sys.stderr)
        sys.exit(0)

    if not ANTHROPIC_KEY:
        print("[KG] ANTHROPIC_API_KEY not set, skipping.", file=sys.stderr)
        sys.exit(0)

    print(f"[KG] Processing session {session_id[:12]}...", file=sys.stderr)

    # Read and parse transcript
    messages = read_transcript(transcript_path)
    conversation = extract_text_from_transcript(messages)

    if len(conversation.strip()) < MIN_LENGTH:
        print("[KG] Session too short, skipping.", file=sys.stderr)
        sys.exit(0)

    # Extract knowledge graph via Claude API
    session_meta = {"session_id": session_id, "cwd": cwd}
    kg = extract_knowledge_graph(conversation, session_meta)

    if not kg:
        print("[KG] Empty knowledge graph, skipping.", file=sys.stderr)
        sys.exit(0)

    # Set up Obsidian vault paths
    vault = Path(OBSIDIAN_VAULT)
    folder = vault / KG_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    entity_dir = folder / "entities"

    # Similarity pass (optional)
    similar_map = {}
    if FEAT.get("similarity", True):
        print("[KG] Finding similar entities...", file=sys.stderr)
        similar_map = find_similar_entities(kg.get("entities", []), entity_dir)
        if similar_map:
            print(f"[KG] Similarities: {', '.join(similar_map.keys())}", file=sys.stderr)

    # Strip features from KG data if disabled
    if not FEAT.get("decisions", True):
        kg["decisions"] = []
    if not FEAT.get("insights", True):
        kg["insights"] = []

    session_note = write_session_note(kg, vault, folder)
    write_entity_notes(kg, vault, folder, similar_map)
    update_index(kg, vault, folder)

    print(f"[KG] ✅ Knowledge graph updated → {session_note.name}", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()