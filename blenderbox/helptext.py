"""Agent-facing CLI documentation, shared by normal and recursive help."""
OVERVIEW = """Blenderbox gives each task its own persistent, headless Blender process.
The local daemon starts automatically. Write ordinary Python using bpy;
commands run in order within a session, while separate sessions run concurrently.
No Blender MCP server, add-on, GUI window, or TCP port is required."""

QUICKSTART = """Quick start:
  SESSION=$(blenderbox create)
  blenderbox exec "$SESSION" <<'PY'
  import bpy
  bpy.data.objects['Cube'].name = 'AgentCube'
  result = {'objects': list(bpy.data.objects.keys())}
  PY
  blenderbox inspect "$SESSION" object AgentCube
  blenderbox preview "$SESSION" --object AgentCube
  blenderbox save "$SESSION"
  blenderbox export "$SESSION" --format glb
  blenderbox close "$SESSION"

Find more guidance:
  blenderbox help exec          Detailed help for a command
  blenderbox help --all         Complete CLI reference, including subcommands
  blenderbox skills list        Discover bundled agent skills
  blenderbox skills show        Read the Blenderbox skill without installing it
  blenderbox skills install --agent all
                               Install for Codex, Claude Code, OpenCode, and shared agents

Output and errors:
  create, checkpoint, fork: one plain ID; use --json for the full response.
  Other session commands: JSON on stdout. Artifacts include an absolute path.
  help / skills show: plain documentation (skills show --json returns JSON).
  exec: {value, stdout, stderr}; set result in your script to return JSON.
  Errors: JSON on stderr, exit 1. Success: exit 0. Client interruption: exit 130.
  Python errors keep a session alive. Execution timeouts terminate its process.
  Ctrl-C interrupts the client; a submitted Blender command may keep running.

Configuration:
  BLENDERBOX_HOME       State directory (default: ~/.local/share/blenderbox).
  --home DIRECTORY     Overrides the state directory; put it before the command.
  BLENDERBOX_BLENDER    Blender executable path, read when the daemon starts.
  create --blender PATH Overrides executable selection for that new session.
  --timeout SECONDS    Blender execution/startup deadline (default: 60, max: 86400).
                       Queued commands start their execution deadline on admission.

Session rules:
  Give unrelated tasks separate sessions. Save/export before close; close does
  not save unsaved changes. Saved files remain after close. Checkpoints capture
  .blend state and workspace files, not Python globals or external host files.
  Session HOME/config/tmp/scripts are isolated; agent code still has ordinary
  trusted local filesystem/network access. A process boundary is not a sandbox.
  Native Blender logs: SESSION_WORKSPACE/logs/blender.log.
  Supervisor log: BLENDERBOX_HOME/daemon.log.
"""

