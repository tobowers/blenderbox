# Blenderbox

**Give every coding agent its own persistent, headless Blender.**

Blenderbox is a local CLI and Python SDK for creating independent Blender sessions, executing ordinary `bpy`, inspecting scenes, rendering previews, saving files, and branching work with checkpoints. Multiple agents can use the same command while their Blender processes and scene state remain separate.

```bash
SESSION=$(blenderbox create)
blenderbox exec "$SESSION" ./build.py
blenderbox preview "$SESSION"
blenderbox save "$SESSION"
blenderbox export "$SESSION" --format glb
blenderbox close "$SESSION"
```

No Blender MCP server or extension is required. The supervisor starts automatically.

- [Why it exists](#why-it-exists)
- [Install](#install)
- [Set up your agents](#set-up-your-agents)
- [For agents: run from source or rebuild without installing](#for-agents-run-from-source-or-rebuild-without-installing)

## Why it exists

An agent attached to one existing Blender instance inherits that instance's scene, Python state, configuration, and failure boundary. Sharing that instance between unrelated tasks makes it easy for one agent to change another agent's work. Starting another command-line Blender for every script avoids some sharing, but also discards the persistent state needed for an iterative modeling workflow.

Blenderbox gives agents a session abstraction, much like a persistent browser session:

> One session = one Blender process + one workspace + one Python namespace + one private RPC endpoint.

An agent creates a session, writes `bpy`, examines an image, and revises the same scene. Another agent can do the same thing concurrently in a different process. A checkpoint can become several independent variants, and a crash in one variant leaves the others running.

The command provides infrastructure around Blender. Modeling, materials, geometry nodes, animation, rigs, and advanced import/export remain Blender Python. Agents do not need a separate handcrafted command for every Blender operation.

```text
Agents → CLI / Python SDK → local supervisor
                             ├── session A → Blender A + workspace A
                             ├── session B → Blender B + workspace B
                             └── session C → Blender C + workspace C
```

The current implementation is for trusted local agents. Each process has isolated Blender state and user paths, but arbitrary Python still has normal host filesystem and network access. It is not an OS sandbox.

## Install

### Requirements

- A Blender executable installed on the computer. The integration suite has been verified with Blender 5.2.2 LTS on macOS; other versions should be checked with the suite before relying on them.
- Python 3.10 or newer for the CLI and supervisor. `bpy` runs inside Blender's own Python; do not install a separate `bpy` package for normal use.
- `uv` for the recommended tool installation, or `pip` inside a dedicated virtual environment.
- A Unix environment. The current supervisor uses Unix sockets, `fcntl`, process groups, and `ps`; native Windows support would require a different process/transport backend.

The runtime uses the Python standard library and has no third-party runtime dependencies. Build tooling is resolved during installation. The commands below install from a repository checkout; no registry release is assumed.

### Install the command, then choose your agent skills

Run these commands from the repository root:

```bash
uv tool install --python python3 .
uv tool dir --bin
```

Add the directory reported by `uv tool dir --bin` to your shell and agent PATH. On this computer it is `~/.local/bin`, and the command is `/Users/tobowers/.local/bin/blenderbox`. An agent can also invoke the binary by its absolute path.

Verify the installation and install skills for the clients you use:

```bash
blenderbox --version
blenderbox doctor
blenderbox skills install --agent codex
# Or install for every supported agent location:
blenderbox skills install --agent all
```

`doctor` reports the supervisor PID, state directory, Blender executable, and Blender version. It starts the supervisor and checks the executable, but does not create a persistent Blender session.

### Convenience installer

For this computer's complete command-and-skills setup, run:

```bash
python3 scripts/install.py
blenderbox doctor
```

The installer reinstalls the command and installs the complete skill for Codex, Claude Code, OpenCode, and shared agents. It uses `--force` when installing skills, so it replaces existing Blenderbox skill directories, including local edits. Use the selective installation commands above if you want to preserve customized skills. It does not change MCP configuration.

### Install without uv

From the repository root, create a dedicated environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/blenderbox doctor
.venv/bin/blenderbox skills install --agent codex
```

Give agents the absolute path to `.venv/bin/blenderbox`, or expose that executable through a launcher on their PATH. Keep the environment available for as long as agents use the command.

### Select Blender and the state directory

Blender discovery checks `BLENDERBOX_BLENDER`, then `blender` on PATH, then `/Applications/Blender.app/Contents/MacOS/Blender` on macOS. Use an explicit executable path when needed:

```bash
blenderbox create --blender /absolute/path/to/blender
```

For a default executable, set `BLENDERBOX_BLENDER` in the environment that starts the supervisor. Restart an already running supervisor for that environment change to take effect.

| Setting | Meaning |
| --- | --- |
| `BLENDERBOX_HOME` | Persistent state root; defaults to `~/.local/share/blenderbox` |
| `blenderbox --home DIRECTORY COMMAND` | Select a state root for this invocation; put `--home` before the command |
| `BLENDERBOX_BLENDER` | Default executable path, read by the supervisor |
| `create --blender PATH` | Executable for one new session; takes a path, not a version number |
| `create --threads N` | Blender render threads per process; defaults to 2 |
| `COMMAND --timeout SECONDS` | Blender execution/startup deadline; defaults to 60, maximum 86400 |

All clients using the same state root share the supervisor and session registry. They still need separate sessions for unrelated tasks. Use a separate state root for development or experiments.

### Update

From the updated checkout:

```bash
uv tool install --python python3 --force --reinstall --no-cache .
blenderbox skills install --agent all --dry-run
```

If you want to replace the installed skills, run `blenderbox skills install --agent all --force`. To load the new supervisor implementation, stop it and start it again:

```bash
blenderbox daemon stop
blenderbox doctor
```

Schedule that restart between commands. Live Blender sessions survive a supervisor stop and can be adopted after restart, but keep their existing bootstrap code. Create fresh sessions to use an updated Blender-side implementation. `daemon stop --close-sessions` also closes every active session in that state root; use it only when you have authority to close all those tasks.

## Set up your agents

### 1. Make the command reachable

Check from the agent's execution environment, which may have a different PATH from your interactive terminal:

```bash
blenderbox --version
blenderbox --help
blenderbox doctor
```

If the command is missing, supply its absolute path. If Blender discovery fails, set the executable as described above. No MCP configuration or Blender add-on is needed for a fresh setup.

### 2. Install or read the skill

The skill has a tiny entrypoint that announces Blender access and links to the full workflow in `references/workflow.md`. Only its short name and description are needed for initial discovery; the workflow is read when an agent starts Blender work. The skill and supporting references ship inside the installed package. They work without this repository and can be inspected without launching Blender or the supervisor:

```bash
blenderbox skills list
blenderbox skills show
blenderbox skills show --file references/workflow.md
blenderbox skills show --file references/cli.md
blenderbox skills show --file references/python.md
```

Install for the desired clients:

```bash
blenderbox skills install --agent codex
blenderbox skills install --agent claude --agent opencode
blenderbox skills install --agent shared
blenderbox skills install --path ./my-agent/skills
```

| Agent target | Parent skill directory |
| --- | --- |
| `codex` | `$CODEX_HOME/skills`, or `~/.codex/skills` |
| `claude` | `~/.claude/skills` |
| `opencode` | `$XDG_CONFIG_HOME/opencode/skills`, or `~/.config/opencode/skills` |
| `shared` | `~/.agents/skills` |
| `all` | All four locations above |

The installer appends `blenderbox/` to the parent directory and copies `SKILL.md` plus its references. An identical installation is unchanged. Different existing content is preserved unless you supply `--force`; `--dry-run` reports destinations and conflicts without writing. Reload your agent's skill discovery after installation.

The source folder [skills/blenderbox](skills/blenderbox/SKILL.md) is also a standard installable skill directory. A compatible skill installer can install that directory from the repository. When copying it manually, copy the entire directory, including `references/`.

### 3. Give the agent a clear operating instruction

Add this to the relevant project or global agent instructions, replacing `blenderbox` with its absolute binary path if necessary:

```text
Use blenderbox for Blender work. Create a session for this task and execute
ordinary bpy with exec. Reuse that session while iterating; use checkpoints
and forks for independent variants. Read preview images from their returned
absolute paths. Save/export deliverables before closing. Only close sessions
owned by this task. Read the installed Blenderbox skill and command help
for detailed usage. Blender MCP is not required for this workflow.
```

Skill installation does not edit these instructions or remove old MCP configuration. If replacing an existing MCP setup, update its instructions too so agents do not keep choosing the old route.

This checkout includes `scripts/migrate_agents.py` for the specific `/Users/tobowers` setup. It requires Python 3.11+ and contains that computer's absolute paths; review or adapt it before using it elsewhere:

```bash
python3 scripts/migrate_agents.py          # Review affected files
python3 scripts/migrate_agents.py --apply  # Back up and migrate
```

That helper removes Blender MCP entries, updates Blender instructions and the existing OpenCode Blender command, and retains the old MCP package/add-on/launcher. Private originals and a rollback manifest are stored under `~/.local/share/blenderbox/migration-backups/`. Restart clients to reload configuration; old chats may still contain previous instructions.

### 4. Verify a complete agent workflow

This example starts from Blender's default cube, branches the scene, renders feedback, and copies a deliverable out:

```bash
SESSION=$(blenderbox create)

blenderbox exec "$SESSION" <<'PY'
import bpy
cube = bpy.data.objects['Cube']
cube.name = 'AgentCube'
cube.scale.z = 2
bpy.context.view_layer.update()
result = {'name': cube.name, 'dimensions': list(cube.dimensions)}
PY

blenderbox eval "$SESSION" 'list(bpy.data.objects.keys())'
blenderbox inspect "$SESSION" object AgentCube
blenderbox preview "$SESSION" --object AgentCube

CHECKPOINT=$(blenderbox checkpoint "$SESSION")
VARIANT=$(blenderbox fork "$CHECKPOINT")
blenderbox exec "$VARIANT" <<'PY'
bpy.data.objects['AgentCube'].scale.x = 2
PY
blenderbox preview "$VARIANT" --view front
blenderbox save "$VARIANT"
blenderbox export "$VARIANT" --format glb --output exports/model.glb
blenderbox get "$VARIANT" exports/model.glb ./model.glb

blenderbox close "$SESSION"
blenderbox close "$VARIANT"
```

`preview` returns an absolute PNG path. The agent should open that image with its available image viewer, judge the geometry, and revise it with `exec`. Closing a session does not save unsaved work; saved files and logs remain afterward.

### Execution, results, and recovery

`exec` reads a file or stdin and keeps its Python globals between calls. `bpy` and `workspace`, the absolute session directory, are already available. Code runs with the workspace as its current directory. Set `result` to return JSON data; it is cleared before each execution while other globals persist. `eval` returns an expression's JSON value. Return primitives, lists, dictionaries, or mathutils vectors/matrices rather than raw Blender datablocks.

`create`, `checkpoint`, and `fork` print plain IDs for shell assignment. Other session commands print JSON. `--json` adds the full session response envelope with request ID and duration. `exec` returns `{value, stdout, stderr}`. Native Blender output is written to `WORKSPACE/logs/blender.log`; the supervisor log is `BLENDERBOX_HOME/daemon.log`. Help and `skills show` normally print documentation.

Commands execute in FIFO order within a session; different sessions execute concurrently. Execution timeouts exclude queue wait and terminate the affected Blender process. Python exceptions return a traceback and leave the session alive, but mutations before the exception remain. Execution is not transactional. Client Ctrl-C does not guarantee server cancellation; `close SESSION` can interrupt a busy process.

Use `status SESSION` for lifecycle/PID/workspace information and `inspect SESSION` for Blender scene state. After a crash or timeout, recover into a new session with `fork CHECKPOINT` or `create --from SAVED.blend`. Checkpoints preserve saved Blender state and workspace assets, not Python globals or external host files.

### Rendering, assets, and delivery

| Operation | Purpose |
| --- | --- |
| `preview` | Frame geometry using a temporary camera, world, neutral lights, and seeded CPU Cycles; no scene camera required |
| `render` | Render a PNG using the actual scene's camera, engine, lighting, frame, and resolution |
| `save` | Save editable `.blend` state inside the workspace |
| `checkpoint` / `fork` | Snapshot workspace state and create independent variants |
| `put` / `get` / `files` | Copy files in, locate/copy files out, or list artifacts |
| `import` / `export` | Import/export common model formats through Blender |

Preview supports object/collection scopes, perspective or axis views, resolution, samples, and an output path. It removes its temporary datablocks and restores the source frame. Hidden render geometry is excluded; complex instancing or geometry nodes may need a custom camera and `render` for finer control. Configure final rendering through `bpy`. A preview supplies its own lights, so use `render` when comparing custom lighting.

Model import supports GLB, glTF, OBJ, STL, PLY, and FBX. Export supports those formats and `.blend`. Other formats/settings remain available through arbitrary `bpy`. Import copies the model into the workspace; local glTF buffers/images are copied automatically. For OBJ/FBX sidecars, use `import SESSION MODEL --resources DIRECTORY` with a directory containing the model and its dependencies.

Session paths passed to file-transfer/output commands must be relative and remain inside the workspace. Import/put sources and get destinations are host paths. `get` without a destination returns a file location, not its contents. External files referenced by an existing `.blend` must be copied into the workspace or packed explicitly if a checkpoint/deliverable should be self-contained.

### Python orchestration

The SDK is included in the tool environment. To import it from another Python environment, install this checkout into that environment. The CLI and SDK share the same supervisor when their `BLENDERBOX_HOME` settings match.

```python
from blenderbox import Blender, BoxError

with Blender.create(threads=2) as b:
    b.exec("bpy.data.objects['Cube'].name = 'Product'")
    print(b.inspect())
    print(b.preview(object='Product')['path'])
    b.save()
    b.export(format='glb', output='exports/product.glb')
    b.get('exports/product.glb', './product.glb')
```

The context manager closes the process and retains files; it does not automatically save. SDK errors raise `BoxError` with structured details in `exception.error`. See the bundled [Python reference](skills/blenderbox/references/python.md) for methods and return values.

### Help, validation, and current scope

```bash
blenderbox --help
blenderbox exec --help
blenderbox help preview
blenderbox help skills install
blenderbox help --all
```

Help and skill commands work offline without launching Blender or starting the supervisor. Every command has examples and operational notes.

To validate a checkout with real Blender:

```bash
python3 -m unittest discover -s tests -v
```

The suite exercises persistent state, independent/concurrent processes, serialized commands, preview cleanup, checkpoint/fork assets, rendering/import/export, Python errors, close during execution, crashes/timeouts, safe file paths, supervisor restart/adoption, and offline help/skill installation. Tests use an isolated temporary state root and do not call Blender MCP.

The implemented scope is local headless sessions. GPU scheduling, resource quotas, TTL cleanup, remote HTTP, add-on profiles, and asset-service integrations remain future work. There is no literal GUI viewport or guarantee of GUI coexistence. The longer-term design is in [docs/blenderbox-final-design.md](docs/blenderbox-final-design.md).

## For agents: run from source or rebuild without installing

You can use this checkout directly, or implement the same primitive yourself. Neither route requires installing Blenderbox as a package or adding an MCP server. Blender itself is still required.

### Option A: run this checkout directly

From the repository root, use Python 3.10+ and a separate development state root:

```bash
export BLENDERBOX_HOME="$HOME/.local/share/blenderbox-dev"
python3 -m blenderbox --help
python3 -m blenderbox doctor
SESSION=$(python3 -m blenderbox create)
python3 -m blenderbox eval "$SESSION" 'list(bpy.data.objects.keys())'
python3 -m blenderbox preview "$SESSION"
python3 -m blenderbox close "$SESSION"
```

This loads the source directly. The supervisor and Blender bootstrap continue using that checkout, so keep it available while those processes run. Help and skills are also usable from source: `python3 -m blenderbox skills show`.

If agents need a stable command from any directory, create a launcher named `blenderbox-dev` on their PATH. Replace both absolute paths in this launcher with paths on the current computer:

```sh
#!/bin/sh
BLENDERBOX_REPO="/absolute/path/to/blenderbox"
BLENDERBOX_PYTHON="/absolute/path/to/python3"
export PYTHONPATH="$BLENDERBOX_REPO${PYTHONPATH:+:$PYTHONPATH}"
export BLENDERBOX_HOME="${BLENDERBOX_HOME:-$HOME/.local/share/blenderbox-dev}"
exec "$BLENDERBOX_PYTHON" -m blenderbox "$@"
```

Make the launcher executable with `chmod +x /absolute/path/to/blenderbox-dev`. It uses the source and an independent default state root. It does not install a package or replace an existing shared `blenderbox` command. After source changes, restart the development supervisor between commands and create fresh sessions to load updated bootstrap code.

### Option B: rebuild the tool locally from the specification

If you do not want to use this package at all, the following is the implementation brief for an agent. Build a local executable and a Blender-side Python bootstrap, with the responsibilities below. Python's standard library is enough for the current local feature set; another language can supervise processes, but the Blender bootstrap still runs Python.

#### 1. Preserve the session contract

Give every session its own headless Blender process, workspace, configuration paths, persistent Python namespace, and local endpoint. Separate Scenes inside one Blender process do not provide this isolation. Keep infrastructure commands small and expose arbitrary `bpy` for actual Blender work.

Start with `create`, `exec`, `eval`, `inspect`, `preview`, `save`, `status`, `sessions`, and `close`. Then add `render`, `checkpoint`, `fork`, `put`, `get`, `files`, `import`, and `export`. Include command help and a standard installable skill so future agents can discover the replacement.

Use a distinct command name/state root while developing. Do not overwrite an existing shared command or attach to another task's Blender process.

#### 2. Separate the supervisor from Blender execution

The supervisor owns process startup/shutdown, session records, command admission, deadlines, files, snapshots, and recovery. The Blender bootstrap owns `bpy`, scene inspection, rendering, and saves. A CLI and optional SDK call the same supervisor API.

The current source provides a useful map if it is available:

| Source | Responsibility |
| --- | --- |
| [client.py](blenderbox/client.py) | Locate/autostart the supervisor; make requests |
| [daemon.py](blenderbox/daemon.py) | Sessions, process groups, queues, files, snapshots, adoption |
| [protocol.py](blenderbox/protocol.py) | Framed JSON transport and structured errors |
| [bootstrap.py](blenderbox/bootstrap.py) | Main-thread Blender execution and visual feedback |
| [cli.py](blenderbox/cli.py), [helptext.py](blenderbox/helptext.py) | Arguments, examples, output conventions |
| [__init__.py](blenderbox/__init__.py) | Python SDK |
| [skills.py](blenderbox/skills.py), [skills/blenderbox](skills/blenderbox/SKILL.md) | Offline skill discovery/installation and agent guidance |

#### 3. Launch Blender as a supervised process

Invoke the executable directly with an argument array, using background/factory settings, disabled blend-file auto-execution, a render-thread limit, and your bootstrap:

```text
BLENDER --background --factory-startup --disable-autoexec --threads 2
        [SOURCE.blend]
        --python-exit-code 1 --python /absolute/path/to/bootstrap.py
        -- --box-session SESSION_ID
```

Load the source file before the bootstrap argument. Start a separate process group, set the working directory to the session workspace, detach stdin, and redirect native stdout/stderr to a log. Persist the PID and process identity, then wait for an RPC ping before returning the session ID. Save an initial `scene.blend`. Detect failed/slow startup and clean up that session's process.

Create a workspace containing `scene.blend`, `assets/`, `exports/`, `renders/`, `scripts/`, `checkpoints/`, `logs/`, `tmp/`, `home/`, `config/`, and `session.json`. In the child environment, point `HOME`, `TMPDIR`, `BLENDER_USER_CONFIG`, `BLENDER_USER_SCRIPTS`, and `BLENDER_USER_DATAFILES` into that workspace. Remove inherited Python runtime overrides, Blender user-path overrides, and obsolete MCP settings before applying your own environment. Pass workspace and endpoint paths explicitly to the bootstrap.

#### 4. Keep bpy on Blender's main thread

Run a blocking accept/read/execute/respond loop in the bootstrap invoked by `--python`. Execute every Blender operation on that same main thread. The supervisor can serve multiple clients with threads, but those threads must not call `bpy`.

Maintain a namespace initialized with `bpy`, `workspace`, and `__name__`. Use `exec` for scripts and `eval` for expressions. Clear the optional `result` variable before each script while retaining other globals. Capture Python stdout/stderr separately; leave native Blender output in the process log. Convert supported results to JSON, reject unsupported datablocks/non-finite numbers, and return tracebacks without taking down the session. Handle user `SystemExit`/`KeyboardInterrupt` as execution errors.

#### 5. Use explicit local RPC and output semantics

For compatibility with this implementation, use Unix sockets and one request/response per connection. Each frame is a four-byte unsigned big-endian length followed by UTF-8 JSON, with a 64 MiB limit. Read until the complete frame arrives; socket reads may be partial. Transfer renders/assets through files and return absolute artifact paths rather than embedding their contents in RPC responses.

Create a private runtime directory with short endpoint paths; Unix socket path lengths are limited. The current implementation derives a runtime directory from user ID and a hash of the state-root path. Use owner-only permissions, verify ownership, and use file locks to prevent duplicate supervisor startup.

A request names an operation, request ID, session ID where applicable, arguments, and timeout. Normal session replies use this shape:

```json
{
  "request_id": "req_example",
  "status": "ok",
  "result": {"path": "/absolute/workspace/renders/preview.png", "size": 12345},
  "stdout": "",
  "stderr": "",
  "duration_ms": 42
}
```

Errors replace `result` with fields such as `type`, `message`, `traceback`, and `session_alive`. CLI success exits 0; errors print JSON to stderr and exit 1. `create`, `checkpoint`, and `fork` print only IDs by default; `--json` requests the envelope. Preserve `{value, stdout, stderr}` for script results. Document the conventions in `--help`.

#### 6. Serialize writes and make close interruptible

Use FIFO command admission within a session, with independent queues/processes for separate sessions. Begin an execution deadline after admission, excluding queue wait. When it expires, terminate that session's process group and preserve its saved files/logs. A hung Python loop must not hang the supervisor.

Allow `status` to report a busy session and `close` to interrupt it without waiting behind the hung command. Coordinate close with in-flight RPC completion so a late reply cannot mark a closed session ready again. Make close repeatable, use a bounded graceful shutdown followed by forced termination when needed, and reap owned child processes. Handle the race where Blender exits just before a signal is sent.

Persist records with unique temporary files followed by atomic replacement. On supervisor restart, load records and adopt only surviving processes whose identity matches the recorded session. A stored PID alone is insufficient because PIDs can be reused.

#### 7. Provide visual feedback and durable branches

Implement compact inspection rather than dumping all of Blender. Include object transforms, dimensions, materials, modifiers, and mesh statistics, with scoped scene/object/material/render queries.

For preview, compute evaluated geometry bounds, create a temporary scene/camera/world/light rig, and render a seeded CPU Cycles PNG. Support perspective/axis views and object/collection scope. Use `try/finally` to remove temporary datablocks and restore affected source state even on failure. Actual `render` should use the scene's settings and restore temporary camera/output overrides.

Checkpoint by saving `scene.blend`, then copying workspace assets/files and recording Blender/implementation metadata. Exclude runtime/config/log/checkpoint directories and session records. Fork by copying that snapshot into a fresh workspace and launching another process. Relative asset references should resolve inside the fork. Do not claim to capture interpreter globals or external files that were not copied or packed.

#### 8. Add files, formats, help, and skills

Resolve every session output/file-transfer path and reject absolute paths or symlink/path traversal that escapes the workspace. Resolve host source/destination paths in the client before sending them to the supervisor. Copy imported models into the workspace, with glTF buffers/images or an explicitly selected resource directory for sidecars. Use Blender's import/export operators for standard formats; keep advanced settings available through arbitrary Python.

Make `--help` useful enough for an agent to operate from it: include a quick start, per-command examples/defaults, result schemas, path rules, persistence limits, timeouts, recovery, and environment settings. Help must not start the service. Bundle a standard `SKILL.md` and any supporting references with the executable/package. Provide offline skill listing/reading/installation, custom destinations, dry-run output, and explicit overwrite behavior.

#### 9. Prove the replacement works

Validate with real Blender, not just mocked sockets. If this checkout is available, its [integration tests](tests/test_integration.py) and [offline CLI tests](tests/test_cli.py) describe the expected behavior. A fresh implementation may adapt those tests to its entrypoints.

- Two sessions have different PIDs/workspaces; changing one does not change the other.
- Both execute concurrently, while concurrent commands in one session cannot lose updates.
- Python globals survive separate CLI calls; exceptions return structured errors and allow another command.
- Preview produces a readable PNG and leaves source scene/camera/settings/datablocks intact.
- A checkpoint fork preserves geometry and local assets while edits remain independent.
- Scene rendering and model export/import produce usable files.
- Infinite loops time out; crashes affect one session; close interrupts a busy process.
- A restarted supervisor adopts a live session without losing its Blender or Python state.
- Escaping file paths are rejected; saved files remain retrievable after close.
- All help/skill commands work without Blender, a running supervisor, or the source checkout once packaged.

Use a temporary state root and close only test-owned sessions. Finish by giving agents the new executable path and its skill, with a working example that creates, edits, previews, saves/exports, and closes a session. Keep any existing shared installation until the replacement has passed these checks.
