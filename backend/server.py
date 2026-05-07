#!/usr/bin/env python3
"""
Local server that receives conversations from the Chrome extension
and processes them into Obsidian knowledge graph notes.
Run: python server.py
"""

import json
import os
import sys
import re
import threading
from pathlib import Path
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request

# ── CONFIG ────────────────────────────────────────────────────────────────────
PORT           = 7842
OBSIDIAN_VAULT = os.getenv("OBSIDIAN_VAULT", str(Path.home() / "ObsidianVault"))
KG_FOLDER      = os.getenv("KG_FOLDER", "ClaudeCode")
ANTHROPIC_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
MODEL          = "claude-sonnet-4-6"
# ─────────────────────────────────────────────────────────────────────────────


def call_claude(prompt: str) -> str:
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
        print(f"[KG] API error: {e}")
        return ""


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:60]


def extract_knowledge_graph(conversation: str, title_hint: str = "") -> dict:
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = f"""You are a knowledge graph builder. Analyze this Claude AI conversation and extract structured knowledge.

DATE: {date}
TITLE HINT: {title_hint}

CONVERSATION:
{conversation[:12000]}

Return ONLY valid JSON (no markdown, no explanation):
{{
  "session": {{
    "title": "Short descriptive title (max 8 words)",
    "summary": "2-3 sentence summary of what was discussed/accomplished",
    "date": "{date}",
    "tags": ["tag1", "tag2"]
  }},
  "entities": [
    {{
      "id": "PascalCaseID",
      "type": "Concept|Tool|Decision|Task|Person|Place|Topic|Code|Resource",
      "name": "Human readable name",
      "description": "1-2 sentence description"
    }}
  ],
  "relationships": [
    {{
      "from": "EntityID",
      "to": "EntityID",
      "type": "RELATES_TO|USES|EXPLAINS|LEADS_TO|CONTRADICTS|DEPENDS_ON|IS_PART_OF",
      "description": "brief description"
    }}
  ],
  "decisions": [
    {{
      "title": "Decision or conclusion reached",
      "rationale": "Why"
    }}
  ],
  "insights": ["Key insight or takeaway"]
}}"""

    raw = call_claude(prompt)
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except Exception as e:
        print(f"[KG] Parse error: {e}")
        return {}


