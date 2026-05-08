#!/usr/bin/env python3
"""
Claude Code → KG Session Start Hook
Reads kg_config.json. If auto_context_on_start is true,
injects previous session context into Claude Code at session start.

Output goes to stdout — Claude Code reads it as initial context.
"""

import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime

# ── Load config ───────────────────────────────────────────────────────────────
def load_config() -> dict:
    defaults = {
        "kg_folder": "ClaudeCode",
        "features": {
            "auto_context_on_start": False,
        },
        "auto_context": {
            "max_sessions":       3,
            "include_entities":   True,
            "include_decisions":  True,
            "only_core_entities": True,
            "max_tokens_hint":    2000,
        },
        "mcp": {
            "importance_tiers": {"core": 20, "important": 8, "moderate": 3}
        }
    }
    config_path = Path.home() / ".claude" / "kg_config.json"
    if config_path.exists():
        try:
            raw  = re.sub(r"//.*", "", config_path.read_text(encoding="utf-8"))
            user = json.loads(raw)
            if "features" in user:
                defaults["features"].update(user.pop("features"))
            if "auto_context" in user:
                defaults["auto_context"].update(user.pop("auto_context"))
            if "mcp" in user:
                defaults["mcp"].update(user.pop("mcp"))
            defaults.update(user)
        except Exception as e:
            print(f"[KG-Start] Config error: {e}", file=sys.stderr)
    return defaults


CFG            = load_config()
OBSIDIAN_VAULT = os.getenv("OBSIDIAN_VAULT", str(Path.home() / "ObsidianVault"))
KG_FOLDER      = os.getenv("KG_FOLDER", CFG.get("kg_folder", "ClaudeCode"))
FEAT           = CFG.get("features", {})
ACTX           = CFG.get("auto_context", {})
TIERS          = CFG.get("mcp", {}).get("importance_tiers", {"core": 20, "important": 8, "moderate": 3})
# ─────────────────────────────────────────────────────────────────────────────


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_-]+", "-", text).strip("-")[:60]


def parse_frontmatter(content: str) -> tuple[dict, str]:
    fm, body = {}, content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    fm[k.strip()] = v.strip().strip('"')
            body = parts[2].strip()
    return fm, body


def get_summary(body: str) -> str:
    for line in body.splitlines():
        line = line.strip()
        if line.startswith(">") and len(line) > 5:
            return line[1:].strip()
        if len(line) > 30 and not line.startswith("#"):
            return line[:200]
    return ""


def importance_score(mentions: int, rel_count: int) -> int:
    return mentions * 2 + rel_count


def get_tier(score: int) -> str:
    if score >= TIERS["core"]:
        return "CORE"
    elif score >= TIERS["important"]:
        return "IMPORTANT"
    elif score >= TIERS["moderate"]:
        return "MODERATE"
    return "LOW"


