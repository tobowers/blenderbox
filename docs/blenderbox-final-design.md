# Blenderbox

## Isolated, stateful Blender sessions for coding agents

**Status:** Proposed final design  
**Implementation:** The local CLI, daemon and Python SDK are implemented and installed on this computer. See [README.md](../README.md) for usage, supported commands and the remaining roadmap.  
**Primary goal:** Give agents a browser-session-like abstraction for Blender: isolated, stateful, headless Blender processes that can be created, manipulated, inspected, rendered, checkpointed, forked, and destroyed programmatically.

---

## 1. Executive summary

Blenderbox is a session manager for Blender aimed at coding agents such as Codex, Claude Code, OpenCode, and similar systems.

The central abstraction is not an MCP server and not a Blender GUI window. It is a **Blender session**:

> **One Blenderbox session = one isolated Blender process + one workspace + one Blender state + one RPC endpoint.**

This is intentionally analogous to how modern agents use headless browser sessions.

Instead of attaching an agent to whatever Blender GUI is currently open, Blenderbox starts and supervises dedicated Blender processes. Multiple agents can therefore operate independently without sharing Blender context, scene state, undo state, add-on state, or crash boundaries.

The normal mode is fully headless. There is no requirement for a Blender window, macOS app lifecycle integration, VNC, Xvfb, or other desktop infrastructure.

Blenderbox exposes a deliberately small infrastructure API:

- create a session
- execute arbitrary `bpy`
- inspect Blender state
- render deterministic visual previews
- import/export files
- save
- checkpoint
- fork
- close

Higher-level Blender operations remain ordinary Python written by the agent.

MCP is treated as an optional adapter on top of Blenderbox rather than as the core architecture.

The design target is:

> **Every task achievable through Blender MCP should be achievable through Blenderbox.**

This is task-level compatibility, not necessarily one CLI command for every MCP tool.

---

# 2. Why Blenderbox exists

Existing Blender MCP implementations generally follow this model:

```text
Agent
  ↓ MCP
MCP server
  ↓ socket
Blender add-on / Blender process
  ↓
bpy
```

This is useful, but it makes MCP the primary abstraction.

For coding agents, that is not necessarily ideal.

Modern coding agents are already very good at:

- writing Python
- using CLIs
- manipulating files
- inspecting JSON
- composing shell commands
- running loops
- creating helper scripts
- reasoning over rendered images

The valuable primitive is therefore not a large catalog of MCP tools such as:

```text
create_cube
set_material
rotate_object
set_camera
add_light
extrude
boolean
...
```

The valuable primitive is:

```text
"Give me an isolated Blender and let me execute code inside it."
```

Blenderbox provides that primitive.

---

# 3. Product definition

## 3.1 One-line description

> **Blenderbox provides isolated, stateful, headless Blender sessions for agents.**

## 3.2 Mental model

The best analogy is Playwright or browser-session infrastructure.

| Browser infrastructure | Blenderbox |
|---|---|
| Browser session | Blender process |
| Browser profile | Blender workspace/config |
| Page state | `.blend` state |
| JavaScript evaluation | `bpy` execution |
| DOM inspection | Scene/object inspection |
| Screenshot | Preview/render |
| Download | Exported asset |
| Upload | Imported asset |
| Browser checkpoint | Saved `.blend` checkpoint |
| New browser context | New Blenderbox session |
| Fork state | Duplicate checkpoint into new Blender process |

The key property is **session isolation**.

---

# 4. Core architectural decision

## One session = one Blender process

Do not multiplex unrelated agents into Scenes inside a single Blender process.

Blender can contain multiple Scenes, but Scenes are not isolation boundaries. They still share:

- `bpy.data`
- materials
- meshes
- images
- objects
- add-on state
- process-global state
- some render state
- undo behavior
- Python interpreter state
- crash fate

An agent with arbitrary `bpy` access could accidentally affect data belonging to another Scene.

Therefore:

```text
Blenderbox daemon
        │
        ├── Session A
        │     └── Blender process A
        │
        ├── Session B
        │     └── Blender process B
        │
        └── Session C
              └── Blender process C
```

This gives each agent a proper isolation boundary.

---

# 5. Session anatomy

A session consists of:

```text
session-id/
├── scene.blend
├── assets/
├── exports/
├── renders/
├── scripts/
├── checkpoints/
├── logs/
├── tmp/
├── home/
├── config/
└── session.json
```

A session record should include at least:

```json
{
  "id": "bbx_7f31",
  "status": "running",
  "pid": 10492,
  "created_at": "...",
  "blender_version": "4.x",
  "workspace": "...",
  "rpc_endpoint": "...",
  "gpu": null,
  "source_checkpoint": null
}
```

