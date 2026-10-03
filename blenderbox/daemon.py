"""Local supervisor. Blender state is touched only by bootstrap's main thread."""
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import socketserver
import subprocess
import threading
import time
import uuid
from collections import deque

from . import __version__
from .client import state_root, runtime_root
from .protocol import BoxError, call, receive, response, send

ID = re.compile(r"^(bbx|chk)_[a-f0-9]{16}$")
DIRECTORIES = ("assets", "exports", "renders", "scripts", "checkpoints", "logs", "tmp", "home", "config")
INTERNAL = {"logs", "tmp", "home", "config", "checkpoints", "session.json"}


class SerialLock:
    """FIFO command admission, with nonblocking lifecycle reads."""
    def __init__(self):
        self.condition = threading.Condition()
        self.queue = deque()
        self.held = False

    def acquire(self, blocking=True):
        with self.condition:
            if not blocking:
                if self.held or self.queue:
                    return False
                self.held = True
                return True
            ticket = object()
            self.queue.append(ticket)
            while self.held or self.queue[0] is not ticket:
                self.condition.wait()
            self.queue.popleft()
            self.held = True
            return True

    def release(self):
        with self.condition:
            self.held = False
            self.condition.notify_all()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()


def write_json(path, data):
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".new")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def workspace_path(workspace, relative):
    candidate = Path(relative)
    path = (workspace / candidate).resolve()
    if candidate.is_absolute() or not path.is_relative_to(workspace.resolve()):
        raise BoxError("invalid_path", "Session paths must stay within the workspace")
    return path


