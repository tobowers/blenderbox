"""Real Blender contract tests, using an isolated daemon and state directory."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from blenderbox import Blender, BoxError
from blenderbox.client import result
from blenderbox.daemon import workspace_path


class Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="blenderbox-test-")
        cls.old_home = os.environ.get("BLENDERBOX_HOME")
        os.environ["BLENDERBOX_HOME"] = cls.temp.name

    @classmethod
    def tearDownClass(cls):
        for session in result("sessions"):
            result("close", session=session["id"])
        pid = result("ping")["pid"]
        os.kill(pid, signal.SIGTERM)
        if cls.old_home is None:
            os.environ.pop("BLENDERBOX_HOME", None)
        else:
            os.environ["BLENDERBOX_HOME"] = cls.old_home
        cls.temp.cleanup()

    def setUp(self):
        self.sessions = []

    def tearDown(self):
        for session in self.sessions:
            session.close()

    def create(self, **options):
        session = Blender.create(**options)
        self.sessions.append(session)
        return session

    def test_cli_persistent_state_and_python_errors(self):
        cli = [sys.executable, "-m", "blenderbox.cli"]
        session_id = subprocess.check_output(cli + ["create"], text=True).strip()
        b = Blender(session_id)
        self.sessions.append(b)
        run = subprocess.run(cli + ["exec", b.id], input="counter = 41\nprint('captured')\nresult = {'ok': True}\n",
                             text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(run.stdout), {"value": {"ok": True}, "stdout": "captured\n", "stderr": ""})
        self.assertEqual(b.eval("counter + 1"), 42)
        run = subprocess.run(cli + ["eval", b.id, "1/0"], text=True, capture_output=True)
        self.assertEqual(run.returncode, 1)
        error = json.loads(run.stderr)
        self.assertEqual(error["type"], "python_exception")
        self.assertTrue(error["session_alive"])
        self.assertEqual(b.eval("counter"), 41)
        with self.assertRaises(BoxError) as caught:
            b.exec("print('before error')\nraise SystemExit(2)")
        self.assertEqual(caught.exception.error["stdout"], "before error\n")
        self.assertEqual(b.status()["status"], "ready")

    def test_isolation_and_concurrent_execution(self):
        a, b = self.create(), self.create()
        self.assertNotEqual(a.status()["pid"], b.status()["pid"])
        self.assertNotEqual(a.status()["workspace"], b.status()["workspace"])
        a.exec("bpy.data.objects['Cube'].name = 'OnlyA'\ncounter = 0")
        self.assertNotIn("OnlyA", b.eval("list(bpy.data.objects.keys())"))
        with ThreadPoolExecutor(max_workers=2) as pool:
            start = time.monotonic()
            futures = [pool.submit(s.exec, "import time; time.sleep(1)") for s in (a, b)]
            for f in futures:
                f.result()
            self.assertLess(time.monotonic() - start, 1.9)
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(a.exec, "old = counter\nimport time; time.sleep(.025)\ncounter = old + 1")
                       for _ in range(8)]
            for f in futures:
                f.result()
        self.assertEqual(a.eval("counter"), 8)
        self.assertEqual(a.eval("__import__('os').environ['HOME']"), a.status()["workspace"] + "/home")
        self.assertFalse(a.eval("'bl_ext.user_default.mcp' in bpy.context.preferences.addons"))

    def test_preview_is_visual_and_restores_scene(self):
        b = self.create()
        b.exec("mod = bpy.data.objects['Cube'].modifiers.new('Bevel', 'BEVEL'); mod.width = .2; mod.segments = 3")
        before = b.eval("{'objects':list(bpy.data.objects.keys()), 'scenes':list(bpy.data.scenes.keys()), "
                        "'worlds':list(bpy.data.worlds.keys()), 'camera':bpy.context.scene.camera.name, "
                        "'engine':bpy.context.scene.render.engine, 'filepath':bpy.context.scene.render.filepath}")
        image = b.preview(object="Cube", resolution=128, samples=4)
        path = Path(image["path"])
        self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertGreater(image["size"], 1000)
        after = b.eval("{'objects':list(bpy.data.objects.keys()), 'scenes':list(bpy.data.scenes.keys()), "
                       "'worlds':list(bpy.data.worlds.keys()), 'camera':bpy.context.scene.camera.name, "
                       "'engine':bpy.context.scene.render.engine, 'filepath':bpy.context.scene.render.filepath}")
        self.assertEqual(before, after)
        with self.assertRaises(BoxError):
            b.preview(object="NoSuchObject")
        self.assertEqual(b.status()["status"], "ready")

    @unittest.skipUnless(sys.platform == "darwin", "macOS app identity")
    def test_macos_worker_runs_outside_desktop_bundle(self):
        b = self.create()
        binary = Path(b.status()["blender"])
        self.assertFalse(any(part.endswith(".app") for part in binary.parts))
        self.assertFalse((binary.parent.parent / "Info.plist").exists())
        self.assertFalse(binary.is_symlink())
        subprocess.run(["/usr/bin/codesign", "--verify", str(binary)], check=True)
        b.preview(object="Cube", resolution=32, samples=1)
        # Read the process's actual bundle identity, not only the plist on disk.
        identity = b.exec("""
