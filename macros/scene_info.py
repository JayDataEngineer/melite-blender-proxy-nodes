"""Macro: scene_info — the session scene as JSON (no pixels).

Executed INSIDE the Blender session. The CHEAP orient arm: before
spending a render, the loop asks what is even in the room — object
names, types, locations, sizes, the camera, the lights. Reads ARGS
(the prelude) and signals with a final
    print("MELITE_RESULT " + json.dumps(...))
line.

ARGS contract: none required. Optional:
  limit: int — max objects listed (default 64, the log stays small)
"""

import json

import bpy

limit = max(1, min(512, int((ARGS.get("limit") if isinstance(ARGS, dict) else None) or 64)))  # noqa: F821

items = []
for o in bpy.data.objects:
    if len(items) >= limit:
        break
    try:
        loc = [round(float(v), 4) for v in o.location]
        dims = [round(float(v), 4) for v in o.dimensions]
    except (TypeError, ValueError):
        loc, dims = [], []
    items.append({
        "name": o.name,
        "type": o.type,
        "location": loc,
        "dimensions": dims,
    })

cam = bpy.context.scene.camera
print("MELITE_RESULT " + json.dumps({
    "macro": "scene_info",
    "objects": len(bpy.data.objects),
    "listed": items,
    "truncated": len(bpy.data.objects) > limit,
    "camera": cam.name if cam is not None else None,
}))
