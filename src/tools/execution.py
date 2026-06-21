"""MCP tools — execution, status, history, queue management."""

import time
import logging

from src.comfyui_client import ComfyUIClient, ComfyUIError
from src.context import get_context

logger = logging.getLogger(__name__)


def execute_workflow(client: ComfyUIClient, client_id: str = "") -> dict:
    """Submit the current workflow to ComfyUI for execution."""
    ctx = get_context()
    if ctx.current_workflow is None:
        return {
            "success": False,
            "error": "No workflow loaded. Use load_template or build_workflow first.",
            "error_code": "WORKFLOW_NOT_FOUND",
        }

    try:
        prompt_id = client.submit_prompt(ctx.current_workflow, client_id=client_id)
        return {
            "success": True,
            "prompt_id": prompt_id,
            "message": "Workflow submitted successfully. Use get_execution_status to track progress.",
        }
    except ComfyUIError as e:
        return {"success": False, "error": str(e), "error_code": "COMFYUI_ERROR"}
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "COMFYUI_UNREACHABLE"}


def get_execution_status(client: ComfyUIClient, prompt_id: str) -> dict:
    """Query the execution status of a specific prompt."""
    try:
        history = client.get_history_by_prompt_id(prompt_id)
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "COMFYUI_UNREACHABLE"}

    if prompt_id in history:
        entry = history[prompt_id]
        status = entry.get("status", {})
        status_str = status.get("status_str", "completed")
        completed = status.get("completed", status_str == "success")
        return {
            "success": True,
            "prompt_id": prompt_id,
            "status": "completed" if completed else "failed",
            "outputs": entry.get("outputs", {}),
            "messages": status.get("messages", []),
        }
    else:
        # Not in history yet — still running or pending
        try:
            queue = client.get_queue()
            running = queue.get("queue_running", [])
            pending = queue.get("queue_pending", [])

            for item in running:
                if item[1] == prompt_id:
                    return {"success": True, "prompt_id": prompt_id, "status": "running"}
            for item in pending:
                if item[1] == prompt_id:
                    return {"success": True, "prompt_id": prompt_id, "status": "pending"}
        except Exception:
            pass

        return {"success": True, "prompt_id": prompt_id, "status": "unknown"}


def get_execution_history(client: ComfyUIClient, max_items: int = 10) -> dict:
    """Get recent execution history."""
    try:
        history = client.get_history(max_items=max_items)
        items = []
        for prompt_id, entry in history.items():
            outputs = entry.get("outputs", {})
            items.append({
                "prompt_id": prompt_id,
                "outputs": outputs,
            })
        return {"success": True, "history": items}
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "COMFYUI_UNREACHABLE"}


def queue_clear(client: ComfyUIClient) -> dict:
    """Clear the ComfyUI execution queue."""
    try:
        result = client.clear_queue()
        return {"success": True, "cleared": True}
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "COMFYUI_UNREACHABLE"}


def queue_cancel(client: ComfyUIClient) -> dict:
    """Cancel the currently running task."""
    try:
        client.cancel_current()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "COMFYUI_UNREACHABLE"}


def queue_status(client: ComfyUIClient) -> dict:
    """Get current queue status."""
    try:
        queue = client.get_queue()
        return {
            "success": True,
            "queue_running": queue.get("queue_running", []),
            "queue_pending": queue.get("queue_pending", []),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "COMFYUI_UNREACHABLE"}