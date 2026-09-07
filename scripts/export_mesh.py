"""Payload script: import a mesh, export it. Runs INSIDE headless Blender.

Usage (never by hand — MeliteBlenderExport builds this argv):
    blender -b --python export_mesh.py -- <in> <out> <FBX|GLB> <apply±> <anim±>

Only bpy lives here. The ComfyUI side (nodes.py) never imports bpy.
"""

import sys

import bpy


def _argv():
    args = sys.argv
    if "--" in args:
        args = args[args.index("--") + 1:]
    if len(args) != 5:
        raise SystemExit(
            "export_mesh: expected 5 args <in> <out> <FBX|GLB> "
            "<apply 0|1> <anim 0|1>, got %r" % (args,))
    return args


in_path, out_path, fmt, apply, anim = _argv()
fmt = fmt.upper()
if fmt not in ("FBX", "GLB"):
    raise SystemExit("export_mesh: format must be FBX or GLB, got %r" % (fmt,))

bpy.ops.wm.read_factory_settings(use_empty=True)

lower = in_path.lower()
if lower.endswith(".glb") or lower.endswith(".gltf"):
    bpy.ops.import_scene.gltf(filepath=in_path)
elif lower.endswith(".fbx"):
    bpy.ops.import_scene.fbx(filepath=in_path)
elif lower.endswith(".obj"):
    bpy.ops.wm.obj_import(filepath=in_path)
elif lower.endswith(".stl"):
    bpy.ops.wm.stl_import(filepath=in_path)
elif lower.endswith(".ply"):
    bpy.ops.import_mesh.ply(filepath=in_path)
else:
    raise SystemExit("export_mesh: unsupported input %r" % (in_path,))

if apply == "1":
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

if fmt == "FBX":
    bpy.ops.export_scene.fbx(
        filepath=out_path, use_selection=False,
        bake_anim=anim == "1", bake_anim_use_all_bones=anim == "1",
        add_leaf_bones=False, apply_unit_scale=True)
else:
    bpy.ops.export_scene.gltf(
        filepath=out_path, export_format="GLB",
        export_animations=anim == "1")

print("export_mesh: wrote %s" % (out_path,))
