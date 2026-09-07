"""Melite Blender proxy nodes for ComfyUI.

ComfyUI graphs drive headless Blender through THESE nodes — the estate
owns no Blender subprocess. Blender is a host requirement, never an
install: this pack contains no Blender build, downloads none, and
imports no bpy wheel.
"""
from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
