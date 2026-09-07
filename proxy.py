"""Shared headless-Blender plumbing: resolve the binary, run scripts.

LAW: this pack NEVER installs Blender — no downloads, no pip bpy
wheels, no bundled binary. (Foreign packs that auto-download a Blender
build into the repo, or pin the serving venv to a bpy wheel's Python,
are the exact coupling this pack exists to avoid.) The binary is a
HOST REQUIREMENT resolved as:

  1. SKINTOKEN_BLENDER_BIN / BLENDER_BIN env (explicit path wins)
  2. PATH lookup (shutil.which("blender"))

Unresolvable = loud RuntimeError naming the env vars and the binary.
The contract mirrors melite-autorig-nodes' _resolve_blender_binary so
the estate compose gate (SYSTEM_BINARY_REQUIRES) and the node name the
same need, one queue slot apart.
"""

from __future__ import annotations

import os
import shutil
import subprocess

ENV_VARS = ("SKINTOKEN_BLENDER_BIN", "BLENDER_BIN")
BINARY = "blender"


def resolve_blender_binary() -> str:
    """Return the Blender executable path, or raise loudly."""
    for var in ENV_VARS:
        candidate = os.environ.get(var)
        if candidate:
            if os.path.isfile(candidate):
                return candidate
            raise RuntimeError(
                "MeliteBlenderProxy: %s points at %r, which is not a "
                "file — fix the env var or unset it" % (var, candidate))
    discovered = shutil.which(BINARY)
    if discovered:
        return discovered
    raise RuntimeError(
        "MeliteBlenderProxy: Blender binary not found. Install Blender "
        "and put it on PATH, or set %s to the executable."
        % " or ".join(ENV_VARS))


def run_blender_script(script_path: str, args: tuple[str, ...] = (),
                       timeout: int = 600) -> str:
    """Run a Blender Python script headless; return combined stdout.

    Raises FileNotFoundError for a missing script (payload bug — fix
    the caller) and RuntimeError for a failed run (Blender's stderr
    tail rides the message so the queue ledger names the cause).
    """
    if not os.path.isfile(script_path):
        raise FileNotFoundError(
            "MeliteBlenderProxy: script not found: %s" % script_path)
    binary = resolve_blender_binary()
    cmd = [binary, "-b", "--python", script_path, "--",
           *(str(a) for a in args)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "MeliteBlenderProxy: blender -b timed out after %ds "
            "(script %s)" % (timeout, script_path)) from exc
    if proc.returncode != 0:
        raise RuntimeError(
            "MeliteBlenderProxy: blender -b failed (rc=%d, script %s):\n%s"
            % (proc.returncode, script_path,
               (proc.stderr or proc.stdout or "")[-2000:]))
    return proc.stdout or ""
