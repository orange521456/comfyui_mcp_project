"""MCP tools — model management."""

from src.comfyui_client import ComfyUIClient


def list_models(client: ComfyUIClient, model_type: str = "all") -> dict:
    """List available models in ComfyUI."""
    all_models = client.get_model_list()

    if model_type == "all":
        return {"success": True, **all_models}

    if model_type in all_models:
        return {"success": True, model_type: all_models[model_type]}
    else:
        return {
            "success": True,
            "model_type": model_type,
            "models": all_models.get(model_type, []),
        }