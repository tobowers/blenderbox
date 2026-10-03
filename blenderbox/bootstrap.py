"""Runs inside background Blender; accept and execute RPC on its main thread."""
import contextlib
import io
import json
import math
import os
from pathlib import Path
import socket
import sys
import traceback
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from blenderbox.protocol import BoxError, receive, response, send

import bpy
from mathutils import Vector, Matrix, Euler, Quaternion, Color

WORKSPACE = Path(os.environ["BLENDERBOX_WORKSPACE"]).resolve()
NAMESPACE = {"bpy": bpy, "__name__": "__main__", "workspace": str(WORKSPACE)}


def json_value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise BoxError("serialization_error", "Non-finite float cannot be represented as JSON")
        return value
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, Vector, Matrix, Euler, Quaternion, Color)):
        return [json_value(item) for item in value]
    raise BoxError("serialization_error", f"Return JSON values rather than {type(value).__name__}")


def output_path(relative):
    relative = Path(relative)
    path = (WORKSPACE / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(WORKSPACE):
        raise BoxError("invalid_path", "Output paths must be relative to the session workspace")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def artifact(path):
    return {"path": str(path), "size": path.stat().st_size}


def object_info(obj):
    info = {"name": obj.name, "type": obj.type, "location": list(obj.location),
            "rotation": list(obj.rotation_euler), "scale": list(obj.scale),
            "dimensions": list(obj.dimensions), "hidden_render": obj.hide_render,
            "materials": [slot.material.name if slot.material else None for slot in obj.material_slots],
            "modifiers": [{"name": m.name, "type": m.type} for m in obj.modifiers]}
    if obj.type == "MESH":
        info["mesh"] = {"vertices": len(obj.data.vertices), "edges": len(obj.data.edges),
                        "polygons": len(obj.data.polygons)}
    return info


def inspect(scope="scene", name=None):
    scene = bpy.context.scene
    scene.view_layers[0].update()
    if scope == "object":
        obj = bpy.data.objects.get(name)
        if obj is None:
            raise BoxError("object_not_found", str(name))
        return object_info(obj)
    if scope == "objects":
        return [object_info(obj) for obj in scene.objects]
    if scope == "materials":
        return [{"name": m.name, "use_nodes": m.use_nodes, "diffuse_color": list(m.diffuse_color)}
                for m in bpy.data.materials]
    if scope in {"cameras", "lights"}:
        kind = "CAMERA" if scope == "cameras" else "LIGHT"
        return [object_info(obj) for obj in scene.objects if obj.type == kind]
    if scope == "collections":
        return [{"name": c.name, "objects": list(c.objects.keys())} for c in bpy.data.collections]
    if scope == "render":
        return {"engine": scene.render.engine, "resolution": [scene.render.resolution_x, scene.render.resolution_y],
                "percentage": scene.render.resolution_percentage,
                "camera": scene.camera.name if scene.camera else None, "filepath": scene.render.filepath}
    if scope != "scene":
        raise BoxError("invalid_scope", str(scope))
    return {"scene": scene.name, "objects": [object_info(obj) for obj in scene.objects],
            "cameras": [o.name for o in scene.objects if o.type == "CAMERA"],
            "lights": [o.name for o in scene.objects if o.type == "LIGHT"],
            "blender_version": bpy.app.version_string, "frame": scene.frame_current}


def render(request):
    scene = bpy.context.scene
    camera = scene.camera
    if request.get("camera"):
        camera = scene.objects.get(request["camera"])
    if camera is None or camera.type != "CAMERA":
        raise BoxError("camera_not_found", "Set a scene camera or pass --camera NAME")
    path = output_path(request.get("output") or "renders/final.png")
    original = (scene.camera, scene.render.filepath, scene.render.image_settings.file_format)
    try:
        scene.camera = camera
        scene.render.filepath = str(path)
        scene.render.image_settings.file_format = "PNG"
        bpy.ops.render.render(write_still=True, scene=scene.name)
        return artifact(path)
    finally:
        scene.camera, scene.render.filepath, scene.render.image_settings.file_format = original


def preview(request):
    source = bpy.context.scene
    source.view_layers[0].update()
    objects = list(source.objects)
    if request.get("object"):
        obj = source.objects.get(request["object"])
        if obj is None:
            raise BoxError("object_not_found", request["object"])
        objects = [obj]
    elif request.get("collection"):
        collection = bpy.data.collections.get(request["collection"])
        if collection is None:
            raise BoxError("collection_not_found", request["collection"])
        objects = list(collection.all_objects)
    geometry = [obj for obj in objects if obj.type in {"MESH", "CURVE", "SURFACE", "META", "FONT", "VOLUME", "POINTCLOUD"}
                and not obj.hide_render]
    if not geometry:
        raise BoxError("empty_preview", "No renderable geometry in the requested scope")
    resolution = int(request.get("resolution", 512))
    samples = int(request.get("samples", 16))
    if not 32 <= resolution <= 4096 or not 1 <= samples <= 4096:
        raise BoxError("invalid_preview", "resolution must be 32..4096; samples must be 1..4096")
    directions = {"perspective": (1, -1, .8), "front": (0, -1, 0), "back": (0, 1, 0),
                  "left": (-1, 0, 0), "right": (1, 0, 0), "top": (0, 0, 1), "bottom": (0, 0, -1)}
    view = request.get("view", "perspective")
    if view not in directions:
        raise BoxError("invalid_view", str(view))
    depsgraph = bpy.context.evaluated_depsgraph_get()
    points = [obj.matrix_world @ Vector(corner) for obj in geometry
              for corner in obj.evaluated_get(depsgraph).bound_box]
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    center = (low + high) / 2
    radius = max((high - low).length / 2, .05)
    path = output_path(request.get("output") or f"renders/preview-{uuid.uuid4().hex[:8]}.png")
    temporary_scene = bpy.data.scenes.new("__blenderbox_preview")
    temporary_objects = []
    temporary_data = []
    world = None
    try:
        for obj in geometry:
            temporary_scene.collection.objects.link(obj)
        temporary_scene.frame_set(source.frame_current)
        temporary_scene.render.engine = "CYCLES"
        temporary_scene.cycles.device = "CPU"
        temporary_scene.cycles.samples = samples
        temporary_scene.cycles.seed = 0
        temporary_scene.render.threads_mode = "FIXED"
        temporary_scene.render.threads = source.render.threads
        temporary_scene.render.resolution_x = resolution
        temporary_scene.render.resolution_y = resolution
        temporary_scene.render.resolution_percentage = 100
        temporary_scene.render.image_settings.file_format = "PNG"
        temporary_scene.render.filepath = str(path)
        world = bpy.data.worlds.new("__blenderbox_world")
        world.use_nodes = True
        world.node_tree.nodes.get("Background").inputs[0].default_value = (.18, .18, .18, 1)
        world.node_tree.nodes.get("Background").inputs[1].default_value = .5
        temporary_scene.world = world
        data = bpy.data.cameras.new("__blenderbox_camera")
        temporary_data.append(data)
        camera = bpy.data.objects.new("__blenderbox_camera", data)
        temporary_objects.append(camera)
        temporary_scene.collection.objects.link(camera)
        direction = Vector(directions[view]).normalized()
        camera.location = center + direction * radius * 3.8
        camera.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()
        data.type = "PERSP" if view == "perspective" else "ORTHO"
        data.lens = 45
        data.ortho_scale = radius * 2.5
        data.clip_start = max(radius / 1000, .0001)
        data.clip_end = radius * 100 + 100
        temporary_scene.camera = camera
        for offset, energy in [((2, -3, 4), 1000), ((-3, -1, 2), 600), ((1, 3, 3), 900)]:
            light_data = bpy.data.lights.new("__blenderbox_light", "AREA")
            temporary_data.append(light_data)
            light_data.energy = energy * radius * radius
            light_data.shape = "DISK"
            light_data.size = radius * 3
            light = bpy.data.objects.new("__blenderbox_light", light_data)
            temporary_objects.append(light)
            temporary_scene.collection.objects.link(light)
            light.location = center + Vector(offset) * radius
            light.rotation_euler = (center - light.location).to_track_quat("-Z", "Y").to_euler()
        bpy.ops.render.render(write_still=True, scene=temporary_scene.name)
        return {**artifact(path), "view": view, "resolution": resolution,
                "objects": [obj.name for obj in geometry]}
    finally:
        bpy.data.scenes.remove(temporary_scene)
        for obj in temporary_objects:
            bpy.data.objects.remove(obj, do_unlink=True)
        for data in temporary_data:
            (bpy.data.cameras if isinstance(data, bpy.types.Camera) else bpy.data.lights).remove(data)
        if world:
            bpy.data.worlds.remove(world)
        # frame_set on a temporary scene may evaluate shared animation data.
        source.frame_set(source.frame_current)


def transfer(request):
    op = request["op"]
    if op == "import":
        path = Path(request["source"])
        format = path.suffix.lower().lstrip(".")
        operators = {"glb": bpy.ops.import_scene.gltf, "gltf": bpy.ops.import_scene.gltf,
                     "obj": bpy.ops.wm.obj_import, "stl": bpy.ops.wm.stl_import,
                     "ply": bpy.ops.wm.ply_import, "fbx": bpy.ops.import_scene.fbx}
        if format not in operators:
            raise BoxError("unsupported_format", "Use bpy for this format; built-ins support GLB, glTF, OBJ, STL, PLY, FBX")
        before = set(bpy.data.objects.keys())
        operators[format](filepath=str(path))
        return {"path": str(path), "objects": sorted(set(bpy.data.objects.keys()) - before)}
    format = request.get("format", "glb").lower()
    path = output_path(request.get("output") or f"exports/scene.{format}")
    options = {"filepath": str(path)}
    if request.get("selected"):
        options["export_selected_objects" if format in {"obj", "stl", "ply"} else "use_selection"] = True
    if format in {"glb", "gltf"}:
        # glTF uses a different selection keyword.
        options.pop("use_selection", None)
        options["use_selection"] = bool(request.get("selected"))
        bpy.ops.export_scene.gltf(export_format="GLB" if format == "glb" else "GLTF_SEPARATE", **options)
    elif format == "obj":
        bpy.ops.wm.obj_export(**options)
    elif format == "stl":
        bpy.ops.wm.stl_export(**options)
    elif format == "ply":
        bpy.ops.wm.ply_export(**options)
    elif format == "fbx":
        bpy.ops.export_scene.fbx(**options)
    elif format == "blend":
        bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True)
    else:
        raise BoxError("unsupported_format", str(format))
    return artifact(path)


