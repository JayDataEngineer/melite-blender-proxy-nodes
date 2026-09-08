"""Headless MCP session bootstrap — RUN INSIDE Blender.

Launched by the estate (never interactively): the pack's node/docs
line, or an operator shell line —

  blender -b --python mcp_listener_headless.py -- [port] [idle_timeout_s]

Boots a TCP listener speaking the pack's MCP wire (line-delimited
JSON: {"type": ..., "params": {...}} -> {"status", "result"/"error"}).
This file runs INSIDE the Blender binary, so `bpy` is importable;
everything else is stdlib. It is the AI-DRIVEN boot shape — the
HUMAN-SYNCED shape is the operator's interactive Blender with the
MCP add-on on the same wire. No UI, no host-config writes.

Serves until idle_timeout (default 1800s) passes with no commands or
the parent kills the process. One command per connection (the graph
reconnects per call — session STATE lives in the Blender scene, not
the socket).
"""

import json
import socket
import sys
import threading
import time

import bpy  # inside the Blender binary

HOST = "127.0.0.1"
IDLE_TIMEOUT_S = 1800.0
_EXEC_NS: dict = {"__name__": "melite_mcp_exec"}


def _handle(buf: bytes) -> bytes:
    try:
        req = json.loads(buf.decode("utf-8", "replace").strip())
        command = req.get("type", "")
        params = req.get("params", {}) or {}
        if command == "ping":
            resp = {"status": "success", "result": {"pong": True,
                                                    "blender": True}}
        elif command == "execute_code":
            code = params.get("code", "")
            if not isinstance(code, str) or not code.strip():
                raise ValueError("execute_code requires non-empty 'code'")
            import io
            from contextlib import redirect_stdout, redirect_stderr
            out = io.StringIO()
            with redirect_stdout(out), redirect_stderr(out):
                exec(compile(code, "<melite-macro>", "exec"), _EXEC_NS)  # noqa: S102 - macro payloads are pack-shipped, never caller-raw
            text = out.getvalue()
            # Macros signal their result with a final
            # print("MELITE_RESULT " + json.dumps(...)) line:
            melite = None
            for line in reversed(text.splitlines()):
                if line.startswith("MELITE_RESULT "):
                    melite = json.loads(line[len("MELITE_RESULT "):])
                    break
            resp = {"status": "success",
                    "result": {"melite_result": melite,
                               "stdout_tail": text[-2000:]}}
        else:
            raise ValueError("unknown command type %r" % (command,))
    except Exception as exc:  # noqa: BLE001 - refusal shape, not crash
        resp = {"status": "error", "error": "%s: %s"
                % (type(exc).__name__, exc)}
    return (json.dumps(resp) + "\n").encode("utf-8")


def main() -> None:
    port = 9876
    idle = IDLE_TIMEOUT_S
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) > 0 and argv[0].isdigit():
        port = int(argv[0])
    if len(argv) > 1 and argv[1].isdigit():
        idle = float(argv[1])
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, port))
    srv.listen(4)
    srv.settimeout(idle)
    print("MELITE_MCP_LISTENING %s:%d (idle %.0fs)"
          % (HOST, port, idle), flush=True)
    last = time.time()
    while time.time() - last < idle:
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            break
        conn.settimeout(600.0)
        try:
            chunks: list[bytes] = []
            while b"\n" not in b"".join(chunks):
                chunk = conn.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
            conn.sendall(_handle(b"".join(chunks)))
        except OSError:
            pass  # client died mid-command; session survives
        finally:
            conn.close()
        last = time.time()
    print("MELITE_MCP_IDLE_EXIT", flush=True)


main()
