"""Macro: render_shot — render the session scene to a PNG file.

Executed INSIDE the Blender session (headless listener or the
operator's interactive add-on). Reads ARGS from the prepended JSON
prelude (see mcp.run_macro) and signals its result with a final
    print("MELITE_RESULT " + json.dumps(...))
line.

THE OBSERVE ARM of the agentic loop: act-macros mutate the session
(place_garment, transforms), this macro photographs it — the PNG
rides back to the bench where eyes (agent or operator) read it and
the loop decides the next act. One shot per call; the LOOP iterates.

ARGS contract:
  out:    str  — absolute output PNG path (the caller owns it; the
                 RenderShot node derives it from ComfyUI's output
                 dir + the run tag, so every shot is deterministic)
  scene:  str | "" — mesh to photograph (GLB/GLTF/FBX/OBJ). Empty =
                 keep the CURRENT session scene (the iterative case:
                 photograph what the act-macros just changed).
  width:  int  — pixels (default 768, clamped 256–1536)
  height: int  — pixels (default 768, clamped 256–1536)
  lens:   float — camera focal length mm (default 50)

When a scene ships: the session resets to a known state (the pack's
session shape — clean + import, prior artifacts already exported as
files), a 3/4 camera frames the import, a sun lights it. EEVEE
(fast, headless-certain); the engine id walks Blender 3.x → 4.x.
"""

import json
import math
import os

import bpy
import mathutils

missing = [k for k in ("out",) if not ARGS.get(k)]  # noqa: F821
if missing:
    raise ValueError("render_shot: missing ARGS %s" % (missing,))

out = os.path.abspath(ARGS["out"])  # noqa: F821
os.makedirs(os.path.dirname(out), exist_ok=True)
width = max(256, min(1536, int(ARGS.get("width") or 768)))  # noqa: F821
height = max(256, min(1536, int(ARGS.get("height") or 768)))  # noqa: F821
lens = float(ARGS.get("lens") or 50.0)  # noqa: F821
scene_path = ARGS.get("scene") or ""  # noqa: F821

if scene_path:
    if not os.path.isfile(scene_path):
        raise FileNotFoundError("render_shot: scene %r is not a file"
                                % (scene_path,))
    # ── known state (the session shape) ──
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll, do_unlink=True)
    for item in list(bpy.data.objects):
        bpy.data.objects.remove(item, do_unlink=True)
    ext = os.path.splitext(scene_path)[1].lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=scene_path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=scene_path)
    elif ext == ".obj":
        bpy.ops.import_scene.obj(filepath=scene_path)
    else:
        raise ValueError("render_shot: scene format %r — GLB/GLTF/FBX/OBJ"
                         % (ext,))

meshes = [o for o in bpy.data.objects if o.type == "MESH"]
if not meshes:
    raise ValueError("render_shot: nothing to photograph — no MESH objects")

# ── frame: bounds center + radius drive the camera ──
low = [1e18, 1e18, 1e18]
high = [-1e18, -1e18, -1e18]
for o in meshes:
    for c in o.bound_box:
        w = o.matrix_world @ mathutils.Vector(c)  # noqa: F821
        for i in range(3):
            low[i] = min(low[i], w[i])
            high[i] = max(high[i], w[i])
center = [(low[i] + high[i]) / 2.0 for i in range(3)]
radius = max((high[i] - low[i]) for i in range(3)) / 2.0 or 1.0

cam_data = bpy.data.cameras.new("MeliteShotCam")
cam_data.lens = lens
cam_obj = bpy.data.objects.new("MeliteShotCam", cam_data)
bpy.context.scene.collection.objects.link(cam_obj)
# 3/4 view: out along +X+Y, up +Z, distance fits the radius with
# headroom (the loop reads the silhouette — never crop it).
dist = radius * 4.2
cam_obj.location = (center[0] + dist * 0.7,
                    center[1] - dist * 0.7,
                    center[2] + dist * 0.5)
track = cam_obj.constraints.new(type="TRACK_TO")
track.target = meshes[0]
track.track_axis = "TRACK_NEGATIVE_Z"
track.up_axis = "UP_Y"
bpy.context.scene.camera = cam_obj

sun_data = bpy.data.lights.new("MeliteShotSun", type="SUN")
sun_data.energy = 3.0
sun_obj = bpy.data.objects.new("MeliteShotSun", sun_data)
bpy.context.scene.collection.objects.link(sun_obj)
sun_obj.rotation_euler = (math.radians(50), 0, math.radians(30))

render = bpy.context.scene.render
render.resolution_x = width
render.resolution_y = height
render.resolution_percentage = 100
render.film_transparent = False
try:
    render.engine = "BLENDER_EEVEE_NEXT"  # 4.x
except TypeError:
    render.engine = "BLENDER_EEVEE"  # 3.x
eevee = bpy.context.scene.eevee
eevee.taa_render_samples = 16
render.image_settings.file_format = "PNG"
render.filepath = out
bpy.ops.render.render(write_still=True)

print("MELITE_RESULT " + json.dumps({
    "macro": "render_shot",
    "shot": out,
    "width": width,
    "height": height,
    "mesh_objects": len(meshes),
    "kept_session_scene": not bool(scene_path),
}))
