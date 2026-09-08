"""Melite Blender MCP session client: one wire, two boot shapes.

PERSISTENT-SESSION Blender calls for ComfyUI graphs (the proxy's
run_blender_script is the one-shot `blender -b` shape; this is the
session shape). The wire is line-delimited JSON over TCP:

  request : {"type": <str>, "params": {...}}\n
  response: {"status": "success"|"error", "result"=<any>}\n

Boot shapes (the card cannot tell them apart — same wire):
  a) HUMAN-SYNCED: the operator's interactive Blender running the
     MCP add-on (default 127.0.0.1:9876). The human watches/steers
     the live viewport while the graph drives the same scene.
  b) AI-DRIVEN headless: `blender -b --python
     mcp_listener_headless.py -- <port>` (pack bootstrap; no UI, no
     host-config writes).

Address resolution: MELITE_BLENDER_MCP_ADDR env (host:port) → the
node knob → default 127.0.0.1:9876. Unreachable = loud RuntimeError
naming the address and both boot shapes (the caller surfaces it as a
run failure naming the requirement — never a silent skip).

Only stdlib here; bpy lives exclusively in macros/ payloads executed
INSIDE the Blender session.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time

DEFAULT_ADDR = ("127.0.0.1", 9876)
ENV_ADDR = "MELITE_BLENDER_MCP_ADDR"
_RECV_BUF = 65536


def resolve_mcp_addr(knob_addr: str = "") -> tuple[str, int]:
    """Node knob wins, then env, then the default."""
    raw = (knob_addr or "").strip() or os.environ.get(ENV_ADDR, "")
    raw = raw.strip()
    if not raw:
        return DEFAULT_ADDR
    host, _, port = raw.rpartition(":")
    if not host or not port.isdigit():
        raise RuntimeError(
            "MeliteBlenderMCP: bad %s/MCP address %r — expected "
            "'host:port' (e.g. 127.0.0.1:9876)" % (ENV_ADDR, raw))
    return (host, int(port))


def _ping(knob_addr: str) -> bool:
    try:
        mcp_call({"type": "ping", "params": {}}, knob_addr=knob_addr,
                 timeout=10.0, connect_timeout=1.0)
        return True
    except RuntimeError:
        return False


def ensure_session(knob_addr: str = "", autoboot: bool = True,
                   boot_timeout: float = 90.0) -> None:
    """Guarantee a session exists at the resolved address.

    The HUMAN-SYNCED shape (operator's interactive Blender + MCP
    add-on) is already there — ping succeeds, nothing boots. The
    AI-DRIVEN shape boots headless when absent: THIS NODE owns the
    Blender process (LAW 0 — the node serves the requirement, the
    estate gateway never owns a subprocess): resolve the binary via
    proxy.resolve_blender_binary, spawn the pack's listener detached,
    wait for the port. autoboot=False refuses loud instead (for
    callers that want the human-synced session ONLY)."""
    if _ping(knob_addr):
        return
    if not autoboot:
        host, port = resolve_mcp_addr(knob_addr)
        raise RuntimeError(
            "MeliteBlenderMCP: no session at %s:%d and autoboot is off "
            "— start the interactive Blender MCP add-on session first"
            % (host, port))
    from .proxy import resolve_blender_binary  # local: keeps module scope stdlib
    binary = resolve_blender_binary()  # loud if the host lacks Blender
    host, port = resolve_mcp_addr(knob_addr)
    listener = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "mcp_listener_headless.py")
    proc = subprocess.Popen(  # detached; reaped by its own idle timeout
        [binary, "-b", "--python", listener, "--", str(port), "1800"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, start_new_session=True)
    deadline = time.time() + boot_timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                "MeliteBlenderMCP: headless listener exited rc=%s before "
                "listening on %s:%d (check the Blender binary / port)"
                % (proc.returncode, host, port))
        if _ping(knob_addr):
            return
        time.sleep(1.0)
    raise RuntimeError(
        "MeliteBlenderMCP: headless listener did not answer on %s:%d "
        "within %.0fs (binary %r)" % (host, port, boot_timeout, binary))


def mcp_call(command: dict, knob_addr: str = "", timeout: float = 300.0,
             connect_timeout: float = 5.0) -> dict:
    """One command over the session wire; returns the parsed response.

    Raises RuntimeError (loud, named) on connect failure, transport
    failure, protocol failure, or {"status": "error"} responses —
    the caller wraps these into node failures, never silent skips.
    """
    host, port = resolve_mcp_addr(knob_addr)
    try:
        with socket.create_connection((host, port),
                                      timeout=connect_timeout) as sock:
            sock.settimeout(timeout)
            payload = json.dumps({"type": str(command.get("type", "")),
                                  "params": command.get("params", {})})
            sock.sendall(payload.encode("utf-8") + b"\n")
            chunks: list[bytes] = []
            while True:
                chunk = sock.recv(_RECV_BUF)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\n" in chunk:
                    break
    except OSError as exc:
        raise RuntimeError(
            "MeliteBlenderMCP: no Blender session at %s:%d — start one "
            "(interactive Blender + the MCP add-on, or headless: "
            "blender -b --python mcp_listener_headless.py): %s"
            % (host, port, exc)) from exc
    wire = b"".join(chunks).decode("utf-8", "replace").strip()
    if not wire:
        raise RuntimeError(
            "MeliteBlenderMCP: session at %s:%d closed without a "
            "response (check the Blender-side console)" % (host, port))
    try:
        resp = json.loads(wire.splitlines()[-1])
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "MeliteBlenderMCP: unparseable response from %s:%d: %r"
            % (host, port, wire[:200])) from exc
    if not isinstance(resp, dict) or "status" not in resp:
        raise RuntimeError(
            "MeliteBlenderMCP: malformed response from %s:%d (no "
            "status): %r" % (host, port, wire[:200]))
    if resp.get("status") != "success":
        raise RuntimeError(
            "MeliteBlenderMCP: session refused the command: %s"
            % (resp.get("error", resp),))
    return resp


def run_macro(macro_name: str, macro_source: str, args: dict,
              knob_addr: str = "", timeout: float = 300.0) -> dict:
    """Execute a NAMED macro's source in the session with JSON args.

    The args ride as a JSON preamble line (ARGS = {...}) prepended to
    the macro source — the session executes one code payload and the
    macro's final MELITE_RESULT JSON line comes back as the response
    result (the listener wraps exec; the real add-on's execute_code
    returns the code's stdout tail, in which the MELITE_RESULT line
    is the last line — parsed identically here).
    """
    prelude = "ARGS = json.loads(%r)\n" % (json.dumps(args),)
    # json must be importable in the exec namespace on both shapes:
    prelude = "import json\n" + prelude
    code = prelude + macro_source
    resp = mcp_call({"type": "execute_code", "params": {"code": code}},
                    knob_addr=knob_addr, timeout=timeout)
    result = resp.get("result")
    # Headless listener returns the parsed MELITE_RESULT directly;
    # the real add-on returns a text tail — find the result line.
    if isinstance(result, dict) and "melite_result" in result:
        return result["melite_result"]
    if isinstance(result, str):
        for line in reversed(result.splitlines()):
            line = line.strip()
            if line.startswith("MELITE_RESULT "):
                try:
                    return json.loads(line[len("MELITE_RESULT "):])
                except json.JSONDecodeError:
                    break
    raise RuntimeError(
        "MeliteBlenderMCP: macro %r produced no MELITE_RESULT — raw "
        "result tail: %r" % (macro_name, str(result)[-400:]))
