"""MCP tools — node type definitions."""

from src.comfyui_client import ComfyUIClient


def get_node_types(client: ComfyUIClient) -> dict:
    """Get all node type definitions from ComfyUI."""
    info = client.get_object_info()
    return {"success": True, "node_types": info}