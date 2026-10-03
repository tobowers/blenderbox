import fcntl
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from .protocol import BoxError, call

# Retain children so Popen does not warn when a long-lived daemon outlives
# the spawning SDK call. poll() also reaps daemons stopped during this process.
_daemon_children = []


def state_root():
    return Path(os.environ.get("BLENDERBOX_HOME", "~/.local/share/blenderbox")).expanduser().resolve()


def runtime_root(root=None):
    root = root or state_root()
    digest = hashlib.sha256(str(root).encode()).hexdigest()[:12]
    path = Path("/tmp") / f"blenderbox-{os.getuid()}-{digest}"
    path.mkdir(mode=0o700, exist_ok=True)
    if path.is_symlink() or path.stat().st_uid != os.getuid():
        raise BoxError("unsafe_runtime", f"Runtime directory is not owned by this user: {path}")
    path.chmod(0o700)
    return path


def endpoint():
    return runtime_root() / "daemon.sock"


def ensure_daemon():
    _daemon_children[:] = [p for p in _daemon_children if p.poll() is None]
    root = state_root()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (runtime_root() / "startup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            call(endpoint(), {"op": "ping"}, timeout=1)
            return
        except (OSError, EOFError):
            pass
        with (root / "daemon.log").open("ab") as log:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
            _daemon_children.append(subprocess.Popen(
                [sys.executable, "-m", "blenderbox.daemon"], env=env,
                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                start_new_session=True, close_fds=True))
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                call(endpoint(), {"op": "ping"}, timeout=1)
                return
            except (OSError, EOFError):
                time.sleep(.1)
        raise BoxError("daemon_startup", f"Daemon did not start; see {root / 'daemon.log'}")


def request(op, **params):
    for key in ("source", "destination", "resources", "blender"):
        if params.get(key) and op != "fork":
            params[key] = str(Path(params[key]).expanduser().resolve())
    ensure_daemon()
    timeout = float(params.get("timeout", 60))
    if timeout <= 0 or timeout > 86400:
        raise BoxError("invalid_timeout", "timeout must be between 0 and 86400 seconds")
    # Queue wait is separate from the execution deadline enforced by the daemon.
    try:
        reply = call(endpoint(), {"op": op, "request_id": "req_" + uuid.uuid4().hex[:12],
                                  **params}, timeout=None)
    except (OSError, EOFError) as exc:
        raise BoxError("daemon_connection", str(exc)) from exc
    return reply


def result(op, **params):
    reply = request(op, **params)
    if reply["status"] != "ok":
        raise BoxError(reply["type"], reply["message"],
                       **{k: v for k, v in reply.items() if k not in {"type", "message"}})
    return reply["result"]