# Each pair is a command's explanation and its operational notes/examples.
COMMANDS = {
    "create": (
        "Launch an independent Blender process with factory settings and isolated user paths.\n"
        "The default scene contains Blender's cube, camera and light. The initial scene\n"
        "is saved to scene.blend. The daemon keeps the process alive between CLI calls.",
        """Examples:
  SESSION=$(blenderbox create)
  blenderbox create --from ./base.blend --timeout 120
  blenderbox create --blender /Applications/Blender.app/Contents/MacOS/Blender --threads 4
  blenderbox create --json

Output: session ID (bbx_...) or a full session record with --json.
--from is a host path. Relative assets in the source blend must remain available
until copied into the workspace or packed with bpy. User add-ons are not loaded.
--blender takes an executable path, not a version number. GPU/profile/version
management is not implemented. --threads limits Blender render threads only."""),
    "sessions": (
        "List persisted session records, including closed, crashed and timed-out sessions.",
        """Examples:
  blenderbox sessions
  blenderbox sessions --json

Output: array of records with id, status, pid, workspace, Blender version,
creation time, last command and dirty state. status is ready/busy/creating or
a terminal state. Listing does not create a Blender process. It may start the
supervisor. Only manipulate or close sessions owned by your current task."""),
    "status": (
        "Read a session's lifecycle record without waiting for a busy Blender command.",
        """Examples:
  blenderbox status bbx_0123456789abcdef

Output: session record. workspace is an absolute directory containing scene.blend,
assets/, exports/, renders/, scripts/, checkpoints/, logs/, tmp/, home/, config/.
dirty is conservative: arbitrary exec/eval/import may have changed scene state.
Inspect the log in workspace/logs/blender.log for native Blender errors.
Use inspect for Blender scene data; status does not invoke bpy."""),
    "exec": (
        "Execute a Python file or stdin in the existing session's main-thread namespace.\n"
        "bpy and workspace (absolute workspace path) are already available. Python globals\n"
        "persist across exec/eval calls. Higher-level modeling remains ordinary bpy.",
        """Examples:
  blenderbox exec "$SESSION" ./build.py --timeout 120
  blenderbox exec "$SESSION" < ./build.py
  blenderbox exec "$SESSION" - <<'PY'
  import bpy
  bpy.data.objects['Cube'].scale.z = 2
  print('updated cube')
  result = {'dimensions': list(bpy.data.objects['Cube'].dimensions)}
  PY

Output: {"value": ..., "stdout": "...", "stderr": "..."}.
Set result to return a JSON value. result is cleared before each execution;
other globals persist. Return primitives/lists/dicts rather than bpy datablocks.
Python stdout/stderr is captured; native Blender output is in blender.log.
Scripts execute with the workspace as cwd, not the script's host directory.
Prefer data APIs when practical; interactive GUI context is unavailable.
Errors return a traceback and session_alive. Execution is not transactional:
changes before an exception remain. Checkpoint first if rollback is needed.
A timeout kills this session's process; recover using a checkpoint or saved blend.
Ctrl-C does not cancel server execution; use close to terminate a busy session."""),
    "eval": (
        "Evaluate one Python expression in the persistent namespace and return JSON.",
        """Examples:
  blenderbox eval "$SESSION" 'list(bpy.data.objects.keys())'
  blenderbox eval "$SESSION" "bpy.data.objects['Cube'].location"
  blenderbox eval "$SESSION" "{'version': bpy.app.version_string, 'file': bpy.data.filepath}"

Output: the expression's JSON value, or the full envelope with --json.
Mathutils vectors/matrices become arrays. Raw bpy datablocks and non-finite
floats cannot be serialized; explicitly extract names or numeric properties.
Use exec for statements and captured output. eval can have side effects and
marks the session dirty conservatively. Execution timeouts terminate Blender."""),
    "inspect": (
        "Return compact scene/object/material/collection/render information as JSON.",
        """Examples:
  blenderbox inspect "$SESSION"
  blenderbox inspect "$SESSION" objects
  blenderbox inspect "$SESSION" object 'Dining Chair'
  blenderbox inspect "$SESSION" materials
  blenderbox inspect "$SESSION" render

Scopes: scene (default), objects, object NAME, materials, cameras, lights,
collections, render. Object summaries include transforms, dimensions, assigned
materials, modifiers, visibility, and mesh vertex/edge/polygon counts.
Scene objects/cameras/lights are scoped to the active scene; materials and
collections come from bpy.data. Use eval for details outside these summaries."""),
    "preview": (
        "Render a neutral visual inspection PNG using a temporary scene, camera, world\n"
        "and lights. Frame evaluated geometry and remove the temporary datablocks afterward.\n"
        "This does not require a scene camera or an interactive Blender viewport.",
        """Examples:
  blenderbox preview "$SESSION"
  blenderbox preview "$SESSION" --object 'Dining Chair' --view front
  blenderbox preview "$SESSION" --collection Furniture --view top
  blenderbox preview "$SESSION" --resolution 1024 --samples 32 --output renders/check.png

Output: {path, size, view, resolution, objects}; path is an absolute PNG path.
Read it with your image-viewing tool. Default: perspective, 512x512, 16 samples,
seeded CPU Cycles, neutral lighting. --object and --collection are exclusive.
Views: perspective, front (-Y), back (+Y), left (-X), right (+X), top (+Z),
bottom (-Z). Axis views use an orthographic camera; perspective uses a 3/4 view.
Hidden render geometry is excluded. Evaluated bounding boxes guide framing;
complex instances/geometry nodes may need a custom camera and render instead.
The source camera/render settings are retained. --output is workspace-relative.
The default output uses a fresh name in renders/. A timeout terminates Blender."""),
    "render": (
        "Render a PNG with the active scene's configured engine, camera, frame, lights,\n"
        "materials and resolution. Unlike preview, this uses your actual scene settings.",
        """Examples:
  blenderbox render "$SESSION"
  blenderbox render "$SESSION" --camera ProductCamera --output renders/final.png --timeout 600

Output: {path, size}; path is an absolute PNG path. Set render settings through
exec before rendering. The default output is renders/final.png. An explicit
camera must belong to the active scene. Camera, output path and format are
restored after rendering. Animation or non-PNG output is available through bpy.
Output paths stay inside the workspace. A timeout terminates this session."""),
    "save": (
        "Save current Blender state to a .blend file inside the session workspace.",
        """Examples:
  blenderbox save "$SESSION"
  blenderbox save "$SESSION" --as iterations/v2.blend

Output: {path, size}. Default: scene.blend. --as is workspace-relative, and
parent directories are created. Saving updates bpy.data.filepath and remaps
relative asset paths. This saves .blend state, not Python interpreter globals.
Use checkpoint to capture a copy of workspace assets too. No automatic save
occurs after exec or close. Files remain available after the process closes."""),
    "checkpoint": (
        "Save scene.blend and snapshot the workspace for independent forks or recovery.",
        """Examples:
  CHECKPOINT=$(blenderbox checkpoint "$SESSION")
  blenderbox checkpoint "$SESSION" --json
  VARIANT=$(blenderbox fork "$CHECKPOINT")

Output: checkpoint ID (chk_...) or metadata with --json. Checkpoints are stored
under BLENDERBOX_HOME/checkpoints/. Runtime/config/log/checkpoint directories
are excluded. Assets, scripts, renders and exports in the workspace are copied.
Put external dependencies in the workspace or pack them before checkpointing.
Python globals, add-on environments and external host files are not captured.
Forking copies the snapshot; later edits do not change the stored checkpoint."""),
    "fork": (
        "Launch an independent Blender process/workspace from a checkpoint or live session.\n"
        "A session source is checkpointed first; the original session keeps running.",
        """Examples:
  VARIANT=$(blenderbox fork "$CHECKPOINT")
  VARIANT=$(blenderbox fork "$SESSION")
  blenderbox fork chk_0123456789abcdef --json --timeout 120

Output: new session ID (bbx_...) or full session record with --json.
The new process inherits saved .blend state, workspace files, executable path
and render-thread count. Python globals start fresh. Use separate forks for
parallel agents, compare their outputs, and close variants owned by your task.
You may fork a stored checkpoint after its source session crashes or closes."""),
    "put": (
        "Copy a host file into a session workspace, creating parent directories.",
        """Examples:
  blenderbox put "$SESSION" ./wood.png assets/wood.png
  blenderbox put "$SESSION" ./build.py scripts/build.py

Output: {path, size}. source is a host file; destination is workspace-relative.
An existing destination file is replaced. Absolute or escaping session paths
are rejected. Use exec to load the asset with bpy; put does not import geometry.
For multi-file models, import --resources DIRECTORY copies an explicit asset tree."""),
    "get": (
        "Locate a session file or copy it to a host destination, including after close.",
        """Examples:
  blenderbox get "$SESSION" exports/scene.glb
  blenderbox get "$SESSION" exports/scene.glb ./deliverables/chair.glb
  blenderbox get "$SESSION" scene.blend ./chair.blend

Output: {path, size}. Without destination, path locates the existing workspace
file; it does not print the file's contents. With destination, the file is copied
to that host path; parent directories are created and existing files replaced.
Session path is workspace-relative; destination is a host path."""),
    "files": (
        "List workspace artifact files without querying Blender state.",
        """Examples:
  blenderbox files "$SESSION"

Output: array of {path, size}; paths are relative to the workspace.
Internal runtime/config/log/checkpoint directories are omitted. Scene files,
assets, scripts, renders and exports are included. Works after session close.
Use status for the absolute workspace path and get to copy a particular file."""),
    "import": (
        "Copy a model into assets/ and import it into the current Blender scene.",
        """Examples:
  blenderbox import "$SESSION" ./chair.glb
  blenderbox import "$SESSION" ./chair.gltf
  blenderbox import "$SESSION" ./bundle/chair.obj --resources ./bundle
  blenderbox import "$SESSION" ./rig.fbx --timeout 120

Output: {path, objects}; objects lists newly created object names.
Built-in formats: GLB, glTF, OBJ, STL, PLY, FBX. The source is a host path.
Local glTF buffer/image sidecars are copied automatically. For OBJ/FBX materials
or textures use --resources: the directory must contain the model, and its
contents are copied into the workspace. Avoid unnecessarily broad directories.
The import adds to existing scene data. Other formats/operator settings remain
available through exec and bpy. Checkpoint first if you need a rollback point."""),
    "export": (
        "Export geometry or a .blend to a workspace artifact using Blender's exporters.",
        """Examples:
  blenderbox export "$SESSION"
  blenderbox export "$SESSION" --format glb --output exports/chair.glb
  blenderbox export "$SESSION" --format obj --selected
  blenderbox export "$SESSION" --format blend --output exports/source.blend

Output: {path, size}. Default format: glb; default path: exports/scene.FORMAT.
Formats: glb, gltf, obj, stl, ply, fbx, blend. --selected exports the current
selection for geometry exporters. .blend exports a copy of the full file.
glTF/OBJ may emit sidecars; use files/get for accompanying buffers/materials.
Selection and advanced exporter options can be set through exec.
--output must stay within the workspace. Existing output files may be replaced."""),
    "close": (
        "Terminate this session's Blender process, including a currently busy command.\n"
        "Retain its saved files and logs. Closing a terminal session is safe to repeat.",
        """Examples:
  blenderbox save "$SESSION"
  blenderbox close "$SESSION"
  blenderbox get "$SESSION" scene.blend ./finished.blend

Output: final session record with status closed. Unsaved state and Python globals
are lost; close does not save automatically. Checkpoint/save/export first when
you need those results. Other sessions are unaffected. Only close sessions
owned by this task. Use fork CHECKPOINT or create --from SAVED.blend to resume."""),
    "doctor": (
        "Start/check the local supervisor and report Blender executable discovery.",
        """Examples:
  blenderbox doctor
  blenderbox --home /tmp/blenderbox-test doctor

Output includes Blenderbox version, daemon PID, Blender path/version, state
directory and transport. It runs Blender --version, not a persistent session.
Discovery uses BLENDERBOX_BLENDER, then blender on PATH, then the default macOS
app executable. If missing, set BLENDERBOX_BLENDER or use create --blender PATH.
For startup failures inspect BLENDERBOX_HOME/daemon.log and session blender.log."""),
    "daemon": (
        "Start, inspect or stop the automatically managed local supervisor.",
        """Examples:
  blenderbox daemon start
  blenderbox daemon status
  blenderbox daemon stop
  blenderbox daemon stop --close-sessions

start/status contact the service and start it if absent. stop preserves Blender
processes by default; the next invocation starts a supervisor that adopts them.
--close-sessions explicitly terminates every active session in this state root,
including other tasks' sessions; use it only when all those sessions may close.
To load a newly installed supervisor, stop it and run doctor. Surviving Blender
processes keep their old bootstrap; create new sessions to load updated code.
State roots are independent; --home DIRECTORY selects which service to manage."""),
    "help": (
        "Read command help without starting the daemon or launching Blender.",
        """Examples:
  blenderbox help
  blenderbox help exec
  blenderbox help skills install
  blenderbox help --all

--all prints the complete CLI reference, including nested skill commands.
Every command also accepts --help. Help is available without Blender installed."""),
    "skills": (
        "Discover, read and install skills bundled with this Blenderbox package.\n"
        "Skill commands work locally without a daemon, Blender, or repository checkout.",
        """Examples:
  blenderbox skills list
  blenderbox skills show blenderbox
  blenderbox skills install --agent codex
  blenderbox skills install --agent all
  blenderbox skills install --path ./my-agent/skills --dry-run

list returns bundled skill metadata. show prints SKILL.md (or JSON with --json).
install copies a complete skill directory, including supporting references.
Use skills SUBCOMMAND --help for destinations, overwrite behavior and examples.
Reload your agent's skill discovery after installation. No MCP settings change."""),
    "skills list": (
        "List the skills distributed in the installed Blenderbox package.",
        """Examples:
  blenderbox skills list
  blenderbox skills list --json

Output: array of {name, description, files}. One Blenderbox workflow skill
covers session creation, modeling, visual feedback and delivery; its supporting
references provide detailed CLI workflows and Python SDK guidance."""),
    "skills show": (
        "Read a bundled skill's entrypoint or supporting reference without installing it.",
        """Examples:
  blenderbox skills show
  blenderbox skills show blenderbox
  blenderbox skills show --file references/workflow.md
  blenderbox skills show --file references/cli.md
  blenderbox skills show --file references/python.md --json

Default skill: blenderbox. Default file: SKILL.md, a tiny entrypoint linking to
references/workflow.md for the full workflow. Plain output is Markdown.
--json returns {name, file, content} in a response envelope. --file must identify
a bundled file; arbitrary filesystem paths are not read."""),
    "skills install": (
        "Install a complete bundled skill into one or more agent skill directories.",
        """Examples:
  blenderbox skills install
  blenderbox skills install blenderbox --agent codex
  blenderbox skills install --agent claude --agent opencode
  blenderbox skills install --agent all --dry-run
  blenderbox skills install --agent all --force
  blenderbox skills install --path ./agent-skills

Default skill: blenderbox. Default agent: codex. Repeat --agent for multiple
clients, or use all. Destinations (skill name is appended):
  codex:   $CODEX_HOME/skills, or ~/.codex/skills
  claude:  ~/.claude/skills
  opencode: $XDG_CONFIG_HOME/opencode/skills, or ~/.config/opencode/skills
  shared:  ~/.agents/skills
--path specifies a custom parent skill directory and cannot mix with --agent.
--dry-run reports planned destinations without writing. Identical installs are
unchanged. A different existing skill is rejected unless --force is supplied;
--force replaces the entire named skill directory, including local edits.
Output: {name, dry_run, installations: [{path, status}]}. Reload agent skills
after install. This command does not edit global agent instructions or MCP config."""),
}