The process itself should have isolated environment/config paths.

For example:

```bash
HOME=/tmp/blenderbox/bbx_7f31/home
TMPDIR=/tmp/blenderbox/bbx_7f31/tmp
BLENDER_USER_CONFIG=/tmp/blenderbox/bbx_7f31/config
BLENDER_USER_SCRIPTS=/tmp/blenderbox/bbx_7f31/scripts
```

This reduces accidental sharing of:

- preferences
- startup files
- scripts
- add-on configuration
- temporary files
- caches

Shared read-only asset caches can still be mounted separately.

---

# 6. Blender startup

On macOS, Blenderbox should not launch Blender through Launch Services or treat `.app` bundles as session identity.

Instead, launch the executable directly:

```bash
/Applications/Blender.app/Contents/MacOS/Blender \
  --background \
  /tmp/blenderbox/bbx_7f31/scene.blend \
  --python /path/to/blenderbox_bootstrap.py
```

On Linux:

```bash
blender \
  --background \
  /var/lib/blenderbox/bbx_7f31/scene.blend \
  --python /opt/blenderbox/blenderbox_bootstrap.py
```

The bootstrap script starts a local RPC endpoint and waits for commands.

This avoids macOS bundle-ID problems because Blenderbox manages ordinary Unix processes rather than multiple application identities.

---

# 7. Why no GUI is required

The design assumes the user never needs a Blender GUI.

That removes an entire class of complexity:

- macOS bundle identifiers
- Launch Services
- application activation
- window focus
- multiple `.app` copies
- Xvfb
- Wayland/X11 desktops
- VNC
- WebRTC desktops
- GUI automation
- interactive workspace context

The normal loop becomes:

```text
Agent writes bpy
      ↓
Blender executes it
      ↓
Blenderbox renders image
      ↓
Vision model examines image
      ↓
Agent writes more bpy
```

For agentic workflows, this can be better than looking at the Blender UI.

---

# 8. Core API

The API should remain intentionally small.

## 8.1 Lifecycle

```text
create
status
close
```

## 8.2 Code execution

```text
exec
eval
```

## 8.3 Inspection

```text
inspect
```

## 8.4 Visual feedback

```text
preview
render
```

## 8.5 Persistence

```text
save
checkpoint
fork
```

## 8.6 Files

```text
put
get
list
```

## 8.7 Import/export

```text
import
export
```

Everything else can initially be implemented through `bpy`.

---

# 9. CLI design

A minimal CLI could look like this.

## Create a session

```bash
$ blenderbox create
bbx_7f31
```

Optional:

```bash
blenderbox create --from chair.blend
blenderbox create --blender 4.5
blenderbox create --gpu
```

## Run Python

```bash
blenderbox exec bbx_7f31 script.py
```

Or stdin:

```bash
blenderbox exec bbx_7f31 <<'PY'
import bpy

bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.object
obj.name = "AgentCube"
PY
```

## Evaluate an expression

```bash
blenderbox eval bbx_7f31 \
  'list(bpy.data.objects.keys())'
```

Output should be machine-readable JSON whenever practical.

## Inspect

```bash
blenderbox inspect bbx_7f31
```

Potential scoped forms:

```bash
blenderbox inspect bbx_7f31 scene
blenderbox inspect bbx_7f31 objects
blenderbox inspect bbx_7f31 object Chair
blenderbox inspect bbx_7f31 materials
blenderbox inspect bbx_7f31 cameras
```

## Preview

```bash
blenderbox preview bbx_7f31
blenderbox preview bbx_7f31 --object Chair
blenderbox preview bbx_7f31 --view top
blenderbox preview bbx_7f31 --view front
blenderbox preview bbx_7f31 --view perspective
```

## Final render

```bash
blenderbox render bbx_7f31 \
  --camera Camera \
  --output renders/final.png
```

## Files

```bash
blenderbox put bbx_7f31 ./wood.png assets/wood.png
blenderbox get bbx_7f31 exports/chair.glb
blenderbox files bbx_7f31
```

## Save

```bash
blenderbox save bbx_7f31
blenderbox save bbx_7f31 --as iteration-4.blend
```

## Checkpoint

```bash
$ blenderbox checkpoint bbx_7f31
chk_a91e
```

## Fork

```bash
$ blenderbox fork chk_a91e
bbx_832a
```

Possibly also:

```bash
blenderbox fork bbx_7f31
```

which implicitly creates a checkpoint first.

## Close

```bash
blenderbox close bbx_7f31
```

---