class Manager:
    def __init__(self, root):
        self.root = root
        self.runtime = runtime_root(root)
        self.sessions = {}
        self.registry_lock = threading.RLock()
        (root / "sessions").mkdir(parents=True, exist_ok=True)
        (root / "checkpoints").mkdir(exist_ok=True)
        for path in (root / "sessions").glob("bbx_*/session.json"):
            try:
                record = json.loads(path.read_text())
                if ID.fullmatch(record["id"]):
                    self.sessions[record["id"]] = {"record": record, "lock": SerialLock(),
                                                   "stop_lock": threading.Lock(), "process": None}
            except (ValueError, KeyError):
                continue

    def persist(self, session):
        write_json(Path(session["record"]["workspace"]) / "session.json", session["record"])

    def lookup(self, session_id):
        with self.registry_lock:
            if session_id not in self.sessions:
                raise BoxError("invalid_session", f"Unknown session: {session_id}")
            return self.sessions[session_id]

    def alive(self, session):
        record = session["record"]
        if record["status"] in {"closed", "failed", "crashed", "timed_out"}:
            return False
        if record["status"] == "creating" and not record.get("pid"):
            return False
        process = session["process"]
        if process is not None:
            code = process.poll()
            if code is None:
                return True
            record.update(status="crashed", exit_code=code)
        else:
            # Avoid signalling a recycled PID when adopting after a daemon restart.
            pid = record.get("pid")
            args = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                                  capture_output=True, text=True).stdout
            if f"--box-session {record['id']}" in args:
                return True
            record.update(status="crashed", exit_code=None)
        self.persist(session)
        return False

    def stop(self, session, status="closed"):
        with session["stop_lock"]:
            # A user close takes precedence over an in-flight RPC reporting EOF.
            if session["record"]["status"] == "closed":
                return dict(session["record"])
            return self._stop(session, status)

    def _stop(self, session, status):
        if self.alive(session):
            pid = session["record"]["pid"]
            process = session["process"]
            def signal_group(sig):
                try:
                    os.killpg(pid, sig)
                except PermissionError:
                    # Darwin can report EPERM for a group disappearing during
                    # process exit. Reap that child before trying a PID signal.
                    if process is not None:
                        try:
                            process.wait(timeout=.1)
                            return
                        except subprocess.TimeoutExpired:
                            pass
                    os.kill(pid, sig)
            try:
                signal_group(signal.SIGTERM)
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    process = session["process"]
                    if process is not None and process.poll() is not None:
                        break
                    if process is None:
                        try:
                            os.kill(pid, 0)
                        except ProcessLookupError:
                            break
                    time.sleep(.05)
                else:
                    signal_group(signal.SIGKILL)
                if session["process"] is not None:
                    session["process"].wait(timeout=5)
            except ProcessLookupError:
                pass
        session["record"].update(status=status, closed_at=time.time())
        if session["process"] is not None:
            session["record"]["exit_code"] = session["process"].poll()
        Path(session["record"]["rpc_endpoint"]).unlink(missing_ok=True)
        self.persist(session)
        return dict(session["record"])

    def binary(self, override=None):
        executable = override or os.environ.get("BLENDERBOX_BLENDER") or shutil.which("blender")
        if not executable and Path("/Applications/Blender.app/Contents/MacOS/Blender").exists():
            executable = "/Applications/Blender.app/Contents/MacOS/Blender"
        if not executable or not Path(executable).is_file() or not os.access(executable, os.X_OK):
            raise BoxError("blender_not_found", "Set BLENDERBOX_BLENDER or pass --blender /path/to/blender")
        return str(Path(executable).resolve())

    def create(self, source=None, blender=None, timeout=60, threads=2, snapshot=None, checkpoint=None):
        binary = self.binary(blender)
        if source and not Path(source).is_file():
            raise BoxError("file_not_found", str(source))
        if not isinstance(threads, int) or threads < 1:
            raise BoxError("invalid_threads", "threads must be a positive integer")
        session_id = "bbx_" + uuid.uuid4().hex[:16]
        workspace = self.root / "sessions" / session_id
        workspace.mkdir(mode=0o700)
        if snapshot:
            shutil.copytree(snapshot, workspace, dirs_exist_ok=True)
        for directory in DIRECTORIES:
            (workspace / directory).mkdir(exist_ok=True)
        rpc = self.runtime / (session_id + ".sock")
        record = {"id": session_id, "status": "creating", "created_at": time.time(),
                  "workspace": str(workspace), "rpc_endpoint": str(rpc), "blender": binary,
                  "blenderbox_version": __version__, "source_checkpoint": checkpoint,
                  "threads": threads, "dirty": False}
        session = {"record": record, "lock": SerialLock(), "stop_lock": threading.Lock(), "process": None}
        session["lock"].acquire()
        with self.registry_lock:
            self.sessions[session_id] = session
        self.persist(session)
        bootstrap = Path(__file__).with_name("bootstrap.py")
        args = [binary, "--background", "--factory-startup", "--disable-autoexec", "--threads", str(threads)]
        blend = source or (str(workspace / "scene.blend") if snapshot else None)
        if blend:
            args.append(str(Path(blend).resolve()))
        args += ["--python-exit-code", "1", "--python", str(bootstrap), "--", "--box-session", session_id]
        env = os.environ.copy()
        # Blender must not inherit the supervisor's Python runtime or any MCP settings.
        for key in list(env):
            if key.startswith(("PYTHON", "BLENDER_USER_", "BLENDER_MCP_")):
                env.pop(key)
        env.update(HOME=str(workspace / "home"), TMPDIR=str(workspace / "tmp"),
                   BLENDER_USER_CONFIG=str(workspace / "config"),
                   BLENDER_USER_SCRIPTS=str(workspace / "scripts"),
                   BLENDER_USER_DATAFILES=str(workspace / "home" / "datafiles"),
                   BLENDERBOX_WORKSPACE=str(workspace), BLENDERBOX_ENDPOINT=str(rpc))
        try:
            with (workspace / "logs" / "blender.log").open("ab") as log:
                session["process"] = subprocess.Popen(args, cwd=workspace, env=env, stdin=subprocess.DEVNULL,
                                                      stdout=log, stderr=log, start_new_session=True)
            record["pid"] = session["process"].pid
            self.persist(session)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if session["process"].poll() is not None:
                    raise BoxError("startup_failure", f"Blender exited; see {workspace / 'logs/blender.log'}")
                try:
                    ping = call(rpc, {"op": "ping"}, timeout=min(1, max(.01, deadline-time.monotonic())))
                    if ping["status"] == "ok":
                        record.update(status="ready", blender_version=ping["result"]["blender_version"])
                        self.persist(session)
                        self.rpc(session, {"op": "save", "path": "scene.blend", "timeout": timeout})
                        return dict(record)
                except (OSError, EOFError):
                    time.sleep(.1)
            raise BoxError("startup_timeout", f"Blender startup timed out; see {workspace / 'logs/blender.log'}")
        except Exception:
            self.stop(session, "failed")
            raise
        finally:
            session["lock"].release()

    def rpc(self, session, request):
        record = session["record"]
        if not self.alive(session):
            raise BoxError("process_crash", f"Session is {record['status']}", session_alive=False,
                           logs=str(Path(record["workspace"]) / "logs/blender.log"))
        record.update(status="busy", last_command=request["op"])
        self.persist(session)
        try:
            reply = call(record["rpc_endpoint"], request, timeout=float(request.get("timeout", 60)))
        except (socket.timeout, TimeoutError):
            self.stop(session, "timed_out")
            raise BoxError("timeout", "Execution deadline exceeded; Blender process terminated",
                           session_alive=False)
        except (OSError, EOFError) as exc:
            self.stop(session, "crashed")
            raise BoxError("process_crash", str(exc), session_alive=False,
                           logs=str(Path(record["workspace"]) / "logs/blender.log")) from exc
        except BoxError:
            record["status"] = "ready"
            self.persist(session)
            raise
        if record["status"] == "closed":
            raise BoxError("session_closed", "Session was closed during execution", session_alive=False)
        record["status"] = "ready"
        if request["op"] in {"exec", "eval", "import"}:
            record["dirty"] = True
        elif request["op"] == "save" and reply["status"] == "ok":
            record["dirty"] = False
        self.persist(session)
        if reply["status"] != "ok":
            raise BoxError(reply["type"], reply["message"], session_alive=True,
                           **{key: reply[key] for key in ("traceback", "stdout", "stderr") if key in reply})
        return reply["result"]

    def checkpoint(self, session, timeout=60):
        record = session["record"]
        self.rpc(session, {"op": "save", "path": "scene.blend", "timeout": timeout})
        checkpoint_id = "chk_" + uuid.uuid4().hex[:16]
        target = self.root / "checkpoints" / checkpoint_id
        target.mkdir()
        workspace = Path(record["workspace"])
        try:
            shutil.copytree(workspace, target / "workspace", ignore=shutil.ignore_patterns(*INTERNAL),
                            symlinks=False)
            metadata = {"id": checkpoint_id, "source_session": record["id"], "created_at": time.time(),
                        "blender": record["blender"], "blender_version": record["blender_version"],
                        "blenderbox_version": __version__, "threads": record["threads"]}
            write_json(target / "checkpoint.json", metadata)
        except Exception:
            shutil.rmtree(target)
            raise
        record["last_checkpoint"] = checkpoint_id
        self.persist(session)
        return metadata

    def dispatch(self, request):
        op = request.get("op")
        timeout = float(request.get("timeout", 60))
        if not 0 < timeout <= 86400:
            raise BoxError("invalid_timeout", "timeout must be between 0 and 86400 seconds")
        if op == "ping":
            return {"pid": os.getpid(), "version": __version__, "home": str(self.root)}
        if op == "doctor":
            binary = self.binary()
            version = subprocess.run([binary, "--background", "--version"], capture_output=True,
                                     text=True, timeout=15, check=True).stdout.splitlines()[0]
            return {"version": __version__, "daemon_pid": os.getpid(), "blender": binary,
                    "blender_version": version, "home": str(self.root), "transport": "unix_socket"}
        if op == "create":
            return self.create(source=request.get("source"), blender=request.get("blender"),
                               timeout=timeout, threads=request.get("threads", 2))
        if op == "sessions":
            with self.registry_lock:
                sessions = list(self.sessions.values())
            records = []
            for session in sessions:
                if session["lock"].acquire(blocking=False):
                    try:
                        self.alive(session)
                        records.append(dict(session["record"]))
                    finally:
                        session["lock"].release()
                else:
                    records.append(dict(session["record"]))
            return records
        if op == "fork":
            source = request["source"]
            if not ID.fullmatch(source):
                raise BoxError("invalid_checkpoint", f"Invalid source: {source}")
            if source.startswith("bbx_"):
                session = self.lookup(source)
                with session["lock"]:
                    source = self.checkpoint(session, timeout)["id"]
            path = self.root / "checkpoints" / source
            if not (path / "checkpoint.json").is_file():
                raise BoxError("invalid_checkpoint", f"Unknown checkpoint: {source}")
            metadata = json.loads((path / "checkpoint.json").read_text())
            return self.create(blender=metadata["blender"], snapshot=path / "workspace", checkpoint=source,
                               threads=metadata["threads"], timeout=timeout)
        session = self.lookup(request.get("session"))
        if op == "close":
            if session["record"]["status"] == "creating":
                with session["lock"]:
                    return self.stop(session)
            return self.stop(session)
        if op == "status":
            if session["lock"].acquire(blocking=False):
                try:
                    self.alive(session)
                finally:
                    session["lock"].release()
            return dict(session["record"])
        with session["lock"]:
            workspace = Path(session["record"]["workspace"])
            if op == "checkpoint":
                return self.checkpoint(session, timeout)
            if op == "files":
                return [{"path": str(p.relative_to(workspace)), "size": p.stat().st_size}
                        for p in sorted(workspace.rglob("*")) if p.is_file() and
                        p.relative_to(workspace).parts[0] not in INTERNAL]
            if op in {"put", "get"}:
                path = workspace_path(workspace, request["path"])
                if op == "put":
                    source = Path(request["source"]).expanduser().resolve()
                    if not source.is_file():
                        raise BoxError("file_not_found", str(source))
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, path)
                else:
                    if not path.is_file():
                        raise BoxError("file_not_found", str(path))
                    if request.get("destination"):
                        destination = Path(request["destination"]).expanduser().resolve()
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(path, destination)
                        path = destination
                return {"path": str(path), "size": path.stat().st_size}
            if op == "import":
                source = Path(request["source"]).expanduser().resolve()
                if not source.is_file():
                    raise BoxError("file_not_found", str(source))
                asset_dir = workspace / "assets" / ("import_" + uuid.uuid4().hex[:8])
                resources = request.get("resources")
                if resources:
                    resources = Path(resources).expanduser().resolve()
                    if not resources.is_dir() or not source.is_relative_to(resources):
                        raise BoxError("invalid_resources", "--resources must be a directory containing the source")
                    if workspace.is_relative_to(resources):
                        raise BoxError("invalid_resources", "Resource directory cannot contain the session workspace")
                    shutil.copytree(resources, asset_dir,
                                    ignore=shutil.ignore_patterns(".git", ".venv", "node_modules"))
                    imported = asset_dir / source.relative_to(resources)
                else:
                    asset_dir.mkdir()
                    imported = asset_dir / source.name
                    shutil.copy2(source, imported)
                    if source.suffix.lower() == ".gltf":
                        data = json.loads(source.read_text())
                        for item in data.get("buffers", []) + data.get("images", []):
                            uri = item.get("uri", "")
                            if uri and not uri.startswith("data:"):
                                from urllib.parse import unquote
                                dependency = workspace_path(source.parent, unquote(uri))
                                target = workspace_path(asset_dir, unquote(uri))
                                target.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(dependency, target)
                request = {**request, "source": str(imported)}
            if op not in {"exec", "eval", "inspect", "preview", "render", "save", "import", "export"}:
                raise BoxError("unknown_command", str(op))
            return self.rpc(session, request)


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            self.request.settimeout(30)
            request = receive(self.request)
            self.request.settimeout(None)
            reply = response(self.server.manager.dispatch, request)
            send(self.request, reply)
        except (OSError, EOFError):
            pass


def main():
    os.umask(0o077)
    root = state_root()
    root.mkdir(parents=True, exist_ok=True)
    runtime = runtime_root(root)
    with (runtime / "daemon.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        path = runtime / "daemon.sock"
        path.unlink(missing_ok=True)
        with Server(str(path), Handler) as server:
            server.manager = Manager(root)
            write_json(root / "daemon.json", {"pid": os.getpid(), "endpoint": str(path), "version": __version__})
            try:
                server.serve_forever(poll_interval=.2)
            finally:
                path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
