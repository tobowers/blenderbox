import argparse
import json
import os
from pathlib import Path
import signal
import sys

from . import __version__
from .client import request, result
from .helptext import COMMANDS, OVERVIEW, QUICKSTART
from .protocol import BoxError
from .skills import install_skill, list_skills, show_skill


def parser():
    p = argparse.ArgumentParser(prog="blenderbox", description=OVERVIEW, epilog=QUICKSTART,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"blenderbox {__version__}")
    p.add_argument("--home", help="State directory (default: BLENDERBOX_HOME or ~/.local/share/blenderbox)")
    p.add_argument("--json", action="store_true", help="Return the full JSON response envelope")
    commands = p.add_subparsers(dest="op", required=True)

    def command(name, help, session=False):
        description, epilog = COMMANDS[name]
        c = commands.add_parser(name, help=help, description=description, epilog=epilog,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
        c.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        c.add_argument("--timeout", type=float, default=60, help="Execution deadline in seconds, excluding queue wait")
        if session:
            c.add_argument("session", help="Session ID returned by create")
        return c

    c = command("create", "Launch a new independent headless Blender process")
    c.add_argument("--from", dest="source", help="Load an existing .blend file")
    c.add_argument("--blender", help="Path to a Blender executable")
    c.add_argument("--threads", type=int, default=2, help="Blender render threads (default: 2)")
    command("sessions", "List all session records")
    command("status", "Inspect lifecycle, workspace, PID and logs", True)
    c = command("exec", "Run a Python file or stdin; globals persist", True)
    c.add_argument("script", nargs="?", default="-", help="Python file or - for stdin")
    c = command("eval", "Evaluate an expression and return JSON", True)
    c.add_argument("expression")
    c = command("inspect", "Return compact Blender state", True)
    c.add_argument("scope", nargs="?", default="scene",
                   choices=["scene", "objects", "object", "materials", "cameras", "lights", "collections", "render"])
    c.add_argument("name", nargs="?", help="Object name when scope is object")
    c = command("preview", "Render a framed neutral preview without changing the source scene", True)
    scope = c.add_mutually_exclusive_group()
    scope.add_argument("--object", help="Frame a named object in the active scene")
    scope.add_argument("--collection", help="Frame renderable objects in a named collection")
    c.add_argument("--view", default="perspective", choices=["perspective", "front", "back", "left", "right", "top", "bottom"], help="Camera direction (default: perspective)")
    c.add_argument("--resolution", type=int, default=512, help="Square PNG dimensions, 32..4096 (default: 512)")
    c.add_argument("--samples", type=int, default=16, help="CPU Cycles samples, 1..4096 (default: 16)")
    c.add_argument("--output", help="Workspace-relative PNG path (default: fresh renders/preview-*.png)")
    c = command("render", "Render the scene using its own settings", True)
    c.add_argument("--camera", help="Camera object in the active scene (default: scene camera)")
    c.add_argument("--output", default="renders/final.png", help="Workspace-relative PNG path (default: renders/final.png)")
    c = command("save", "Save a .blend file in the workspace", True)
    c.add_argument("--as", dest="path", default="scene.blend", help="Workspace-relative .blend path (default: scene.blend)")
    command("checkpoint", "Snapshot the scene and workspace assets", True)
    c = command("fork", "Create an independent session from a session or checkpoint")
    c.add_argument("source", help="Session ID (bbx_...) or checkpoint ID (chk_...)")
    c = command("put", "Copy a host file into the session workspace", True)
    c.add_argument("source", help="Host file to copy")
    c.add_argument("path", help="Workspace-relative destination")
    c = command("get", "Locate a session file or copy it to a host destination", True)
    c.add_argument("path", help="Workspace-relative file to locate or copy")
    c.add_argument("destination", nargs="?", help="Optional host file destination")
    command("files", "List workspace files", True)
    c = command("import", "Import GLB, glTF, OBJ, STL, PLY or FBX", True)
    c.add_argument("source", help="Host model file to copy and import")
    c.add_argument("--resources", help="Explicit asset directory to copy alongside the model")
    c = command("export", "Export scene geometry or a .blend", True)
    c.add_argument("--format", default="glb", choices=["glb", "gltf", "obj", "stl", "ply", "fbx", "blend"], help="Export format (default: glb)")
    c.add_argument("--output", help="Workspace-relative output path (default: exports/scene.FORMAT)")
    c.add_argument("--selected", action="store_true", help="Export selected geometry only (.blend remains a full copy)")
    command("close", "Terminate the session; saved files and logs remain", True)
    command("doctor", "Report Blender discovery and service health")
    c = command("daemon", "Start, inspect or stop the local supervisor")
    c.add_argument("action", choices=["start", "status", "stop"])
    c.add_argument("--close-sessions", action="store_true", help="Close sessions before stopping (otherwise they survive)")

    c = commands.add_parser("help", help="Read detailed help or the complete command reference",
                            description=COMMANDS["help"][0], epilog=COMMANDS["help"][1],
                            formatter_class=argparse.RawDescriptionHelpFormatter)
    c.add_argument("topic", nargs="*", help="Command path, e.g. exec or skills install")
    c.add_argument("--all", action="store_true", help="Print help for every command and nested subcommand")
    c = commands.add_parser("skills", help="Discover, read or install bundled agent skills",
                            description=COMMANDS["skills"][0], epilog=COMMANDS["skills"][1],
                            formatter_class=argparse.RawDescriptionHelpFormatter)
    c.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                   help="Return a JSON response envelope")
    skill_commands = c.add_subparsers(dest="skill_action", required=True)
    for action in ("list", "show", "install"):
        description, epilog = COMMANDS["skills " + action]
        child = skill_commands.add_parser(action, help=description.splitlines()[0], description=description,
                                         epilog=epilog, formatter_class=argparse.RawDescriptionHelpFormatter)
        child.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                           help="Return a JSON response envelope instead of plain content/results")
        if action != "list":
            child.add_argument("name", nargs="?", default="blenderbox", help="Bundled skill name (default: blenderbox)")
        if action == "show":
            child.add_argument("--file", default="SKILL.md", help="Bundled file to read (default: SKILL.md)")
        if action == "install":
            targets = child.add_mutually_exclusive_group()
            targets.add_argument("--agent", action="append", dest="agents", choices=["codex", "claude", "opencode", "shared", "all"], help="Agent destination; repeat for multiple clients (default: codex)")
            targets.add_argument("--path", help="Custom parent skill directory; skill name is appended")
            child.add_argument("--force", action="store_true", help="Replace a different existing skill directory, including local edits")
            child.add_argument("--dry-run", action="store_true", help="Report destinations/conflicts without writing any files")
    return p