# 10. Python SDK

The Python interface should map very closely to the session API.

Example:

```python
from blenderbox import Blender

b = Blender.create()

b.exec("""
import bpy

bpy.ops.mesh.primitive_uv_sphere_add()
sphere = bpy.context.object
sphere.name = "Ball"
""")

scene = b.inspect()

image = b.preview(object="Ball")

checkpoint = b.checkpoint()

variant = b.fork()

b.close()
```

A context-manager form could be useful:

```python
from blenderbox import Blender

with Blender.create() as b:
    b.exec(open("build.py").read())
    b.render("renders/output.png")
```

---

# 11. HTTP / RPC layer

The CLI and SDK should talk to a stable Blenderbox service API rather than directly implementing session logic.

Conceptually:

```text
                 Blenderbox API
                      │
        ┌─────────────┼─────────────┐
        │             │             │
       CLI       Python SDK     MCP adapter
                      │
                session manager
                      │
         ┌────────────┼────────────┐
         │            │            │
      Blender      Blender      Blender
```

Potential session API:

```http
POST   /sessions
GET    /sessions/{id}
DELETE /sessions/{id}

POST   /sessions/{id}/exec
POST   /sessions/{id}/eval
GET    /sessions/{id}/inspect

POST   /sessions/{id}/preview
POST   /sessions/{id}/render

POST   /sessions/{id}/save
POST   /sessions/{id}/checkpoint
POST   /checkpoints/{id}/fork

POST   /sessions/{id}/files
GET    /sessions/{id}/files/{path}
```

The exact transport can be:

- Unix socket locally
- HTTP locally
- HTTP/gRPC remotely

The external interface should not depend on Blender's internal transport.

---

# 12. Blender-side RPC

Each Blender process starts with a bootstrap script.

Conceptually:

```text
Blender process
      │
      ├── bpy
      │
      └── Blenderbox bootstrap
              │
              └── RPC endpoint
```

The bootstrap should provide a minimal set of process-local operations:

```text
exec_python
eval_python
inspect
save
render
ping
shutdown
```

The session supervisor should own lifecycle, files, checkpoints, process monitoring, and resource limits.

The Blender process should not itself be responsible for orchestrating other sessions.

---

# 13. Code execution model

The most important Blenderbox operation is arbitrary Python execution.

Example:

```python
import bpy

mesh = bpy.data.meshes.new("TableTopMesh")
obj = bpy.data.objects.new("TableTop", mesh)

bpy.context.scene.collection.objects.link(obj)
```

Coding agents already know how to write Python and can learn Blender's API from documentation.

Therefore Blenderbox should avoid creating dozens of redundant operations unless there is a strong infrastructure reason.

For example, these do not need to be first-class initially:

```text
create_cube
rotate_object
set_scale
set_material_color
extrude_mesh
boolean_difference
add_sun
move_camera
```

They can all be `bpy`.

---

# 14. `bpy.ops` versus Blender data API

Headless Blender can perform many operators, but some `bpy.ops` calls depend on Blender context.

Agent guidance should therefore recommend:

> Prefer direct Blender data APIs where practical. Use operators when they are the natural or required API, but do not assume an interactive Blender window exists.

For example:

Prefer robust datablock manipulation where reasonable:

```python
mesh = bpy.data.meshes.new("Mesh")
obj = bpy.data.objects.new("Object", mesh)
bpy.context.scene.collection.objects.link(obj)
```

instead of relying unnecessarily on context-sensitive operators.

This is not a hard ban on `bpy.ops`.

---

# 15. Inspection design

A raw dump of Blender's entire state would be too large.

`inspect` should return intentionally compact structured representations.

Example:

```json
{
  "scene": "Scene",
  "objects": [
    {
      "name": "Chair",
      "type": "MESH",
      "location": [0, 0, 0],
      "rotation": [0, 0, 0],
      "scale": [1, 1, 1],
      "dimensions": [0.8, 0.9, 1.1],
      "materials": ["Oak"]
    }
  ],
  "cameras": ["Camera"],
  "lights": ["Key", "Fill"]
}
```

Scoped inspection keeps responses small.

Useful inspection modes may include:

```text
scene summary
object summary
mesh statistics
materials
textures
cameras
lights
collections
render settings
dependencies
bounding boxes
selected object details
```

Agents can always fall back to arbitrary `bpy` if they need more.

---

# 16. Visual feedback

## 16.1 Do not depend on Blender viewport screenshots

A literal Blender `VIEW_3D` viewport is part of Blender's UI context.

If Blenderbox runs with:

```bash
blender --background
```

there is no need to promise literal parity with a human-visible viewport.

