"""Official-MCP stdio face — RUN INSIDE Blender (the dsh-mcp-client boot).

  blender -b --python mcp_server.py

Speaks the Model Context Protocol over stdio (newline-delimited
JSON-RPC 2.0) so a standard MCP client — the estate's lane via
@deepseek-ai/dsh-mcp-client (transport: stdio, command: blender,
args: ["-b", "--python", <this file>]) — connects and its tools
appear as mcp__blender__<tool>. This is the SAME session machinery
as the pack's TCP wire (mcp_listener_headless.py): the macro
contract (ARGS prelude in, a final MELITE_RESULT JSON line out)
and the exec namespace are shared — one implementation, two boots.

STDOUT LAW: a stdio MCP server's stdout carries ONLY protocol
frames. Blender itself (banner, render progress "Fra:" lines,
module prints) writes to fd 1 — so at boot this script dups fd 1
to a private protocol fd and re-points fd 1 at fd 2: every
non-protocol byte lands on stderr where the MCP client ignores
it, while protocol frames ride the private fd.

Tools (the control arm; vision never rides bespoke — ImageContent
is opt-in per call for image-capable routes, and every render also
lands a file the estate views through its own observe arm):

  execute_code {code}        — pack-trusted python, macro contract
  run_macro   {macro, args}  — a macros/<name>.py payload (allowlist)
  scene_info  {limit?}       — the cheap JSON orient
  render_shot {out, width?, height?, lens?, scene?, image?}
                             — deterministic PNG at `out`; image=true
                               ALSO returns ImageContent (base64 PNG)

Serves until idle_timeout (default 1800s, the listener's law)
passes with no requests or the parent kills the process; the MCP
client owns connect/reconnect (this side only exits).
"""

import base64
import io
import json
import os
import sys
import time
from contextlib import redirect_stderr, redirect_stdout

import bpy  # inside the Blender binary

IDLE_TIMEOUT_S = 1800.0
PROTOCOL_VERSION_ECHO = True  # respond with the client's version
SERVER_INFO = {"name": "melite-blender", "version": "0.1.0"}

_EXEC_NS: dict = {"__name__": "melite_mcp_exec"}
_MACROS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "macros")

# The protocol fd (stdout duped BEFORE fd 1 is re-pointed at fd 2).
_PROTOCOL_FD = os.dup(1)
os.dup2(2, 1)  # blender's own stdout noise -> stderr, forever


def _send(obj: dict) -> None:
    os.write(_PROTOCOL_FD, (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8"))


def _result(req_id, result: dict) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error(req_id, code: int, message: str) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


# ── the shared exec engine (the listener's law, one implementation) ──

def _exec_engine(code: str) -> dict:
    """Run pack-trusted python under the macro contract: a final
    print("MELITE_RESULT " + json) line carries the result; stdout
    tail rides along for diagnosis. Refusals raise (the caller
    shapes them into isError)."""
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(out):
        exec(compile(code, "<melite-macro>", "exec"), _EXEC_NS)  # noqa: S102 - pack-shipped payloads, never caller-raw
    text = out.getvalue()
    melite = None
    for line in reversed(text.splitlines()):
        if line.startswith("MELITE_RESULT "):
            melite = json.loads(line[len("MELITE_RESULT "):])
            break
    return {"melite_result": melite, "stdout_tail": text[-2000:]}


def _macro_source(name: str) -> str:
    """The macros/ allowlist: one name, one pack file — never a
    caller-chosen path."""
    if not isinstance(name, str) or not name or "/" in name or "\\" in name or name in (".", ".."):
        raise ValueError("run_macro: macro must be a pack macros/ name")
    path = os.path.join(_MACROS_DIR, name + ".py")
    if not os.path.isfile(path):
        raise ValueError("run_macro: no such macro %r (allowlist: %s)"
                         % (name, sorted(os.listdir(_MACROS_DIR))))
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _run_macro(name: str, args: dict) -> dict:
    prelude = "import json\nARGS = json.loads(%r)\n" % (json.dumps(args or {}),)
    return _exec_engine(prelude + _macro_source(name))


# ── tool descriptors (the client's model-facing surface) ──

_TOOLS = [
    {
        "name": "execute_code",
        "description": "Run pack-trusted python inside the live Blender session "
                       "(macro contract: a final print('MELITE_RESULT ' + json) line "
                       "carries the structured result; the stdout tail returns too).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python source to exec"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "run_macro",
        "description": "Run one of the pack's macros/ payloads by name with JSON args "
                       "(ARGS prelude in, MELITE_RESULT out).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "macro": {"type": "string", "description": "macros/ name (e.g. render_shot)"},
                "args": {"type": "object", "description": "JSON args for the macro"},
            },
            "required": ["macro"],
        },
    },
    {
        "name": "scene_info",
        "description": "The session scene as JSON — object names, types, locations, "
                       "sizes, camera, lights. The cheap orient before any render.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "max objects listed (default 64)"},
            },
        },
    },
    {
        "name": "render_shot",
        "description": "Deterministic 3/4 camera render to a PNG at `out` (absolute "
                       "path, caller-owned). image=true ALSO returns the PNG inline as "
                       "ImageContent (for image-capable model routes).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "out": {"type": "string", "description": "absolute output PNG path"},
                "width": {"type": "integer", "description": "pixels (default 768, clamped 256-1536)"},
                "height": {"type": "integer", "description": "pixels (default 768, clamped 256-1536)"},
                "lens": {"type": "number", "description": "camera lens mm (default 50)"},
                "scene": {"type": "string", "description": "optional .blend scene path to import first"},
                "image": {"type": "boolean", "description": "also return ImageContent (default false)"},
            },
            "required": ["out"],
        },
    },
]


