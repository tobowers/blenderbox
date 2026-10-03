"""Review or apply the Blender MCP -> Blenderbox migration, with private backups."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import time
import tomllib

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--apply", action="store_true", help="Write changes; default only lists affected files")
args = parser.parse_args()
home = Path.home()
changes = {}

codex = home / ".codex/config.toml"
if codex.exists():
    original = codex.read_text()
    updated = re.sub(r"(?ms)^\[mcp_servers\.blender(?:\.[^\]]+)?\]\s*\n.*?(?=^\[|\Z)", "", original)
    if updated != original:
        tomllib.loads(updated)
        changes[codex] = updated

for path, nested in [(home / ".claude.json", ("mcpServers",)),
                     (home / ".config/opencode/opencode.json", ("mcp", "servers"))]:
    if path.exists():
        data = json.loads(path.read_text())
        section = data
        for key in nested:
            section = section.get(key, {})
        if "blender" in section:
            del section["blender"]
            changes[path] = json.dumps(data, indent=2, ensure_ascii=False) + "\n"

instruction = """## Blenderbox

Blender is available through `/Users/tobowers/.local/bin/blenderbox`. For Blender work, read `/Users/tobowers/.agents/skills/blenderbox/SKILL.md`, which links to the full workflow.
"""
for path in (home / ".codex/AGENTS.md", home / ".config/opencode/AGENTS.md", home / ".claude/CLAUDE.md"):
    original = path.read_text() if path.exists() else ""
    updated = re.sub(r"(?ms)^## Blender (?:MCP|box)\s*\n.*?(?=^## |\Z)", "", original)
    # Handle the new heading on repeat invocations as well.
    updated = re.sub(r"(?ms)^## Blenderbox\s*\n.*?(?=^## |\Z)", "", updated)
    updated = updated.rstrip() + ("\n\n" if updated.strip() else "") + instruction
    if updated != original:
        changes[path] = updated

opencode_command = home / ".config/opencode/commands/blender.md"
if opencode_command.exists():
    command = """---
description: Inspect Blenderbox sessions or run a Blender task in an isolated headless process
---

Current Blenderbox sessions:

!`/Users/tobowers/.local/bin/blenderbox sessions`

Read `/Users/tobowers/.agents/skills/blenderbox/SKILL.md`. Use Blenderbox for Blender tasks.
Create a session for this task or reuse the session already owned by this chat; do not attach
to another task's session. The local daemon starts automatically. Execute `bpy`, inspect
state, render previews and save/export deliverables before closing. Report artifact paths.

If no task arguments are supplied, summarize the listed sessions. Do not create a new session
just to report status. Do not start the old Blender MCP/headless service.

User request: $ARGUMENTS
"""
    if opencode_command.read_text() != command:
        changes[opencode_command] = command

backup = home / ".local/share/blenderbox/migration-backups" / time.strftime("%Y%m%d-%H%M%S")
if args.apply and changes:
    backup.mkdir(parents=True, mode=0o700)
    os.chmod(backup, 0o700)
    manifest = []
    for path, text in changes.items():
        entry = {"path": str(path), "existed": path.exists()}
        if path.exists():
            saved = backup / path.relative_to(home)
            saved.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            shutil.copy2(path, saved)
            saved.chmod(0o600)
            entry["backup"] = str(saved)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".blenderbox-new")
        temporary.write_text(text)
        temporary.chmod(path.stat().st_mode & 0o777 if path.exists() else 0o600)
        temporary.replace(path)
        manifest.append(entry)
    (backup / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps({"applied": args.apply, "files": [str(p) for p in changes],
                  "backup": str(backup) if args.apply and changes else None}, indent=2))