Instead, provide deterministic agent-oriented visual probes.

## 16.2 Preview operation

```bash
blenderbox preview bbx_123
```

should:

1. determine the relevant objects
2. compute their bounds
3. create or reuse a temporary camera
4. frame the requested geometry
5. choose a predictable light/environment setup
6. render quickly
7. save PNG
8. restore any temporary state

Possible modes:

```bash
blenderbox preview bbx_123 --view perspective
blenderbox preview bbx_123 --view front
blenderbox preview bbx_123 --view back
blenderbox preview bbx_123 --view left
blenderbox preview bbx_123 --view right
blenderbox preview bbx_123 --view top
blenderbox preview bbx_123 --view bottom
```

Object-scoped:

```bash
blenderbox preview bbx_123 --object Chair
```

Collection-scoped:

```bash
blenderbox preview bbx_123 --collection Furniture
```

## 16.3 Render

`render` should mean the actual scene render according to scene configuration.

```bash
blenderbox render bbx_123 --camera Camera
```

Preview and render are intentionally different abstractions:

```text
preview = agent inspection
render  = scene output
```

---

# 17. Checkpoints and forks

This is one of Blenderbox's strongest features.

## Checkpoint

A checkpoint captures sufficient session state to restart or branch the Blender session.

At minimum this includes:

- `.blend`
- relevant session metadata
- session-local assets
- Blenderbox version
- Blender version

Command:

```bash
blenderbox checkpoint bbx_123
```

Result:

```text
chk_42
```

## Fork

```bash
blenderbox fork chk_42
```

creates an independent Blender process from the checkpoint.

Example:

```text
              checkpoint
                  │
        ┌─────────┼─────────┐
        │         │         │
     Agent A   Agent B   Agent C
        │         │         │
   version A version B version C
```

This enables agents to explore competing solutions in parallel.

Possible use:

```text
"Try three lighting setups."

checkpoint base

fork 1 → warm studio
fork 2 → overcast exterior
fork 3 → dramatic rim light

render all
compare images
keep winner
```

This is much harder to model cleanly when agents all share one Blender process.

---

# 18. Concurrency

Blender's Python environment should be treated as effectively single-writer within each session.

Commands to a session should therefore normally be serialized:

```text
Agent
  ↓
Blenderbox
  ↓
per-session command queue
  ↓
Blender process
```

Independent sessions execute concurrently.

```text
session A queue → Blender A
session B queue → Blender B
session C queue → Blender C
```

This produces simple correctness semantics:

> Commands in one session execute in submission order.

If parallel work is desired, fork the session.

---

# 19. Process failure

One Blender process per session gives clean crash isolation.

```text
Blender A crashes → Session A fails
Blender B continues
Blender C continues
```

The supervisor should:

- detect process exit
- preserve logs
- report crash status
- preserve the last saved `.blend`
- optionally support restart from the last checkpoint

Potential status:

```json
{
  "id": "bbx_123",
  "status": "crashed",
  "exit_code": 139,
  "last_checkpoint": "chk_41"
}
```

---

# 20. Timeouts and runaway scripts

Arbitrary agent-written Python creates the possibility of:

- infinite loops
- memory explosions
- pathological geometry creation
- extremely long renders

Blenderbox should therefore support resource limits.

Potential controls:

```text
exec timeout
render timeout
maximum memory
maximum session age
maximum disk usage
CPU quota
GPU assignment
```

Example:

```bash
blenderbox exec bbx_123 build.py --timeout 60
```

If a Blender process becomes irrecoverably stuck, Blenderbox should kill the session process rather than compromising the daemon.

---

# 21. Filesystem isolation

The ideal filesystem model is:

```text
session workspace = writable
shared assets     = read-only
host filesystem   = inaccessible by default
```

For stronger isolation on Linux, Blenderbox could use:

- containers
- mount namespaces
- user namespaces
- cgroups
- seccomp

But the initial local version does not necessarily need full containerization.

The process boundary plus dedicated workspace already solves the primary Blender-state isolation problem.

---

# 22. Local versus cloud

The Blenderbox abstraction should be the same everywhere.

## Local macOS

```text
Blenderbox
   ↓
/Applications/Blender.app/Contents/MacOS/Blender --background
```

## Linux workstation

```text
Blenderbox
   ↓
blender --background
```

## GPU server

```text
Blenderbox
   ↓
headless Blender process
   ↓
Cycles GPU
```

## Remote service

```text
Agent
   ↓ HTTPS
Blenderbox server
   ↓
isolated Blender sessions
```

The client should not care where the Blender process lives.

---