def print_help(root, topic=None, all_commands=False):
    def children(node):
        for action in node._actions:
            if isinstance(action, argparse._SubParsersAction):
                return action.choices
        return {}
    node = root
    for part in topic or []:
        available = children(node)
        if part not in available:
            raise BoxError("unknown_help_topic", f"Unknown help topic: {' '.join(topic)}")
        node = available[part]
    node.print_help()
    if all_commands:
        def walk(parent):
            for name, child in children(parent).items():
                print("\n" + "=" * 72 + "\n" + child.prog + "\n" + "=" * 72)
                child.print_help()
                walk(child)
        walk(node)


def main():
    root_parser = parser()
    args = vars(root_parser.parse_args())
    full_json = args.pop("json")
    home = args.pop("home")
    if home:
        os.environ["BLENDERBOX_HOME"] = str(Path(home).expanduser().resolve())
    op = args.pop("op")
    try:
        if op == "help":
            print_help(root_parser, args["topic"], args["all"])
            return 0
        if op == "skills":
            action = args.pop("skill_action")
            value = (list_skills() if action == "list" else
                     show_skill(**args) if action == "show" else install_skill(**args))
            if action == "show" and not full_json:
                print(value["content"], end="" if value["content"].endswith("\n") else "\n")
            else:
                print(json.dumps({"status": "ok", "result": value} if full_json else value, indent=2))
            return 0
        if op == "exec":
            script = args.pop("script")
            args["code"] = sys.stdin.read() if script == "-" else Path(script).read_text()
        for key in ("source", "destination", "resources", "blender"):
            if args.get(key) and op != "fork":
                args[key] = str(Path(args[key]).expanduser().resolve())
        if op == "daemon":
            action = args.pop("action")
            close_sessions = args.pop("close_sessions")
            reply = request("ping")
            if action == "stop":
                if close_sessions:
                    for session in result("sessions"):
                        if session["status"] not in {"closed", "failed", "crashed", "timed_out"}:
                            result("close", session=session["id"])
                os.kill(reply["result"]["pid"], signal.SIGTERM)
                reply["result"]["status"] = "stopped"
        elif op == "doctor":
            reply = request("doctor", **args)
        else:
            reply = request(op, **args)
        if reply["status"] != "ok":
            print(json.dumps(reply, indent=2), file=sys.stderr)
            return 1
        value = reply["result"]
        if full_json:
            print(json.dumps(reply, indent=2))
        elif op in {"create", "fork", "checkpoint"}:
            print(value["id"])
        else:
            print(json.dumps(value, indent=2))
        return 0
    except (BoxError, OSError, ValueError) as exc:
        error = exc.error if isinstance(exc, BoxError) else {"type": "client_error", "message": str(exc)}
        print(json.dumps({"status": "error", **error}, indent=2), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(json.dumps({"status": "error", "type": "client_interrupted",
                          "message": "The submitted command may still be running; check session status"}), file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
