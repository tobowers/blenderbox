---
name: blenderbox
description: Create, edit, inspect, render, and export Blender scenes using isolated persistent headless sessions through the local blenderbox CLI.
---

Use the `blenderbox` CLI for Blender work. Confirm it is available with `blenderbox --version`; use the installed binary's absolute path if the agent's PATH omits it. The daemon starts automatically. Each session has its own Blender process and workspace. Create a session for the task; fork a checkpoint when independent variants are useful. Do not share a session with unrelated agents.

```bash
SESSION=$(blenderbox create)
blenderbox exec "$SESSION" <<'PY'
import bpy
bpy.data.objects['Cube'].name = 'MyCube'
PY
blenderbox inspect "$SESSION"
blenderbox preview "$SESSION" --object MyCube
blenderbox save "$SESSION"
blenderbox export "$SESSION" --format glb
blenderbox close "$SESSION"
```

`exec` reads a Python file or stdin. Python globals persist until the process closes; an optional `result` variable returns JSON, alongside captured Python stdout/stderr. `eval SESSION 'expression'` returns JSON directly. Use `--json` for a full response envelope. Errors are JSON on stderr with a nonzero exit code; a Python exception leaves the session usable. An execution timeout terminates that session. Native Blender output is in the workspace's `logs/blender.log`.

Prefer direct Blender data APIs when practical; there is no interactive window. Use `preview` for visual inspection and read its returned absolute PNG path with the available image viewer. `render` uses the scene's camera and settings. The default preview uses CPU Cycles and neutral lighting in a temporary scene.

Use `checkpoint SESSION` and `fork CHECKPOINT_OR_SESSION` to branch saved Blender state and workspace assets. Python globals are not checkpointed. Checkpoints include session-local assets; put external dependencies in the workspace before checkpointing. `put SESSION HOST_FILE assets/name` transfers a file. `get SESSION RELATIVE_PATH [HOST_DESTINATION]` locates or copies output. `import SESSION model.glb` copies and imports an asset; use `--resources DIRECTORY` for OBJ/FBX files with sidecars. glTF buffer/image sidecars are copied automatically.

Save or export deliverables before closing. `close` terminates Blender and retains saved files/logs; it does not automatically save unsaved work. `status SESSION` reports PID, status and workspace; `sessions` lists records. Only close sessions belonging to the current task. Run `blenderbox --help` or `blenderbox COMMAND --help` for options. Arbitrary `bpy` is ordinary trusted local Python, with host filesystem/network access.

Read [references/cli.md](references/cli.md) for asset handling, variant comparison and recovery workflows. Read [references/python.md](references/python.md) when orchestrating sessions through the Python SDK. `blenderbox help --all` prints the complete command reference; `blenderbox skills show --file references/cli.md` reads bundled guidance without installing it.