# 23. macOS bundle IDs

Bundle IDs were a problem when considering multiple interactive Blender applications.

Blenderbox avoids this entirely.

Instead of:

```text
Blender.app instance A
Blender.app instance B
Blender.app instance C
```

managed through macOS application semantics, Blenderbox launches:

```text
PID 101 → Blender executable
PID 102 → Blender executable
PID 103 → Blender executable
```

Each process is associated with a Blenderbox session ID rather than a bundle ID.

Therefore:

> macOS bundle identity is not part of Blenderbox's session model.

---

# 24. Multiple `.blend` files

A single Blender process should not be treated as a multi-document host.

The architecture is:

```text
one session
=
one Blender process
=
one active Blender database
```

Different files belong in different sessions.

If an agent needs three independent `.blend` states:

```text
bbx_A → A.blend
bbx_B → B.blend
bbx_C → C.blend
```

Blender library linking and append functionality remain available through `bpy`, but are data composition mechanisms, not session isolation.

---

# 25. Shared assets

Sessions may need access to the same large assets.

Do not duplicate immutable assets into every session unnecessarily.

Potential layout:

```text
/blenderbox
  /shared-assets
      HDRIs/
      textures/
      models/
      fonts/
  /sessions
      bbx_A/
      bbx_B/
      bbx_C/
```

Shared assets can be mounted read-only.

Agents can copy assets into their own workspace when mutation is necessary.

This also makes checkpoints smaller.

---

# 26. Asset integrations

Some Blender MCP implementations include integrations such as:

- Poly Haven
- Sketchfab
- model-generation APIs
- texture-generation APIs
- external 3D services

These should not need to live inside the Blender process.

A cleaner architecture is:

```text
Agent
  │
  ├── Asset provider API
  │        ↓
  │     model.glb
  │
  └── Blenderbox
           ↓
        import
```

Potential CLI:

```bash
blenderbox asset search polyhaven "industrial warehouse"
blenderbox asset download polyhaven <id>
blenderbox import bbx_123 ./warehouse.glb
```

This separates:

```text
asset acquisition
```

from:

```text
Blender execution
```

Third-party integrations can be optional plugins.

---

# 27. MCP compatibility

MCP should be an adapter, not the product.

```text
                     Blenderbox
                         │
                canonical session API
                         │
       ┌─────────────────┼──────────────────┐
       │                 │                  │
      CLI            Python SDK         MCP adapter
```

The MCP adapter can expose whichever high-level tools are useful for MCP-only clients.

For example:

```text
create_primitive
set_material
get_scene_info
render_image
execute_blender_code
...
```

Internally those calls become Blenderbox operations.

This means Blenderbox can support generic MCP clients without forcing coding agents to use MCP.

---

# 28. Blender MCP parity target

The compatibility target should be:

> **Every task achievable through the reference Blender MCP should be achievable through Blenderbox.**

This is different from saying:

> Blenderbox must contain a one-to-one CLI command for every MCP tool.

For example, an MCP server may expose:

```text
create_cube
set_material_color
set_transform
set_camera_fov
add_light
boolean_objects
extrude
```

Blenderbox can perform all of these through:

```bash
blenderbox exec
```

with generated `bpy`.

The important thing is capability parity.

---

# 29. Expected parity categories

## 29.1 Blender scene editing

Expected: **full parity**

Through arbitrary `bpy`.

Examples:

- objects
- meshes
- curves
- geometry nodes
- materials
- shaders
- lights
- cameras
- collections
- modifiers
- animation
- rigs
- constraints
- physics
- compositing
- rendering
- import/export

## 29.2 Blender inspection

Expected: **full or better parity**

Blenderbox can implement concise structured inspection while still allowing arbitrary Python.

## 29.3 Arbitrary Blender code

Expected: **full parity**

This is a core Blenderbox primitive.

## 29.4 Rendering

Expected: **full parity**

Cycles, EEVEE, and agent-oriented previews where supported.

## 29.5 Import/export

Expected: **full parity**

Anything exposed through Blender APIs can be used.

## 29.6 Third-party assets

Expected: **full task parity**

Implemented outside Blender or as optional integrations.

## 29.7 Literal interactive viewport screenshot

Expected: **semantic parity, not necessarily implementation parity**

Blenderbox should provide deterministic headless previews instead of depending on a UI viewport.

If a future feature genuinely requires a UI-only Blender context, Blenderbox could optionally support a virtual-display execution mode without changing the public API.

---

# 30. Why preview is preferable to viewport capture

For agents, an arbitrary Blender viewport has several disadvantages:

