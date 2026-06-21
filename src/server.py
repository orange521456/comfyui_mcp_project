"""MCP Server entry point — exposes ComfyUI as MCP tools and resources.

Usage:
    python src/server.py
"""

from __future__ import annotations

import logging
import os
import sys

# Ensure project root is on path when run directly as `python src/server.py`
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from mcp.server.fastmcp import FastMCP

from src.comfyui_client import ComfyUIClient
from src.context import get_context
from src.tools import models, nodes, workflow, execution, images, templates

# ── Logging setup ──────────────────────────────────────────────────

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_DIR = os.environ.get("LOG_DIR", "logs")
LOG_MAX_DAYS = int(os.environ.get("LOG_MAX_DAYS", "7"))

os.makedirs(LOG_DIR, exist_ok=True)

# Root logger
logger = logging.getLogger("src")
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

# stderr handler
stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setLevel(logging.DEBUG)
stderr_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logger.addHandler(stderr_handler)

# File handler (daily rotating)
from logging.handlers import TimedRotatingFileHandler

log_file = os.path.join(LOG_DIR, "mcp_server.log")
file_handler = TimedRotatingFileHandler(
    log_file, when="midnight", interval=1, backupCount=LOG_MAX_DAYS, encoding="utf-8"
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logger.addHandler(file_handler)

logger.info("Logging initialized: level=%s, dir=%s", LOG_LEVEL, LOG_DIR)

# ── ComfyUI client ─────────────────────────────────────────────────

COMFYUI_BASE_URL = os.environ.get("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
client = ComfyUIClient(COMFYUI_BASE_URL)

# ── MCP Server ─────────────────────────────────────────────────────

mcp = FastMCP(
    "comfyui-mcp",
    instructions="MCP Server for local ComfyUI service. Create workflows, generate images, manage models via natural language.",
)

# ── Startup check ──────────────────────────────────────────────────

logger.info("Checking ComfyUI at %s ...", COMFYUI_BASE_URL)
if client.check_health():
    logger.info("ComfyUI is reachable at %s", COMFYUI_BASE_URL)
else:
    logger.warning("ComfyUI is NOT reachable at %s — tools will return errors until it is available.", COMFYUI_BASE_URL)


# ╔══════════════════════════════════════════════════════════════════╗
# ║                         MODEL TOOLS                              ║
# ╚══════════════════════════════════════════════════════════════════╝

@mcp.tool()
def list_models(model_type: str = "all") -> dict:
    """List available models in ComfyUI.

    Args:
        model_type: Filter by type. Options: "checkpoints", "loras", "vaes", "upscalers", "controlnet", "clip", "all"
    """
    return models.list_models(client, model_type)


@mcp.tool()
def get_node_types() -> dict:
    """Get all node type definitions from ComfyUI. Returns the full object_info dictionary."""
    return nodes.get_node_types(client)


# ╔══════════════════════════════════════════════════════════════════╗
# ║                       WORKFLOW TOOLS                             ║
# ╚══════════════════════════════════════════════════════════════════╝

@mcp.tool()
def load_template(template_name: str, params: dict | None = None) -> dict:
    """Load a workflow template (builtin or user) and set it as the current workflow.

    Builtin templates: txt2img, img2img.
    User templates are loaded from the user_templates/ directory.

    Args:
        template_name: Name of the template (without .json extension).
        params: Optional parameter overrides dict. For builtin templates, keys include:
                checkpoint, positive_prompt, negative_prompt, width, height, steps, cfg,
                sampler_name, scheduler, seed, batch_size, denoise, input_image, filename_prefix.
    """
    return workflow.load_template(template_name, params)


@mcp.tool()
def list_templates() -> dict:
    """List all available templates (both builtin and user-defined)."""
    return workflow.list_templates()


@mcp.tool()
def build_workflow(ir: dict) -> dict:
    """Build a workflow from an Intermediate Representation (IR) dict.

    The IR format:
        {
            "type": "txt2img",          # required: "txt2img" or "img2img"
            "checkpoint": "model.safetensors",  # required
            "positive_prompt": "...",   # required
            "negative_prompt": "...",   # optional
            "width": 1024,              # optional, default 512
            "height": 1024,             # optional, default 512
            "steps": 20,                # optional
            "cfg": 7.0,                 # optional
            "sampler_name": "euler",    # optional
            "scheduler": "normal",      # optional
            "seed": 42,                 # optional, -1 for random
            "batch_size": 1,            # optional
            "denoise": 0.75,            # optional, mainly for img2img
            "input_image": "file.png",  # required for img2img
        }
    """
    return workflow.build_workflow(ir)


@mcp.tool()
def get_workflow() -> dict:
    """Get the current workflow's node list."""
    return workflow.get_workflow()


@mcp.tool()
def save_workflow(filepath: str, overwrite: bool = False) -> dict:
    """Save the current workflow to a JSON file.

    Args:
        filepath: Save path. Relative paths are saved to user_templates/.
        overwrite: Whether to overwrite if the file already exists.
    """
    return workflow.save_workflow(filepath, overwrite)


# ╔══════════════════════════════════════════════════════════════════╗
# ║                      EXECUTION TOOLS                             ║
# ╚══════════════════════════════════════════════════════════════════╝

@mcp.tool()
def execute_workflow(client_id: str = "") -> dict:
    """Submit the current workflow to ComfyUI for execution.

    Returns a prompt_id. Use get_execution_status(prompt_id) to track progress.

    Args:
        client_id: Optional client identifier for WebSocket (future use).
    """
    return execution.execute_workflow(client, client_id)


@mcp.tool()
def get_execution_status(prompt_id: str) -> dict:
    """Query the execution status of a specific prompt.

    Args:
        prompt_id: The prompt ID returned by execute_workflow.
    """
    return execution.get_execution_status(client, prompt_id)


@mcp.tool()
def get_execution_history(max_items: int = 10) -> dict:
    """Get recent execution history from ComfyUI.

    Args:
        max_items: Maximum number of history entries to return.
    """
    return execution.get_execution_history(client, max_items)


# ╔══════════════════════════════════════════════════════════════════╗
# ║                       QUEUE TOOLS                                ║
# ╚══════════════════════════════════════════════════════════════════╝

@mcp.tool()
def queue_clear() -> dict:
    """Clear all pending tasks from the ComfyUI execution queue."""
    return execution.queue_clear(client)


@mcp.tool()
def queue_cancel() -> dict:
    """Cancel the currently running task in ComfyUI."""
    return execution.queue_cancel(client)


@mcp.tool()
def queue_status() -> dict:
    """Get the current ComfyUI queue status (running and pending tasks)."""
    return execution.queue_status(client)


# ╔══════════════════════════════════════════════════════════════════╗
# ║                       IMAGE TOOLS                                ║
# ╚══════════════════════════════════════════════════════════════════╝

@mcp.tool()
def get_generated_image(
    filename: str,
    subfolder: str = "",
    image_type: str = "output",
    thumbnail: bool = True,
) -> dict:
    """Download a generated image from ComfyUI.

    Returns thumbnail_base64 (for preview) and original_path (local file path).

    Args:
        filename: Image filename, e.g. "ComfyUI_00001_.png"
        subfolder: Subfolder within the output directory.
        image_type: "output" or "temp".
        thumbnail: Whether to include a base64-encoded thumbnail in the response.
    """
    return images.get_generated_image(client, filename, subfolder, image_type, thumbnail)


@mcp.tool()
def upload_image(image_path: str, subfolder: str = "", overwrite: bool = False) -> dict:
    """Upload an image file to ComfyUI's input directory.

    Args:
        image_path: Local path to the image file.
        subfolder: Target subfolder in ComfyUI's input directory.
        overwrite: Whether to overwrite if a file with the same name exists.
    """
    return images.upload_image(client, image_path, subfolder, overwrite)


# ╔══════════════════════════════════════════════════════════════════╗
# ║                     ATOMIC OPERATIONS                            ║
# ╚══════════════════════════════════════════════════════════════════╝

@mcp.tool()
def create_node(node_type: str, params: dict | None = None, title: str | None = None) -> dict:
    """Create a new node in the current workflow.

    Args:
        node_type: ComfyUI node class type, e.g. "KSampler", "LoadCheckpoint", "CLIPTextEncode".
        params: Initial parameters for the node.
        title: Optional display title for the node.
    """
    return templates.create_node(node_type, params, title)


@mcp.tool()
def update_node(node_id: str, params: dict) -> dict:
    """Update parameters of an existing node in the current workflow.

    Args:
        node_id: The node ID (as shown in get_workflow).
        params: Dict of parameters to update, e.g. {"steps": 30, "cfg": 8.5}.
    """
    return templates.update_node(node_id, params)


@mcp.tool()
def remove_node(node_id: str) -> dict:
    """Remove a node from the current workflow.

    Args:
        node_id: The node ID to remove.
    """
    return templates.remove_node(node_id)


@mcp.tool()
def connect_nodes(
    from_node_id: str,
    from_slot: int,
    to_node_id: str,
    to_slot: int,
    to_input_name: str,
) -> dict:
    """Connect two nodes by linking an output slot to an input slot.

    Args:
        from_node_id: Source node ID.
        from_slot: Output slot index on the source node.
        to_node_id: Target node ID.
        to_slot: Input slot index on the target node.
        to_input_name: Name of the input parameter on the target node (e.g. "model", "positive", "latent_image").
    """
    return templates.connect_nodes(from_node_id, from_slot, to_node_id, to_slot, to_input_name)


@mcp.tool()
def disconnect_nodes(node_id: str, input_name: str) -> dict:
    """Disconnect a specific input of a node.

    Args:
        node_id: The node ID.
        input_name: The name of the input to disconnect (e.g. "model", "latent_image").
    """
    return templates.disconnect_nodes(node_id, input_name)


# ╔══════════════════════════════════════════════════════════════════╗
# ║                     MCP RESOURCES                                ║
# ╚══════════════════════════════════════════════════════════════════╝

@mcp.resource("comfyui://system_info")
def system_info_resource() -> str:
    """ComfyUI system information."""
    import json
    try:
        stats = client.get_system_stats()
        return json.dumps(stats, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.resource("comfyui://models/checkpoints")
def checkpoints_resource() -> str:
    """Available checkpoint models."""
    import json
    data = models.list_models(client, "checkpoints")
    return json.dumps(data.get("checkpoints", data.get("models", [])), indent=2)


@mcp.resource("comfyui://models/loras")
def loras_resource() -> str:
    """Available LoRA models."""
    import json
    data = models.list_models(client, "loras")
    return json.dumps(data.get("loras", data.get("models", [])), indent=2)


@mcp.resource("comfyui://models/vaes")
def vaes_resource() -> str:
    """Available VAE models."""
    import json
    data = models.list_models(client, "vaes")
    return json.dumps(data.get("vaes", data.get("models", [])), indent=2)


@mcp.resource("comfyui://models/upscalers")
def upscalers_resource() -> str:
    """Available upscaler models."""
    import json
    data = models.list_models(client, "upscalers")
    return json.dumps(data.get("upscalers", data.get("models", [])), indent=2)


@mcp.resource("comfyui://models/controlnet")
def controlnet_resource() -> str:
    """Available ControlNet models."""
    import json
    data = models.list_models(client, "controlnet")
    return json.dumps(data.get("controlnet", data.get("models", [])), indent=2)


@mcp.resource("comfyui://node_types")
def node_types_resource() -> str:
    """All node type definitions."""
    import json
    try:
        info = client.get_object_info()
        return json.dumps(info, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Entry point ─────────────────────────────────────────────────────

def main():
    """Start the MCP server."""
    logger.info("Starting comfyui-mcp server...")
    mcp.run()


if __name__ == "__main__":
    main()