def _tool_call(name: str, args: dict) -> dict:
    """One tools/call. Returns the MCP result object (content,
    isError). Refusals are isError results, never protocol errors."""
    try:
        if name == "execute_code":
            code = args.get("code")
            if not isinstance(code, str) or not code.strip():
                raise ValueError("execute_code requires non-empty 'code'")
            payload = _exec_mELITE(code)
            return {"content": [{"type": "text", "text": json.dumps(payload)}]}
        if name == "run_macro":
            payload = _run_macro(args.get("macro"), args.get("args") or {})
            return {"content": [{"type": "text", "text": json.dumps(payload)}]}
        if name == "scene_info":
            payload = _run_macro("scene_info", {"limit": args.get("limit")})
            return {"content": [{"type": "text", "text": json.dumps(payload)}]}
        if name == "render_shot":
            out = args.get("out")
            if not isinstance(out, str) or not out.strip():
                raise ValueError("render_shot requires 'out' (absolute PNG path)")
            macro_args = {"out": out}
            for key in ("width", "height", "lens", "scene"):
                if args.get(key) is not None:
                    macro_args[key] = args[key]
            payload = _run_macro("render_shot", macro_args)
            content = [{"type": "text", "text": json.dumps(payload)}]
            if args.get("image") is True:
                with open(out, "rb") as fh:
                    content.append({
                        "type": "image",
                        "mimeType": "image/png",
                        "data": base64.b64encode(fh.read()).decode("ascii"),
                    })
            return {"content": content}
        raise ValueError("unknown tool %r" % (name,))
    except Exception as exc:  # noqa: BLE001 - refusal shape, not crash
        return {"content": [{"type": "text",
                             "text": "%s: %s" % (type(exc).__name__, exc)}],
                "isError": True}


def _handle(req: dict) -> None:
    """One protocol frame. Requests answered; notifications silent."""
    req_id = req.get("id")
    method = req.get("method", "")
    if req_id is None:
        return  # a notification (initialized / cancelled) — no response
    if method == "initialize":
        client_version = (req.get("params") or {}).get("protocolVersion")
        _result(req_id, {
            "protocolVersion": client_version if PROTOCOL_VERSION_ECHO and client_version else "2025-06-18",
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
    elif method == "ping":
        _result(req_id, {})
    elif method == "tools/list":
        _result(req_id, {"tools": _TOOLS})
    elif method == "tools/call":
        params = req.get("params") or {}
        _result(req_id, _tool_call(params.get("name", ""), params.get("arguments") or {}))
    else:
        _error(req_id, -32601, "method not found: %r" % (method,))


def main() -> None:
    """The serve loop: poll stdin with a timeout so the idle-reap
    law (the listener's 1800s) actually fires between frames; EOF
    (parent gone) exits at once."""
    import select

    last = time.monotonic()
    while True:
        if time.monotonic() - last > IDLE_TIMEOUT_S:
            return
        ready, _, _ = select.select([sys.stdin], [], [], 1.0)
        if not ready:
            continue
        line = sys.stdin.readline()
        if line == "":
            return  # EOF — the parent closed the pipe
        last = time.monotonic()
        line = line.strip()
        if not line:
            continue
        try:
            frame = json.loads(line)
        except ValueError:
            continue  # a corrupt frame dies silently; the protocol carries ids
        if isinstance(frame, dict):
            _handle(frame)


if __name__ == "__main__":
    main()