- camera angle may depend on previous UI state
- overlays may clutter the image
- viewport shading may be inconsistent
- selection state may change appearance
- framing may be poor
- window size affects results

A Blenderbox preview can be deterministic.

For example:

```text
preview object Chair
```

can always mean:

```text
camera = 3/4 perspective
frame = object bounds + padding
lighting = standard neutral setup
background = neutral
resolution = 1024×1024
```

This produces better visual input for vision-capable agents.

---

# 31. Agent workflow example

Suppose an agent is asked:

> Build a low-poly wooden chair with a curved back.

The loop could be:

```bash
SESSION=$(blenderbox create)
```

Agent writes:

```python
# build_v1.py
import bpy
...
```

Then:

```bash
blenderbox exec $SESSION build_v1.py
blenderbox preview $SESSION --object Chair
```

The image is fed back to the model.

The agent notices the back is too narrow.

```bash
blenderbox exec $SESSION fix_back.py
blenderbox preview $SESSION --object Chair
```

Once satisfied:

```bash
blenderbox save $SESSION
blenderbox export $SESSION \
  --format glb \
  --output exports/chair.glb
```

Then:

```bash
blenderbox get $SESSION exports/chair.glb
blenderbox close $SESSION
```

---

# 32. Parallel agent workflow

Suppose the system wants three agents to improve a base scene.

```bash
BASE=$(blenderbox create --from base.blend)
CHK=$(blenderbox checkpoint $BASE)

A=$(blenderbox fork $CHK)
B=$(blenderbox fork $CHK)
C=$(blenderbox fork $CHK)
```

Now:

```text
Agent A → session A
Agent B → session B
Agent C → session C
```

Each can mutate freely without coordination.

They each produce:

```text
preview.png
scene.blend
metrics.json
```

A supervising model compares them and selects a winner.

This is one of the strongest reasons to use process-based sessions.

---

# 33. Session manager responsibilities

The Blenderbox daemon should own:

- session IDs
- process startup
- process shutdown
- process monitoring
- workspaces
- environment isolation
- RPC endpoint allocation
- command queues
- timeouts
- checkpoint creation
- fork creation
- logs
- file transfer
- Blender version selection
- GPU assignment
- resource accounting

Blender itself should own:

- Blender state
- `bpy`
- rendering
- scene manipulation
- import/export
- save/load

This is a clean responsibility split.

---

# 34. Session states

Potential states:

```text
creating
ready
busy
checkpointing
stopping
closed
crashed
failed
```

Example status:

```json
{
  "id": "bbx_7f31",
  "status": "ready",
  "pid": 18421,
  "uptime_seconds": 812,
  "memory_mb": 1240,
  "last_command": "preview",
  "dirty": true
}
```

---

# 35. Command execution semantics

Each command should have:

```text
request ID
session ID
command
timeout
stdout
stderr
structured result
artifacts
duration
```

Example response:

```json
{
  "request_id": "req_82",
  "status": "ok",
  "result": {
    "objects_created": ["Chair"]
  },
  "stdout": "",
  "stderr": "",
  "duration_ms": 412
}
```

This is particularly useful for agents because failures can be inspected and repaired.

---

# 36. Errors

Errors should be structured.

Example:

```json
{
  "status": "error",
  "type": "python_exception",
  "message": "Object 'Chair' not found",
  "traceback": "...",
  "session_alive": true
}
```

Possible categories:

```text
python_exception
timeout
render_failure
process_crash
invalid_session
file_not_found
resource_limit
unsupported_blender_version
```

Do not force agents to parse human-oriented logs when a structured error can be returned.

---

# 37. Determinism

Where practical, Blenderbox should make repeatability easy.

Potential options:

```text
random seed
Blender version pinning
render engine pinning
GPU/CPU mode
dependency manifest
asset hashes
```

Checkpoints should record enough metadata to understand the environment that produced them.

Example:

```json
{
  "blender_version": "4.5.1",
  "blenderbox_version": "0.3.0",
  "render_engine": "BLENDER_EEVEE_NEXT",
  "asset_hashes": {
    "wood.png": "..."
  }
}
```

---

# 38. Blender versions

The session API should allow version selection eventually.

```bash
blenderbox create --blender 4.5
```

A server may advertise:

```bash
blenderbox versions
```

Output:

```text
4.3
4.5
5.0
```

This allows reproducible builds and compatibility with specific add-ons.

---

# 39. Add-ons

Add-ons create another layer of state.

Blenderbox should support session templates or images.

For example:

```bash
blenderbox create --profile architectural
blenderbox create --profile rigging
```

A profile might specify:

```text
Blender version
enabled add-ons
Python dependencies
startup file
shared assets
render preferences
```