def write_notes(kg: dict):
    session   = kg.get("session", {})
    entities  = kg.get("entities", [])
    rels      = kg.get("relationships", [])
    decisions = kg.get("decisions", [])
    insights  = kg.get("insights", [])

    date  = session.get("date", datetime.now().strftime("%Y-%m-%d"))
    title = session.get("title", "Untitled")
    slug  = f"{date}-{slugify(title)}"
    tags  = session.get("tags", [])

    vault  = Path(OBSIDIAN_VAULT)
    folder = vault / KG_FOLDER
    folder.mkdir(parents=True, exist_ok=True)

    entity_map = {e["id"]: e["name"] for e in entities}

    # ── Session note ──────────────────────────────────────────
    lines = [
        "---",
        f'title: "{title}"',
        f"date: {date}",
        f"tags: [{', '.join(tags)}]",
        "type: claude-conversation",
        "---",
        "",
        f"# {title}",
        "",
        f"> {session.get('summary', '')}",
        "",
        f"**Date:** {date}",
        "",
    ]

    if entities:
        lines += ["## 🔷 Entities", ""]
        by_type: dict[str, list] = {}
        for e in entities:
            by_type.setdefault(e.get("type", "Other"), []).append(e)
        for etype, elist in sorted(by_type.items()):
            lines.append(f"### {etype}")
            for e in elist:
                lines.append(f"- [[entities/{slugify(e['name'])}|{e['name']}]] — {e.get('description', '')}")
            lines.append("")

    if rels:
        lines += ["## 🔗 Relationships", ""]
        for r in rels:
            fn = entity_map.get(r["from"], r["from"])
            tn = entity_map.get(r["to"],   r["to"])
            fl = f"[[entities/{slugify(fn)}|{fn}]]"
            tl = f"[[entities/{slugify(tn)}|{tn}]]"
            desc = f" — {r['description']}" if r.get("description") else ""
            lines.append(f"- {fl} **{r['type']}** {tl}{desc}")
        lines.append("")

    if decisions:
        lines += ["## ⚡ Decisions & Conclusions", ""]
        for d in decisions:
            lines.append(f"### {d['title']}")
            lines.append(f"{d.get('rationale', '')}")
            lines.append("")

    if insights:
        lines += ["## 💡 Insights", ""]
        for ins in insights:
            lines.append(f"- {ins}")
        lines.append("")

    lines += ["---", f"*Auto-generated by claude-kg on {date}*"]

    note_path = folder / f"{slug}.md"
    note_path.write_text("\n".join(lines), encoding="utf-8")

    # ── Entity notes ──────────────────────────────────────────
    entity_dir = folder / "entities"
    entity_dir.mkdir(parents=True, exist_ok=True)

    for entity in entities:
        name = entity["name"]
        epath = entity_dir / f"{slugify(name)}.md"

        existing_sessions: list[str] = []
        if epath.exists():
            content = epath.read_text(encoding="utf-8")
            for m in re.finditer(r"\[\[(\d{4}-[^\]|]+)", content):
                s = m.group(1)
                if s not in existing_sessions:
                    existing_sessions.append(s)

        if slug not in existing_sessions:
            existing_sessions.insert(0, slug)

        outgoing = [r for r in rels if r["from"] == entity["id"]]
        incoming = [r for r in rels if r["to"]   == entity["id"]]

        eLines = [
            "---",
            f'title: "{name}"',
            f"type: {entity.get('type', 'concept').lower()}",
            f"tags: [entity, {entity.get('type', 'concept').lower()}]",
            "---",
            "",
            f"# {name}",
            "",
            f"> **Type:** {entity.get('type', '')}",
            "",
            entity.get("description", ""),
            "",
        ]

        if outgoing:
            eLines += ["## Outgoing", ""]
            for r in outgoing:
                tn = entity_map.get(r["to"], r["to"])
                eLines.append(f"- **{r['type']}** [[entities/{slugify(tn)}|{tn}]]")
            eLines.append("")

        if incoming:
            eLines += ["## Incoming", ""]
            for r in incoming:
                fn = entity_map.get(r["from"], r["from"])
                eLines.append(f"- [[entities/{slugify(fn)}|{fn}]] **{r['type']}** this")
            eLines.append("")

        eLines += ["## Sessions", ""]
        for s in existing_sessions[:20]:
            eLines.append(f"- [[{s}]]")
        eLines.append("")

        epath.write_text("\n".join(eLines), encoding="utf-8")

    # ── Update index ──────────────────────────────────────────
    index_path = folder / "INDEX.md"
    existing_rows: list[str] = []
    if index_path.exists():
        for line in index_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("| [[") and slug not in line:
                existing_rows.append(line)

    new_row = f"| [[{slug}\\|{title}]] | {date} | {', '.join(tags)} |"
    rows = [new_row] + existing_rows

    index_lines = [
        "---",
        "title: Claude Conversations Knowledge Graph",
        "type: index",
        "tags: [index, claude]",
        "---",
        "",
        "# 🧠 Claude Knowledge Graph",
        "",
        "> Auto-generated index of all Claude conversations.",
        "",
        "## Conversations",
        "",
        "| Session | Date | Tags |",
        "| ------- | ---- | ---- |",
    ] + rows[:100] + [
        "",
        "## All Entities",
        "",
        "Browse → `ClaudeCode/entities/`",
        "",
        "---",
        f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*"
    ]

    index_path.write_text("\n".join(index_lines), encoding="utf-8")
    print(f"[KG] ✅ Written → {note_path.name}")
    return slug


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # silence default logging

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        if self.path == "/process":
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)
            try:
                data         = json.loads(body)
                conversation = data.get("conversation", "")
                title_hint   = data.get("title", "")

                if len(conversation.strip()) < 100:
                    self._respond(400, {"error": "Conversation too short"})
                    return

                if not ANTHROPIC_KEY:
                    self._respond(500, {"error": "ANTHROPIC_API_KEY not set"})
                    return

                # Process in background so browser doesn't time out
                def process():
                    kg   = extract_knowledge_graph(conversation, title_hint)
                    if kg:
                        slug = write_notes(kg)
                        print(f"[KG] Done: {slug}")

                threading.Thread(target=process, daemon=True).start()
                self._respond(200, {"status": "processing", "message": "Knowledge graph is being built..."})

            except Exception as e:
                self._respond(500, {"error": str(e)})

        elif self.path == "/ping":
            self._respond(200, {"status": "ok", "vault": OBSIDIAN_VAULT})
        else:
            self._respond(404, {"error": "Not found"})

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "https://claude.ai")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _respond(self, code: int, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    if not ANTHROPIC_KEY:
        print("⚠️  ANTHROPIC_API_KEY not set!")
        print("   Set it and restart.")

    vault = Path(OBSIDIAN_VAULT)
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  Claude → Obsidian KG Server")
    print(f"  Port:  {PORT}")
    print(f"  Vault: {vault / KG_FOLDER}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    server = HTTPServer(("127.0.0.1", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[KG] Server stopped.")