def dispatch(request):
    op = request["op"]
    if op == "ping":
        return {"blender_version": bpy.app.version_string, "pid": os.getpid()}
    if op == "exec":
        NAMESPACE.pop("result", None)
        exec(compile(request["code"], "<blenderbox-exec>", "exec"), NAMESPACE)
        return json_value(NAMESPACE.get("result"))
    if op == "eval":
        return json_value(eval(request["expression"], NAMESPACE))
    if op == "inspect":
        return inspect(request.get("scope", "scene"), request.get("name"))
    if op == "save":
        path = output_path(request.get("path") or "scene.blend")
        bpy.ops.wm.save_as_mainfile(filepath=str(path), relative_remap=True)
        return artifact(path)
    if op == "preview":
        return preview(request)
    if op == "render":
        return render(request)
    if op in {"import", "export"}:
        return transfer(request)
    raise BoxError("unknown_command", str(op))


def main():
    os.umask(0o077)
    endpoint = Path(os.environ["BLENDERBOX_ENDPOINT"])
    endpoint.unlink(missing_ok=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(endpoint))
        server.listen(16)
        print(f"Blenderbox ready: {endpoint}", flush=True)
        while True:
            connection, _ = server.accept()
            with connection:
                stdout, stderr = io.StringIO(), io.StringIO()
                try:
                    connection.settimeout(30)
                    request = receive(connection)
                    connection.settimeout(None)
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        reply = response(dispatch, request)
                    if reply.get("type") == "internal_error":
                        reply["type"] = "python_exception"
                    reply.update(stdout=stdout.getvalue(), stderr=stderr.getvalue())
                    # Python errors (including SystemExit/KeyboardInterrupt from user code)
                    # should not take down an otherwise healthy session.
                    if request["op"] == "exec" and reply["status"] == "ok":
                        reply["result"] = {"value": reply["result"], "stdout": reply["stdout"], "stderr": reply["stderr"]}
                    try:
                        send(connection, reply)
                    except BoxError as exc:
                        send(connection, {"status": "error", **exc.error})
                except (SystemExit, KeyboardInterrupt) as exc:
                    send(connection, {"status": "error", "type": "python_exception", "message": str(exc),
                                      "traceback": traceback.format_exc(), "stdout": stdout.getvalue(), "stderr": stderr.getvalue()})
                except (OSError, EOFError):
                    pass
            # A namespace may hold stale bpy references after open_mainfile; the
            # agent is responsible for reacquiring them, as with ordinary Blender.


if __name__ == "__main__":
    main()
