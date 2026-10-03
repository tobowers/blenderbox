# Python SDK

Install Blenderbox into the Python environment used for orchestration (`pip install /path/to/blenderbox`), or use the Python interpreter inside its installed tool environment. The SDK and CLI share the supervisor selected by `BLENDERBOX_HOME`.

```python
from blenderbox import Blender, BoxError

with Blender.create(threads=2) as b:
    b.exec("bpy.data.objects['Cube'].name = 'Product'")
    names = b.eval("list(bpy.data.objects.keys())")
    image = b.preview(object='Product', resolution=512)
    print(image['path'])
    b.save()
    exported = b.export(format='glb', output='exports/product.glb')
    b.get('exports/product.glb', './deliverables/product.glb')
```

The context manager closes Blender and retains files. It does not automatically save. `Blender(session_id)` attaches to a known session; attach only to a session owned by the task.

| Method | Result / semantics |
| --- | --- |
| `Blender.create(source=None, blender=None, timeout=60, threads=2)` | New `Blender` instance; source and blender are host paths |
| `b.status()` | Lifecycle record with PID/workspace/status |
| `b.exec(code, timeout=60)` | `{value, stdout, stderr}`; set `result` in code to return JSON |
| `b.eval(expression, timeout=60)` | JSON value; vectors/matrices become arrays |
| `b.inspect(scope='scene', name=None)` | Compact scene/scope data |
| `b.preview(**options)` | PNG artifact and framing metadata; options use CLI parameter names |
| `b.render(output='renders/final.png', **options)` | PNG artifact using scene settings; camera and timeout are optional |
| `b.save(path='scene.blend')` | Saved `.blend` artifact |
| `b.checkpoint()` | Checkpoint ID string |
| `b.fork()` | New `Blender` instance from an implicit checkpoint |
| `b.put(source, destination)` | Copy host file to a workspace-relative destination |
| `b.get(path, destination=None)` | Locate workspace file or copy it to a host destination |
| `b.files()` | Relative artifact paths/sizes |
| `b.import_file(source, **options)` | Imported model path and created object names; optional resources directory |
| `b.export(format='glb', output=None, **options)` | Export artifact; optional selected and timeout |
| `b.close()` | Terminate the process and return its final record |

Python globals persist only inside the live session. Checkpoints capture saved Blender state and workspace assets, not interpreter globals. Use distinct sessions/forks for concurrent agents; a session remains a single writer. Do not use threads to call `bpy` inside Blender.

```python
try:
    b.exec('raise ValueError("bad input")', timeout=30)
except BoxError as exc:
    print(exc.error['type'], exc.error['message'])
    if exc.error.get('session_alive'):
        print('Repair code and continue in the current session')
    else:
        print('Recover from a checkpoint or a saved .blend')
```

Errors have structured fields in `BoxError.error`; Python errors include traceback and output. Mutations before an exception remain. Timeouts kill that Blender process. `preview`, `render`, import/export and save return artifact dictionaries with an absolute `path` and byte `size`; outputs passed to them are workspace-relative.