Profiles should be immutable or versioned where possible.

---

# 40. Security

Arbitrary `bpy` means arbitrary Python.

Therefore Blenderbox should assume session code is effectively arbitrary code execution.

For trusted local personal agents, process isolation may be sufficient.

For untrusted/multi-tenant agents, use stronger sandboxing:

```text
container
user namespace
mount namespace
cgroup
network restrictions
resource limits
read-only host mounts
```

Never assume `bpy` itself is a sandbox.

---

# 41. Network access

Default recommendation:

```text
Blender session network = disabled
```

unless explicitly needed.

External services should preferably be accessed by the controlling agent or Blenderbox integration layer, with downloaded assets passed into the session.

This makes Blender execution more deterministic and easier to secure.

---

# 42. Shared cache

Large immutable data may be shared:

```text
Blender binaries
Python packages
HDRIs
textures
downloaded models
render kernels/cache
```

Session-writable state should remain isolated.

This allows dozens of Blender processes without unnecessarily duplicating disk usage.

---

# 43. GPU handling

A Blenderbox server may expose available devices:

```bash
blenderbox devices
```

Example:

```text
cpu
cuda:0
cuda:1
metal:0
```

Session creation could accept:

```bash
blenderbox create --device metal:0
```

GPU assignment should be handled by the supervisor, not agent-written Blender code alone.

Potential future scheduling:

```text
GPU 0:
  session A
  session B

GPU 1:
  session C
```

or exclusive GPU sessions for heavy renders.

---

# 44. Lifecycle policy

Sessions can be:

```text
ephemeral
persistent
```

Ephemeral:

```bash
blenderbox create --ttl 30m
```

Persistent:

```bash
blenderbox create --persist
```

Potential cleanup policy:

- idle timeout
- maximum lifetime
- disk quota
- automatic checkpoint before eviction

---

# 45. Minimal viable version

The first useful version does not need much.

## V0

Implement:

```text
create
exec
eval
inspect
preview
save
close
```

Architecture:

```text
local daemon
   ↓
one headless Blender process per session
   ↓
local socket RPC
```

No containers.

No MCP.

No asset integrations.

No GUI.

No remote hosting.

This is already useful.

---

# 46. V1

Add:

```text
checkpoint
fork
put/get
import/export
process recovery
timeouts
structured errors
```

At this point Blenderbox becomes a strong agent primitive.

---

# 47. V2

Add:

```text
HTTP remote API
GPU scheduling
session profiles
Blender version management
resource quotas
```

Now it can run as shared infrastructure.

---

# 48. V3

Add optional integrations:

```text
MCP adapter
Poly Haven
Sketchfab
3D generation APIs
texture generation
asset caching
```

These remain outside the core session abstraction.

---

# 49. Recommended implementation language

A daemon implementation in Rust or Go is attractive because the supervisor mostly needs to manage:

- processes
- sockets
- filesystem
- streaming logs
- HTTP
- timeouts
- concurrency
- resource accounting

Rust would fit particularly well if the broader system already uses Rust infrastructure.

However, an initial prototype could easily be written in Python.

The Blender-side bootstrap is naturally Python because it runs inside Blender.

Potential architecture:

```text
Rust daemon
    │
    ├── process supervisor
    ├── HTTP/CLI API
    ├── checkpoint manager
    └── file manager
          │
          ▼
    Blender process
          │
      Python bootstrap
          │
          ▼
         bpy
```

---

# 50. CLI versus SDK versus MCP

## CLI

Best for:

- Codex
- Claude Code
- shell agents
- humans
- debugging
- scripts

## Python SDK

Best for:

- orchestration
- tests
- higher-level agent runtimes
- bulk operations

## HTTP

Best for:

- remote hosting
- language-neutral access
- distributed execution

## MCP

Best for:

- generic MCP clients
- clients that do not execute ordinary code well
- compatibility with existing Blender MCP workflows

All should share the same backend.

---

# 51. What Blenderbox should *not* become

Avoid turning Blenderbox into a giant handcrafted Blender API.

Do not begin with:

```text
blenderbox cube create
blenderbox cube move
blenderbox cube rotate
blenderbox material set-color
blenderbox mesh extrude
...
```

That duplicates Blender's own API and increases maintenance dramatically.

Agents can already write:

```python
import bpy
```

Blenderbox should provide infrastructure around Blender, not replace Blender's API.

---

# 52. What deserves a first-class command

A feature should become a Blenderbox primitive when it relates to session infrastructure rather than normal Blender modeling.

Good first-class features:

