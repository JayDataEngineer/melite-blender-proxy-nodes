# melite-blender-proxy-nodes

Thin ComfyUI proxy: graphs drive headless Blender (`blender -b`) through
nodes, never through estate-side subprocesses.

## Requirement (host, never installed)

Blender must exist on the serving machine. Resolution order:

1. `SKINTOKEN_BLENDER_BIN` / `BLENDER_BIN` env (explicit path wins)
2. `blender` on `PATH`

Unresolvable = loud refusal at compose time (estate gate) and at prompt
time (node). This pack downloads nothing, bundles no binary, imports no
`bpy` wheel — `bpy` lives only in `scripts/` payloads executed by the
Blender binary itself.

## Nodes (`Melite/Blender`)

- **Melite Blender Run Script** — escape hatch: run any Blender Python
  script headless (`script_path` + JSON `script_args` + `timeout`).
  Existing lane scripts ride this unchanged until they earn dedicated
  nodes. Returns the run log tail.
- **Melite Blender Export (FBX/GLB)** — self-contained mesh export via
  the pack's own `scripts/export_mesh.py`. Mesh path in, file path out
  (under ComfyUI `output/blender_proxy/`).

## For lane authors

New Blender ops: first try expressing them as a payload script through
Run Script. A dedicated node earns its keep only when two or more
graphs share the exact invocation.
