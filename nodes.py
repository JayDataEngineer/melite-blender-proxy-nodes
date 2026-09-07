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

from .proxy import ENV_VARS, run_blender_script

_PACK_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.join(_PACK_DIR, "scripts")


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


NODE_CLASS_MAPPINGS = {
    "MeliteBlenderRunScript": MeliteBlenderRunScript,
    "MeliteBlenderExport": MeliteBlenderExport,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MeliteBlenderRunScript": "Melite Blender Run Script",
    "MeliteBlenderExport": "Melite Blender Export (FBX/GLB)",
}