```text
create
close
exec
inspect
preview
render
save
checkpoint
fork
put/get
import/export
```

Poor first-class features:

```text
bevel
extrude
rotate
set roughness
create cube
move vertex
```

Those belong in `bpy`.

---

# 53. Suggested repository layout

```text
blenderbox/
├── cmd/
│   └── blenderbox/
├── daemon/
│   ├── sessions/
│   ├── process/
│   ├── rpc/
│   ├── files/
│   └── checkpoints/
├── blender/
│   └── bootstrap.py
├── sdk/
│   ├── python/
│   └── typescript/
├── adapters/
│   └── mcp/
├── tests/
│   ├── lifecycle/
│   ├── bpy/
│   ├── render/
│   ├── checkpoint/
│   └── mcp_parity/
└── docs/
```

---

# 54. MCP parity test suite

If full Blender-MCP task compatibility is a design goal, make it measurable.

Create a corpus of tasks such as:

```text
create cube
create material
assign material
move object
create camera
create light
render
inspect scene
import GLB
export GLB
add modifier
run arbitrary Python
download/import external asset
```

For each task:

```text
reference Blender MCP
        vs.
Blenderbox
```

Verify:

- equivalent scene state
- equivalent exported files
- visually equivalent result where relevant
- no unsupported capabilities

The test should focus on task completion rather than identical internal implementation.

---

# 55. Definition of “100% Blender MCP compatibility”

Blenderbox can claim compatibility when:

> For every supported reference Blender MCP workflow, an agent can achieve the same meaningful Blender result using Blenderbox without requiring an interactive GUI.

The one known semantic difference is viewport imagery.

Blenderbox should provide:

```text
deterministic headless preview
```

instead of:

```text
literal screenshot of interactive VIEW_3D
```

unless an actual UI context becomes technically necessary.

That should be considered feature parity for agent workflows.

---

# 56. Final architecture

```text
                         AGENTS
           ┌──────────────┼──────────────┐
           │              │              │
        Codex        Claude Code      OpenCode
           │              │              │
           └──────────────┼──────────────┘
                          │
              CLI / SDK / HTTP / MCP
                          │
                 BLENDERBOX DAEMON
                          │
         ┌────────────────┼────────────────┐
         │                │                │
      Session A        Session B        Session C
         │                │                │
     workspace A      workspace B      workspace C
         │                │                │
      Blender A        Blender B        Blender C
         │                │                │
        bpy              bpy              bpy
         │                │                │
    render/save      render/save      render/save
```

Optional shared infrastructure:

```text
            ┌─────────────────────────┐
            │ Shared read-only assets │
            │ Blender installations   │
            │ asset cache             │
            │ render cache            │
            └─────────────────────────┘
```

---

# 57. Final design principles

1. **The session is the product.**  
   MCP is only one possible client.

2. **One session means one Blender process.**  
   Do not use Scenes as security or isolation boundaries.

3. **Headless by default.**  
   No GUI is needed for the intended workflow.

4. **Arbitrary `bpy` is the primary modeling API.**  
   Do not duplicate Blender with hundreds of commands.

5. **Provide deterministic visual feedback.**  
   `preview` is more useful to agents than an arbitrary viewport screenshot.

6. **Checkpoint and fork are first-class.**  
   Parallel experimentation is a major advantage.

7. **Keep infrastructure separate from asset services.**  
   Poly Haven, Sketchfab, generated assets, etc. should be optional integrations.

8. **Serialize commands inside a session.**  
   Parallelism happens across sessions.

9. **Process isolation is the baseline safety boundary.**  
   Containers can be added when running untrusted code or multi-tenant workloads.

10. **Local and cloud should have the same abstraction.**  
    Only the process launcher, storage, and GPU scheduler should differ.

11. **macOS bundle IDs are irrelevant.**  
    Launch the Blender executable directly and supervise PIDs.

12. **Target task-level Blender MCP parity.**  
    Everything agents can accomplish with Blender MCP should be possible through Blenderbox.

---

# 58. The resulting primitive

The whole design can ultimately be summarized by a very small interaction surface:

```bash
SESSION=$(blenderbox create)

blenderbox exec $SESSION build.py
blenderbox inspect $SESSION
blenderbox preview $SESSION

CHECKPOINT=$(blenderbox checkpoint $SESSION)
VARIANT=$(blenderbox fork $CHECKPOINT)

blenderbox render $VARIANT
blenderbox export $VARIANT --format glb

blenderbox close $SESSION
blenderbox close $VARIANT
```

That is the intended Blender equivalent of giving an agent its own isolated browser session.

> **Blenderbox = browser sessions for `bpy`.**
