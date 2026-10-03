# Blenderbox development

Blenderbox replaces the Blender MCP dependency with a local CLI/SDK and private Unix-socket supervisor. Use the installed `blenderbox` command for Blender work. Each task gets its own headless process; Blender operations belong on the bootstrap main thread. Do not introduce the old MCP protocol or Blender add-on as a dependency.

Run `python3 -m unittest discover -s tests -v` after changes to RPC, session lifecycle, Blender operations or persistence. These are real Blender integration tests with an isolated supervisor; close only the sessions created by the current task. Reinstall with `python3 scripts/install.py` after package changes, then restart the supervisor to load its new implementation (live sessions keep their existing bootstrap until recreated).
