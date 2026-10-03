# Blenderbox workflows

Use `blenderbox help COMMAND` for arguments, examples, defaults and output semantics. `blenderbox help --all` prints the full reference without launching Blender or the daemon.

## Model and inspect

```bash
SESSION=$(blenderbox create)
blenderbox exec "$SESSION" <<'PY'
import bpy
cube = bpy.data.objects['Cube']
cube.name = 'Prototype'
cube.scale = (1, 1, 2)
result = {'object': cube.name}
PY
blenderbox inspect "$SESSION" object Prototype
blenderbox preview "$SESSION" --object Prototype --view perspective
```

Preview returns an absolute PNG path. Open it with the agent's available image viewer and iterate with `exec`. Preview uses neutral lighting in a temporary scene. Use `render` to evaluate the final scene lighting/materials/camera. Configure resolution, engine, samples and current frame through `bpy` before `render`.

Blender executes in the session workspace. `workspace` is available as a Python string inside `exec`/`eval`. Prefer absolute file paths derived from it or Blender-relative paths such as `//assets/wood.png`. A script file executes in the persistent namespace; it is not imported as a Python module and its adjacent host files are not automatically available.

## Branch and compare

```bash
BASE=$(blenderbox create --from ./base.blend)
CHECKPOINT=$(blenderbox checkpoint "$BASE")
A=$(blenderbox fork "$CHECKPOINT")
B=$(blenderbox fork "$CHECKPOINT")
blenderbox exec "$A" ./warm-lighting.py
blenderbox exec "$B" ./cool-lighting.py
blenderbox render "$A" --output renders/variant.png
blenderbox render "$B" --output renders/variant.png
```

Each variant has an independent process and asset copy. Commands in a session are serialized; independent sessions can execute concurrently. Compare actual scene renders when evaluating custom lighting because preview supplies its own neutral light rig. Save/export the chosen variant and close the sessions owned by this task. Checkpoints preserve `.blend` state and workspace files, not persistent Python globals.

## Assets and delivery

```bash
blenderbox put "$SESSION" ./wood.png assets/wood.png
blenderbox exec "$SESSION" <<'PY'
from pathlib import Path
texture = bpy.data.images.load(str(Path(workspace) / 'assets/wood.png'))
texture.filepath = '//assets/wood.png'
PY
blenderbox import "$SESSION" ./model.glb
blenderbox import "$SESSION" ./bundle/model.obj --resources ./bundle
blenderbox save "$SESSION"
blenderbox export "$SESSION" --format glb --output exports/model.glb
blenderbox get "$SESSION" exports/model.glb ./deliverables/model.glb
blenderbox get "$SESSION" scene.blend ./deliverables/source.blend
blenderbox close "$SESSION"
```

Import copies the model into the workspace. GLB is self-contained; glTF buffer/image resources are copied automatically. OBJ/FBX texture/material sidecars should be in an explicitly supplied `--resources` directory. An external asset referenced by an existing `.blend` remains an external dependency until copied into the workspace or packed with `bpy`. A `.blend` copied out alone may need its asset tree or packed assets to be portable.

Workspace file paths passed to `put`, `get`, `save`, `render`, `preview` and `export` must be relative and remain within the workspace. Source imports/files and `get` destinations are host paths. `get` without a destination locates a file and returns its absolute path; it does not stream file contents. `files` lists artifacts and works after close.

## Recover a failure

Python exceptions leave the process running and include `session_alive: true`, a traceback and captured Python output. Fix the code and continue. Earlier mutations remain; execution is not transactional.

An execution timeout or process crash loses unsaved state in that session. Inspect `status SESSION` and `WORKSPACE/logs/blender.log`, then create a new session from `fork CHECKPOINT` or `create --from SAVED.blend`. Other sessions continue independently. Reacquire `bpy` object references after loading another file.

`--timeout` excludes queue wait and terminates Blender when execution exceeds the deadline. Client Ctrl-C does not guarantee server cancellation; `close SESSION` can interrupt a busy process. Save before closing when possible. `daemon stop` preserves live processes for adoption; `daemon stop --close-sessions` closes every active session in the state root and requires authority over those tasks.
