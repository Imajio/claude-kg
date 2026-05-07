#!/usr/bin/env python3
"""
claude-kg installer
Works on Windows, macOS, and Linux.
"""

import os
import sys
import json
import shutil
import platform
from pathlib import Path

REPO_URL = "https://github.com/YOUR_USERNAME/claude-kg"

def print_banner():
    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║   claude-kg  ·  installer            ║")
    print("  ║   Claude Code → Obsidian KG          ║")
    print("  ╚══════════════════════════════════════╝")
    print()

def ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    try:
        val = input(f"  {prompt}{hint}: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n\nAborted.")
        sys.exit(0)
    return val or default

def ok(msg):  print(f"  ✅  {msg}")
def err(msg): print(f"  ❌  {msg}")
def info(msg):print(f"  ℹ️   {msg}")
def warn(msg):print(f"  ⚠️   {msg}")


def install():
    print_banner()
    is_windows = platform.system() == "Windows"

    # ── Locate files ──────────────────────────────────────
    script_dir = Path(__file__).parent.resolve()
    extractor  = script_dir / "hooks" / "kg_extractor.py"
    mcp_server = script_dir / "hooks" / "kg_mcp_server.py"

    for f in [extractor, mcp_server]:
        if not f.exists():
            err(f"{f.name} not found. Make sure you run this from the repo root.")
            sys.exit(1)

    # ── Claude hooks folder ───────────────────────────────
    hooks_dir = Path.home() / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(extractor,  hooks_dir / "kg_extractor.py")
    shutil.copy2(mcp_server, hooks_dir / "kg_mcp_server.py")
    ok(f"Scripts copied → {hooks_dir}")

    # ── Obsidian vault path ───────────────────────────────
    print()
    info("Where is your Obsidian vault?")
    default_vault = str(Path.home() / "ObsidianVault")
    vault_path = ask("Obsidian vault path", default_vault)
    vault_path = vault_path.replace("~", str(Path.home()))

    vault = Path(vault_path)
    if not vault.exists():
        vault.mkdir(parents=True, exist_ok=True)
        ok(f"Created vault directory: {vault}")

    kg_folder = ask("KG subfolder inside vault", "ClaudeCode")

    # ── API key ───────────────────────────────────────────
    print()
    info("You need an Anthropic API key from console.anthropic.com")
    existing_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if existing_key:
        ok(f"ANTHROPIC_API_KEY already set in environment.")
        api_key = existing_key
    else:
        api_key = ask("Anthropic API key (sk-ant-...)", "")
        if not api_key:
            warn("No API key provided — you can set ANTHROPIC_API_KEY manually later.")

    # ── Update settings.json ──────────────────────────────
    print()
    settings_path = Path.home() / ".claude" / "settings.json"

    if is_windows:
        extractor_cmd = f'python "{hooks_dir / "kg_extractor.py"}"'
        mcp_script    = str(hooks_dir / "kg_mcp_server.py")
    else:
        extractor_cmd = f'python3 "{hooks_dir / "kg_extractor.py"}"'
        mcp_script    = str(hooks_dir / "kg_mcp_server.py")

    # Read existing settings
    settings = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            warn("Could not parse existing settings.json — will merge carefully.")

    # Inject hook
    settings.setdefault("hooks", {})
    settings["hooks"]["SessionEnd"] = [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": extractor_cmd,
                    "async": True
                }
            ]
        }
    ]

    # Inject MCP server
    settings.setdefault("mcpServers", {})
    settings["mcpServers"]["knowledge-graph"] = {
        "type": "stdio",
        "command": "python" if is_windows else "python3",
        "args": [mcp_script],
        "env": {
            "OBSIDIAN_VAULT": str(vault),
            "KG_FOLDER": kg_folder,
            "ANTHROPIC_API_KEY": api_key or ""
        }
    }

    settings_path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    ok(f"settings.json updated → {settings_path}")

    # ── Set env vars hint ─────────────────────────────────
    print()
    if is_windows:
        print("  ─────────────────────────────────────────────")
        print("  Set these System Environment Variables:")
        print()
        print(f"    ANTHROPIC_API_KEY  =  {api_key or 'your-key-here'}")
        print(f"    OBSIDIAN_VAULT     =  {vault}")
        print(f"    KG_FOLDER          =  {kg_folder}")
        print()
        print("  How: Start → 'Environment Variables' → User variables → New")
        print("  ─────────────────────────────────────────────")
    else:
        shell_file = Path.home() / (".zshrc" if Path.home().joinpath(".zshrc").exists() else ".bashrc")
        lines = [
            f'\n# claude-kg',
            f'export ANTHROPIC_API_KEY="{api_key or "your-key-here"}"',
            f'export OBSIDIAN_VAULT="{vault}"',
            f'export KG_FOLDER="{kg_folder}"',
        ]
        with open(shell_file, "a") as f:
            f.write("\n".join(lines) + "\n")
        ok(f"Environment variables written to {shell_file}")
        info(f"Run: source {shell_file}")

    # ── Done ──────────────────────────────────────────────
    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║   Installation complete! 🎉           ║")
    print("  ║                                      ║")
    print("  ║   1. Restart Claude Code             ║")
    print("  ║   2. Run a session                   ║")
    print("  ║   3. Open Obsidian                   ║")
    print("  ╚══════════════════════════════════════╝")
    print()


if __name__ == "__main__":
    install()