import ctypes
objc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')
objc.objc_getClass.argtypes = [ctypes.c_char_p]
objc.objc_getClass.restype = ctypes.c_void_p
objc.sel_registerName.argtypes = [ctypes.c_char_p]
objc.sel_registerName.restype = ctypes.c_void_p
send_pointer = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(('objc_msgSend', objc))
send_string = ctypes.CFUNCTYPE(ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p)(('objc_msgSend', objc))
bundle = send_pointer(objc.objc_getClass(b'NSBundle'), objc.sel_registerName(b'mainBundle'))
identifier = send_pointer(bundle, objc.sel_registerName(b'bundleIdentifier'))
result = send_string(identifier, objc.sel_registerName(b'UTF8String')).decode() if identifier else None
""")
        self.assertIsNone(identity["value"])
        registered = subprocess.check_output(["/usr/bin/lsappinfo", "info", f"#{b.status()['pid']}"], text=True)
        self.assertNotIn('bundleID="org.blenderfoundation.blender"', registered)

    def test_checkpoint_fork_and_asset_copy(self):
        b = self.create()
        asset = Path(self.temp.name) / "asset.txt"
        asset.write_text("base")
        b.put(asset, "assets/base.txt")
        b.exec("bpy.data.objects['Cube'].name = 'BaseCube'")
        checkpoint = b.checkpoint()
        fork = Blender(result("fork", source=checkpoint)["id"])
        self.sessions.append(fork)
        self.assertIn("BaseCube", fork.eval("list(bpy.data.objects.keys())"))
        fork.exec("bpy.data.objects['BaseCube'].name = 'Variant'")
        self.assertIn("BaseCube", b.eval("list(bpy.data.objects.keys())"))
        copied = Path(fork.get("assets/base.txt")["path"])
        self.assertEqual(copied.read_text(), "base")
        copied.write_text("variant")
        self.assertEqual(Path(b.get("assets/base.txt")["path"]).read_text(), "base")
        implicit = b.fork()
        self.sessions.append(implicit)
        self.assertIn("BaseCube", implicit.eval("list(bpy.data.objects.keys())"))
        # Restart from a saved file should remap relative paths and retain geometry.
        restored = self.create(source=b.save()["path"])
        self.assertIn("BaseCube", restored.eval("list(bpy.data.objects.keys())"))

    def test_render_and_export_import(self):
        b = self.create()
        b.exec("bpy.context.scene.render.engine = 'CYCLES'\nbpy.context.scene.cycles.samples = 4\n"
               "bpy.context.scene.render.resolution_x = 64\nbpy.context.scene.render.resolution_y = 64")
        original = b.inspect("render")
        image = b.render()
        self.assertTrue(Path(image["path"]).is_file())
        self.assertEqual(original, b.inspect("render"))
        for format in ("glb", "gltf", "obj", "stl", "ply", "fbx", "blend"):
            with self.subTest(format=format):
                exported = b.export(format=format)
                self.assertGreater(exported["size"], 0)
                if format != "blend":
                    selected = b.export(format=format, output=f"exports/selected.{format}", selected=True)
                    self.assertGreater(selected["size"], 0)
        target = self.create()
        target.exec("bpy.data.objects.remove(bpy.data.objects['Cube'], do_unlink=True)")
        imported = target.import_file(b.get("exports/scene.glb")["path"])
        self.assertTrue(imported["objects"])
        gltf = target.import_file(b.get("exports/scene.gltf")["path"])
        self.assertTrue(gltf["objects"])

    def test_timeout_and_crash_are_isolated(self):
        good, runaway = self.create(), self.create()
        with self.assertRaises(BoxError) as caught:
            runaway.exec("while True: pass", timeout=.3)
        self.assertEqual(caught.exception.error["type"], "timeout")
        self.assertFalse(caught.exception.error["session_alive"])
        self.assertEqual(runaway.status()["status"], "timed_out")
        crashed = self.create()
        with self.assertRaises(BoxError) as caught:
            crashed.exec("import os; os._exit(17)")
        self.assertEqual(caught.exception.error["type"], "process_crash")
        self.assertEqual(crashed.status()["status"], "crashed")
        self.assertEqual(good.eval("6 * 7"), 42)

    def test_daemon_restart_adopts_live_session(self):
        b = self.create()
        b.exec("persistent_global = 'alive'")
        pid = b.status()["pid"]
        daemon_pid = result("ping")["pid"]
        os.kill(daemon_pid, signal.SIGTERM)
        time.sleep(.2)
        self.assertNotEqual(result("ping")["pid"], daemon_pid)
        self.assertEqual(b.status()["pid"], pid)
        self.assertEqual(b.eval("persistent_global"), "alive")

    def test_close_interrupts_a_busy_session(self):
        b = self.create()
        with ThreadPoolExecutor(max_workers=1) as pool:
            running = pool.submit(b.exec, "import time; time.sleep(60)")
            deadline = time.monotonic() + 5
            while b.status()["status"] != "busy" and time.monotonic() < deadline:
                time.sleep(.02)
            start = time.monotonic()
            self.assertEqual(b.close()["status"], "closed")
            self.assertLess(time.monotonic() - start, 4)
            with self.assertRaises(BoxError):
                running.result(timeout=5)
        self.assertEqual(b.status()["status"], "closed")

    def test_file_paths_and_structured_serialization_errors(self):
        b = self.create()
        for path in ("../escape", "/tmp/escape"):
            with self.assertRaises(BoxError):
                b.save(path)
        workspace = Path(b.status()["workspace"])
        (workspace / "assets" / "outside").symlink_to(self.temp.name)
        with self.assertRaises(BoxError):
            workspace_path(workspace, "assets/outside/escape")
        (workspace / "assets" / "outside").unlink()
        with self.assertRaises(BoxError) as caught:
            b.eval("bpy.context.object")
        self.assertEqual(caught.exception.error["type"], "serialization_error")
        with self.assertRaises(BoxError):
            b.eval("float('nan')")
        self.assertEqual(b.eval("bpy.context.object.location"), [0, 0, 0])


if __name__ == "__main__":
    unittest.main()
