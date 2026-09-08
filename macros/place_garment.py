"""Macro: place_garment — clothing placement on a body (bpy 3.3).

Executed INSIDE the Blender session (headless listener or the
operator's interactive add-on). Reads ARGS from the prepended JSON
prelude (see mcp.run_macro) and signals its result with a final
    print("MELITE_RESULT " + json.dumps(...))
line.

ARGS contract:
  body:     str  — path to the body mesh (GLB/GLTF/FBX/OBJ)
  garment:  str  — path to the garment mesh (same formats)
  out:      str  — output GLB path (scene with body + placed garment)
  position: [x, y, z]        — world offset from the placement base
  rotation: [rx, ry, rz]     — degrees, applied to the garment
  scale:    float            — uniform garment scale (default 1.0)
  snap_to:  str | ""         — object/bone name to place RELATIVE to
                               (default: the body object root)
  mirror_x: bool             — mirror the garment across X (symmetry)

TRANSLATION-LEVEL placement only (snap + offset + rotate + scale +
mirror): no cloth sim, no collision solve — those are later macros
(the design record's risk line).
"""

import json
import math
import os

import bpy

missing = [k for k in ("body", "garment", "out") if not ARGS.get(k)]  # noqa: F821
if missing:
    raise ValueError("place_garment: missing ARGS %s" % (missing,))
for key in ("body", "garment"):
    if not os.path.isfile(ARGS[key]):  # noqa: F821
        raise FileNotFoundError("place_garment: %s %r is not a file"
                                % (key, ARGS[key]))

# ── clean scene (session shape: each macro starts from a known state;
#    prior artifacts were already exported as files) ──
for coll in list(bpy.data.collections):
    bpy.data.collections.remove(coll, do_unlink=True)
for item in list(bpy.data.objects):
    bpy.data.objects.remove(item, do_unlink=True)

before_garments = len(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=ARGS["body"])  # noqa: F821
body_objs = [o for o in bpy.data.objects if o.type == "MESH"]
if not body_objs:
    raise ValueError("place_garment: body import yielded no MESH objects")
body_root = body_objs[0]

bpy.ops.import_scene.gltf(filepath=ARGS["garment"])  # noqa: F821
garment_objs = [o for o in bpy.data.objects
                if o.type == "MESH" and o not in body_objs]
if not garment_objs:
    raise ValueError("place_garment: garment import yielded no MESH objects")

# ── placement base: named snap target (object first, then bone),
#    else the body root ──
base = None
snap = ARGS.get("snap_to") or ""  # noqa: F821
if snap:
    base = bpy.data.objects.get(snap)
    if base is None:
        for arm in (o for o in bpy.data.objects if o.type == "ARMATURE"):
            if snap in arm.pose.bones:
                bone = arm.pose.bones[snap]
                base = arm.matrix_world @ bone.matrix
                break
if base is None:
    base = body_root.matrix_world

pos = ARGS.get("position") or [0.0, 0.0, 0.0]  # noqa: F821
rot = ARGS.get("rotation") or [0.0, 0.0, 0.0]  # noqa: F821
scale = float(ARGS.get("scale") or 1.0)  # noqa: F821
mirror_x = bool(ARGS.get("mirror_x", False))  # noqa: F821

if hasattr(base, "to_quaternion"):  # a matrix (bone world matrix)
    base_loc = base.to_translation()
else:  # an object
    base_loc = base.to_translation()

for obj in garment_objs:
    obj.location = (
        base_loc.x + float(pos[0]),
        base_loc.y + float(pos[1]),
        base_loc.z + float(pos[2]),
    )
    obj.rotation_euler = (
        math.radians(float(rot[0])),
        math.radians(float(rot[1])),
        math.radians(float(rot[2])),
    )
    obj.scale = (scale, scale, scale)
    if mirror_x:
        obj.scale = (-scale, scale, scale)

out_dir = os.path.dirname(os.path.abspath(ARGS["out"]))  # noqa: F821
os.makedirs(out_dir, exist_ok=True)
bpy.ops.export_scene.gltf(
    filepath=ARGS["out"],  # noqa: F821
    export_format="GLB",
    use_selection=False,
    export_apply=True,
)

print("MELITE_RESULT " + json.dumps({
    "macro": "place_garment",
    "out": ARGS["out"],  # noqa: F821
    "body_objects": len(body_objs),
    "garment_objects": len(garment_objs),
    "placed_at": [round(v, 4) for v in obj.location],
    "scale": scale,
    "mirror_x": mirror_x,
    "snap_to": snap or body_root.name,
}))