def build_context(cwd: str) -> str:
    folder     = Path(OBSIDIAN_VAULT) / KG_FOLDER
    entity_dir = folder / "entities"

    if not folder.exists():
        return ""

    max_sessions    = ACTX.get("max_sessions", 3)
    inc_entities    = ACTX.get("include_entities", True)
    inc_decisions   = ACTX.get("include_decisions", True)
    only_core       = ACTX.get("only_core_entities", True)
    max_tokens_hint = ACTX.get("max_tokens_hint", 2000)

    cwd_lower = cwd.lower().replace("\\", "/")

    # ── Past sessions ─────────────────────────────────────────────────────────
    sessions   = []
    entity_set = set()

    for f in folder.glob("????-??-??-*.md"):
        try:
            fm, body = parse_frontmatter(f.read_text(encoding="utf-8"))
            note_cwd = fm.get("cwd", "").lower().replace("\\", "/")
            if cwd_lower not in note_cwd and note_cwd not in cwd_lower:
                continue
            sessions.append({
                "title":   fm.get("title", f.stem),
                "date":    fm.get("date", ""),
                "summary": get_summary(body),
            })
            for m in re.finditer(r"\[\[entities/([^\]|]+)", body):
                entity_set.add(m.group(1))
        except Exception:
            pass

    sessions.sort(key=lambda x: x["date"], reverse=True)

    if not sessions:
        return ""  # No history for this project, nothing to inject

    # ── Entities with signals ─────────────────────────────────────────────────
    entities = []
    if inc_entities and entity_dir.exists():
        for slug in entity_set:
            ep = entity_dir / f"{slug}.md"
            if not ep.exists():
                continue
            try:
                fm, body = parse_frontmatter(ep.read_text(encoding="utf-8"))
                mentions  = int(fm.get("mentions", 0))
                rel_count = len(re.findall(r"\(weight:\s*\d+\)", body))
                score     = importance_score(mentions, rel_count)
                tier      = get_tier(score)
                if only_core and tier not in ("CORE", "IMPORTANT"):
                    continue
                entities.append({
                    "name":     fm.get("title", slug),
                    "type":     fm.get("type", ""),
                    "tier":     tier,
                    "score":    score,
                    "mentions": mentions,
                    "rels":     rel_count,
                })
            except Exception:
                pass
        entities.sort(key=lambda x: x["score"], reverse=True)

    # ── Decisions ─────────────────────────────────────────────────────────────
    decisions = []
    if inc_decisions:
        for f in folder.glob("????-??-??-*.md"):
            try:
                fm, body = parse_frontmatter(f.read_text(encoding="utf-8"))
                note_cwd = fm.get("cwd", "").lower().replace("\\", "/")
                if cwd_lower not in note_cwd and note_cwd not in cwd_lower:
                    continue
                in_dec, cur = False, {}
                for line in body.splitlines():
                    if "## ⚡" in line:
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
                            cur = {"title": line[4:].strip(), "rationale": ""}
                        elif "**Rationale:**" in line and cur:
                            cur["rationale"] = line.replace("**Rationale:**", "").strip()
                if cur:
                    decisions.append(cur)
            except Exception:
                pass

    # ── Assemble context block ────────────────────────────────────────────────
    lines = [
        "---",
        "# 🧠 Knowledge Graph Context",
        f"Project: {cwd}",
        f"Loaded: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "> This context was auto-injected from your Knowledge Graph (claude-kg).",
        "> It summarizes previous sessions to help you start faster.",
        "",
    ]

    # Sessions
    lines += [f"## Recent sessions ({min(len(sessions), max_sessions)} of {len(sessions)})", ""]
    for s in sessions[:max_sessions]:
        lines.append(f"**{s['date']} — {s['title']}**")
        if s["summary"]:
            lines.append(f"  {s['summary']}")
        lines.append("")

    # Entities
    if entities:
        label = "CORE + IMPORTANT entities" if only_core else "All entities"
        lines += [f"## {label} — sorted by importance", ""]
        lines.append(f"{'Entity':<28} {'Type':<14} {'Tier':<12} {'Score':>5}")
        lines.append("-" * 62)
        for e in entities[:20]:
            tier_icon = {"CORE": "⭐⭐⭐", "IMPORTANT": "⭐⭐", "MODERATE": "⭐"}.get(e["tier"], "○")
            lines.append(f"{e['name']:<28} {e['type']:<14} {tier_icon} {e['tier']:<8} {e['score']:>5}")
        lines.append("")

    # Decisions
    if decisions:
        lines += [f"## Past decisions ({len(decisions)})", ""]
        for d in decisions[:8]:
            lines.append(f"- **{d['title']}**")
            if d["rationale"]:
                lines.append(f"  {d['rationale']}")
        lines.append("")

    lines.append("---")

    result = "\n".join(lines)

    # Soft trim to max_tokens_hint (approx 4 chars per token)
    char_limit = max_tokens_hint * 4
    if len(result) > char_limit:
        result = result[:char_limit] + "\n... (context trimmed to stay within token limit)"

    return result


def main():
    # Check feature flag first — exit immediately if disabled
    if not FEAT.get("auto_context_on_start", False):
        sys.exit(0)

    hook_input = {}
    try:
        raw = sys.stdin.read()
        if raw.strip():
            hook_input = json.loads(raw)
    except Exception:
        pass

    cwd = hook_input.get("cwd", os.getcwd())

    context = build_context(cwd)

    if not context:
        sys.exit(0)

    # Print to stdout — Claude Code injects this as session context
    print(context)
    print(f"[KG] ✅ Context injected ({len(context)} chars)", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()