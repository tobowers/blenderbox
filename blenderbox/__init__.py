"""Python SDK for the same local service used by the blenderbox command."""
from .client import result
from .protocol import BoxError

__version__ = "0.2.1"
__all__ = ["Blender", "BoxError"]


class Blender:
    def __init__(self, session_id):
        self.id = session_id

    @classmethod
    def create(cls, source=None, blender=None, timeout=60, threads=2):
        return cls(result("create", source=source, blender=blender, timeout=timeout,
                          threads=threads)["id"])

    def _call(self, op, **params):
        return result(op, session=self.id, **params)

    def status(self):
        return self._call("status")

    def exec(self, code, timeout=60):
        return self._call("exec", code=code, timeout=timeout)

    def eval(self, expression, timeout=60):
        return self._call("eval", expression=expression, timeout=timeout)

    def inspect(self, scope="scene", name=None):
        return self._call("inspect", scope=scope, name=name)

    def preview(self, **options):
        return self._call("preview", **options)

    def render(self, output="renders/final.png", **options):
        return self._call("render", output=output, **options)

    def save(self, path="scene.blend"):
        return self._call("save", path=path)

    def checkpoint(self):
        return self._call("checkpoint")["id"]

    def fork(self):
        return Blender(result("fork", source=self.id)["id"])

    def put(self, source, destination):
        return self._call("put", source=str(source), path=destination)

    def get(self, path, destination=None):
        return self._call("get", path=path, destination=destination)

    def files(self):
        return self._call("files")

    def import_file(self, source, **options):
        return self._call("import", source=str(source), **options)

    def export(self, format="glb", output=None, **options):
        return self._call("export", format=format, output=output, **options)

    def close(self):
        return self._call("close")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
