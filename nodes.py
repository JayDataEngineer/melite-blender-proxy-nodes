"""Melite Blender proxy nodes: ComfyUI graphs drive headless Blender.

The estate owns no Blender subprocess — graphs call THESE nodes, and
these nodes shell `blender -b` (proxy.run_blender_script). Blender is a
host requirement (env SKINTOKEN_BLENDER_BIN / BLENDER_BIN, else PATH);
unresolvable = loud refusal before any render starts.

Only stdlib imports at module scope. bpy lives exclusively in
scripts/ payloads executed by the Blender binary, never in this
process. folder_paths (ComfyUI core) is imported lazily inside the
methods that need it, so the module stays importable off-server.
"""

from __future__ import annotations

import json
import os

from .mcp import ensure_session, run_macro
from .proxy import ENV_VARS, run_blender_script

_PACK_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.join(_PACK_DIR, "scripts")
_MACROS_DIR = os.path.join(_PACK_DIR, "macros")


def _macro_names() -> list[str]:
    try:
        return sorted(f[:-3] for f in os.listdir(_MACROS_DIR)
                      if f.endswith(".py") and not f.startswith("_"))
    except OSError:
        return []


def _macro_source(name: str) -> str:
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("MeliteBlenderMCPCall: bad macro name %r" % (name,))
    path = os.path.join(_MACROS_DIR, name + ".py")
    if not os.path.isfile(path):
        raise ValueError(
            "MeliteBlenderMCPCall: unknown macro %r — shipped: %s"
            % (name, ", ".join(_macro_names())))
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class MeliteBlenderRunScript:
    """Run any Blender Python script headless. The escape hatch: existing
    estate scripts (retarget, convert, validation renders) ride this node
    unchanged as payload paths until they earn dedicated nodes."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "script_path": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Absolute path to a Blender Python script "
                                   "(runs under blender -b --python).",
                    },
                ),
                "script_args": (
                    "STRING",
                    {
                        "default": "[]",
                        "multiline": True,
                        "tooltip": "JSON list of string args appended after "
                                   "'--' (reachable in-Blender via sys.argv).",
                    },
                ),
                "timeout": (
                    "INT",
                    {
                        "default": 600, "min": 60, "max": 3600, "step": 60,
                        "tooltip": "Seconds before the headless run is killed.",
                    },
                ),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("log",)
    FUNCTION = "run"
    CATEGORY = "Melite/Blender"

    def run(self, script_path, script_args, timeout):
        try:
            args = json.loads(script_args) if script_args.strip() else []
        except json.JSONDecodeError as exc:
            raise ValueError(
                "MeliteBlenderRunScript: script_args is not a JSON list: %s"
                % (exc,)) from exc
        if not isinstance(args, list):
            raise ValueError(
                "MeliteBlenderRunScript: script_args must be a JSON list, "
                "got %s" % (type(args).__name__,))
        log = run_blender_script(script_path, tuple(str(a) for a in args),
                                 timeout=int(timeout))
        return (log[-4000:],)


class MeliteBlenderExport:
    """Self-contained mesh export: mesh file in, FBX/GLB file out, via the
    pack's own scripts/export_mesh.py payload. Replaces bespoke
    `blender -b` export calls in lane packs."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mesh_path": (
                    "STRING",
                    {
                        "default": "",
                        "forceInput": True,
                        "tooltip": "Input mesh file (GLB/GLTF/FBX/OBJ/STL/PLY).",
                    },
                ),
                "format": (["FBX", "GLB"], {"default": "FBX"}),
                "output_filename": (
                    "STRING",
                    {
                        "default": "exported",
                        "tooltip": "Basename (no extension) under ComfyUI's "
                                   "output/blender_proxy dir.",
                    },
                ),
            },
            "optional": {
                "apply_transforms": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "Apply location/rotation/scale on export.",
                    },
                ),
                "include_animations": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "Bake/export animation actions when present.",
                    },
                ),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("exported_path",)
    FUNCTION = "export"
    CATEGORY = "Melite/Blender"
    OUTPUT_NODE = True

    def export(self, mesh_path, format, output_filename,
               apply_transforms=True, include_animations=True):
        import folder_paths  # ComfyUI core
        if not mesh_path or not os.path.isfile(mesh_path):
            raise FileNotFoundError(
                "MeliteBlenderExport: input mesh not found: %r" % (mesh_path,))
        out_dir = os.path.join(folder_paths.get_output_directory(),
                               "blender_proxy")
        os.makedirs(out_dir, exist_ok=True)
        base = os.path.basename(output_filename) or "exported"
        ext = ".fbx" if format == "FBX" else ".glb"
        out_path = os.path.join(out_dir, base + ext)
        run_blender_script(
            os.path.join(_SCRIPTS_DIR, "export_mesh.py"),
            (mesh_path, out_path, format,
             "1" if apply_transforms else "0",
             "1" if include_animations else "0"))
        return {"result": (out_path,)}


