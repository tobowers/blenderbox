"""Private, length-framed local RPC. No MCP or TCP ports involved."""
import json
import socket
import struct
import time
import traceback
import uuid

MAX_FRAME = 64 * 1024 * 1024


class BoxError(Exception):
    def __init__(self, kind, message, **details):
        super().__init__(message)
        self.error = {"type": kind, "message": message, **details}


def receive(sock):
    def exact(n):
        chunks = bytearray()
        while len(chunks) < n:
            chunk = sock.recv(n - len(chunks))
            if not chunk:
                raise EOFError("RPC connection closed")
            chunks.extend(chunk)
        return chunks

    size = struct.unpack("!I", exact(4))[0]
    if size > MAX_FRAME:
        raise BoxError("request_too_large", "RPC messages are limited to 64 MiB")
    return json.loads(exact(size))


def send(sock, data):
    raw = json.dumps(data, allow_nan=False).encode()
    if len(raw) > MAX_FRAME:
        raise BoxError("request_too_large", "RPC messages are limited to 64 MiB")
    sock.sendall(struct.pack("!I", len(raw)) + raw)


def call(endpoint, request, timeout=60):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(str(endpoint))
        send(sock, request)
        return receive(sock)


def response(fn, request):
    start = time.monotonic()
    reply = {"request_id": request.get("request_id", "req_" + uuid.uuid4().hex[:12]),
             "status": "ok", "stdout": "", "stderr": ""}
    try:
        reply["result"] = fn(request)
    except BoxError as exc:
        reply.update(status="error", **exc.error)
    except Exception as exc:
        reply.update(status="error", type="internal_error", message=str(exc),
                     traceback=traceback.format_exc())
    reply["duration_ms"] = round((time.monotonic() - start) * 1000, 2)
    return reply