class MeliteBlenderMCPCall:
    """Run a NAMED macro in a PERSISTENT Blender session (MCP wire).

    One wire, two boot shapes (the card cannot tell them apart):
    the operator's interactive Blender + MCP add-on (HUMAN-SYNCED —
    live viewport while the graph drives the scene), or headless
    `blender -b --python mcp_listener_headless.py` (AI-DRIVEN).
    Macros are pack-shipped bpy payloads taking JSON args — the
    caller gets PARAMETERS, never arbitrary code (the raw-code
    escape hatch is MeliteBlenderRunScript, operator-scoped)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "macro": (_macro_names() or ["place_garment"],
                          {"default": "place_garment",
                           "tooltip": "Pack-shipped macro (macros/ dir)."}),
                "args": (
                    "STRING",
                    {
                        "default": "{}",
                        "multiline": True,
                        "tooltip": "JSON object of macro args (see the "
                                   "macro's docstring contract).",
                    },
                ),
                "timeout": (
                    "INT",
                    {
                        "default": 300, "min": 10, "max": 3600, "step": 10,
                        "tooltip": "Seconds for the session to answer.",
                    },
                ),
            },
            "optional": {
                "mcp_addr": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "host:port override (env "
                                   "MELITE_BLENDER_MCP_ADDR, else "
                                   "127.0.0.1:9876).",
                    },
                ),
                "autoboot": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "Boot a headless session when none is "
                                   "listening (the node owns the Blender "
                                   "process). False = human-synced session "
                                   "only, refuse if absent.",
                    },
                ),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("result_json",)
    FUNCTION = "call"
    CATEGORY = "Melite/Blender"
    OUTPUT_NODE = True

    def call(self, macro, args, timeout, mcp_addr="", autoboot=True):
        try:
            payload = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError as exc:
            raise ValueError(
                "MeliteBlenderMCPCall: args is not a JSON object: %s"
                % (exc,)) from exc
        if not isinstance(payload, dict):
            raise ValueError(
                "MeliteBlenderMCPCall: args must be a JSON object, got %s"
                % (type(payload).__name__,))
        ensure_session(str(mcp_addr or ""), bool(autoboot))
        result = run_macro(str(macro), _macro_source(str(macro)), payload,
                           knob_addr=str(mcp_addr or ""),
                           timeout=float(timeout))
        return (json.dumps(result)[:4000],)


class MeliteBlenderRenderShot:
    """Render the session scene to an IMAGE (the observe arm).

    The agentic loop's eyes: act-macros/nodes mutate the Blender
    session, THIS node photographs it — the IMAGE rides SaveImage
    into the run's artifacts (the gallery, the agent's eyes), and the
    loop decides the next act off pixels, not log text. The shot lands
    under ComfyUI's output/blender_proxy/<tag>.png (deterministic per
    run tag — the loop finds it by name), rendered by the pack-shipped
    render_shot macro in the PERSISTENT session (no cold boot per
    shot; a cold `blender -b` costs ~15s every iteration).

    Scene shape: a mesh path IMPORTS fresh (known state); empty keeps
    the CURRENT session scene (the iterative case — photograph what
    the acts just changed).
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "scene": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Mesh to photograph (GLB/GLTF/FBX/OBJ); "
                                   "empty = keep the current session scene.",
                    },
                ),
                "tag": (
                    "STRING",
                    {
                        "default": "shot",
                        "tooltip": "Shot basename under output/blender_proxy "
                                   "(the card stamps the run id here).",
                    },
                ),
                "width": (
                    "INT",
                    {
                        "default": 768, "min": 256, "max": 1536, "step": 64,
                        "tooltip": "Render width px.",
                    },
                ),
                "height": (
                    "INT",
                    {
                        "default": 768, "min": 256, "max": 1536, "step": 64,
                        "tooltip": "Render height px.",
                    },
                ),
                "timeout": (
                    "INT",
                    {
                        "default": 300, "min": 10, "max": 3600, "step": 10,
                        "tooltip": "Seconds for the session to answer.",
                    },
                ),
            },
            "optional": {
                "mcp_addr": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "host:port override (env "
                                   "MELITE_BLENDER_MCP_ADDR, else "
                                   "127.0.0.1:9876).",
                    },
                ),
                "autoboot": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "Boot a headless session when none is "
                                   "listening (the node owns the Blender "
                                   "process).",
                    },
                ),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("shot",)
    FUNCTION = "render"
    CATEGORY = "Melite/Blender"

    def render(self, scene, tag, width, height, timeout,
               mcp_addr="", autoboot=True):
        import folder_paths  # ComfyUI core
        import torch
        from PIL import Image
        import numpy as np
        scene = str(scene or "")
        if scene and not os.path.isfile(scene):
            raise FileNotFoundError(
                "MeliteBlenderRenderShot: scene not found: %s" % (scene,))
        base = "".join(c if (c.isalnum() or c in ("-", "_")) else "_"
                       for c in str(tag or "shot")) or "shot"
        out_dir = os.path.join(folder_paths.get_output_directory(),
                               "blender_proxy")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, base + ".png")
        ensure_session(str(mcp_addr or ""), bool(autoboot))
        result = run_macro("render_shot", _macro_source("render_shot"),
                           {"scene": scene, "out": out_path,
                            "width": int(width), "height": int(height)},
                           knob_addr=str(mcp_addr or ""),
                           timeout=float(timeout))
        # run_macro returns the MELITE_RESULT dict itself (mcp.py —
        # the listener envelope is already unwrapped there).
        shot = (result or {}).get("shot", "")
        if not shot or not os.path.isfile(shot):
            raise RuntimeError(
                "MeliteBlenderRenderShot: the session rendered nothing "
                "(macro result: %s)" % (json.dumps(result)[:500],))
        img = Image.open(shot).convert("RGB")
        arr = np.asarray(img, dtype=np.float32) / 255.0
        return (torch.from_numpy(arr)[None,],)


NODE_CLASS_MAPPINGS = {
    "MeliteBlenderRunScript": MeliteBlenderRunScript,
    "MeliteBlenderExport": MeliteBlenderExport,
    "MeliteBlenderMCPCall": MeliteBlenderMCPCall,
    "MeliteBlenderRenderShot": MeliteBlenderRenderShot,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MeliteBlenderRunScript": "Melite Blender Run Script",
    "MeliteBlenderExport": "Melite Blender Export (FBX/GLB)",
    "MeliteBlenderMCPCall": "Melite Blender MCP Call (session macro)",
    "MeliteBlenderRenderShot": "Melite Blender Render Shot (observe arm)",
}
