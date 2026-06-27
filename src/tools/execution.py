"""MCP tools — execution, status, history, queue management."""

import asyncio
import os
import time
import logging
import uuid

from src.comfyui_client import ComfyUIClient, ComfyUIWebSocket, ComfyUIError
from src.context import get_context

logger = logging.getLogger(__name__)

POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "1"))
POLL_TIMEOUT = int(os.environ.get("POLL_TIMEOUT", "300"))


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


# ══════════════════════════════════════════════════════════════════════
# WebSocket real-time execution monitoring
# ══════════════════════════════════════════════════════════════════════

async def _watch_execution_ws(base_url: str, client_id: str, prompt_id: str) -> dict:
    """Watch execution via WebSocket. Returns final result dict.

    Yields progress events via the returned dict's 'events' list.
    Uses REST polling as fallback if WebSocket disconnects early.
    """
    ws = ComfyUIWebSocket(base_url)
    events = []
    result = {
        "success": True,
        "prompt_id": prompt_id,
        "status": "unknown",
        "outputs": {},
        "events": events,
    }

    try:
        async for event in ws.listen(client_id):
            etype = event["type"]
            data = event["data"]

            # Only track events for our prompt_id
            event_pid = data.get("prompt_id", "")
            if event_pid and event_pid != prompt_id:
                continue

            events.append({"type": etype, "data": data})

            if etype == "execution_start":
                result["status"] = "running"
                logger.info("[WS] execution_start: %s", prompt_id)

            elif etype == "executing":
                node = data.get("node")
                if node is None and data.get("prompt_id") == prompt_id:
                    # execution complete — fetch final result via REST
                    logger.info("[WS] executing (node=null): %s complete", prompt_id)
                    break
                else:
                    logger.debug("[WS] executing node: %s", node)

            elif etype == "progress":
                logger.debug("[WS] progress: %s/%s (node %s)",
                             data.get("value"), data.get("max"), data.get("node"))

            elif etype == "executed":
                logger.debug("[WS] executed node: %s", data.get("node"))

            elif etype == "execution_error":
                result["status"] = "failed"
                result["error"] = data.get("exception_message", "Unknown error")
                result["error_code"] = "EXECUTION_FAILED"
                logger.error("[WS] execution_error: %s", data.get("exception_message"))
                return result

            elif etype == "execution_interrupted":
                result["status"] = "failed"
                result["error"] = "Execution interrupted"
                result["error_code"] = "EXECUTION_FAILED"
                return result

    except Exception as e:
        logger.warning("WebSocket monitoring failed, falling back to REST polling: %s", e)
        # Fall through to REST polling below

    # Fetch final result via REST history
    client = ComfyUIClient(base_url)
    try:
        history = client.get_history_by_prompt_id(prompt_id)
    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)
        result["error_code"] = "COMFYUI_UNREACHABLE"
        return result

    if prompt_id in history:
        entry = history[prompt_id]
        status = entry.get("status", {})
        status_str = status.get("status_str", "completed")
        completed = status.get("completed", status_str == "success")
        result["status"] = "completed" if completed else "failed"
        result["outputs"] = entry.get("outputs", {})
        if not completed:
            result["error"] = "Execution failed"
            result["error_code"] = "EXECUTION_FAILED"
    else:
        result["status"] = "unknown"

    return result


def execute_and_watch(client: ComfyUIClient, client_id: str = "") -> dict:
    """Submit workflow and watch execution via WebSocket in real-time.

    This is the recommended execution method. It uses WebSocket for
    real-time progress events, with REST polling as automatic fallback.

    Returns the same format as get_execution_status() plus an 'events'
    list containing all WebSocket events received during execution.

    Args:
        client: ComfyUIClient instance.
        client_id: Optional client identifier for WebSocket.

    Returns:
        dict with success, prompt_id, status, outputs, events.
    """
    ctx = get_context()
    if ctx.current_workflow is None:
        return {
            "success": False,
            "error": "No workflow loaded. Use load_template or build_workflow first.",
            "error_code": "WORKFLOW_NOT_FOUND",
        }

    if not client_id:
        client_id = str(uuid.uuid4())

    # Submit
    try:
        prompt_id = client.submit_prompt(ctx.current_workflow, client_id=client_id)
    except ComfyUIError as e:
        return {"success": False, "error": str(e), "error_code": "COMFYUI_ERROR"}
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "COMFYUI_UNREACHABLE"}

    logger.info("Submitted prompt %s, watching via WebSocket (clientId=%s)", prompt_id, client_id)

    # Watch via WebSocket
    try:
        result = asyncio.run(_watch_execution_ws(client.base_url, client_id, prompt_id))
    except RuntimeError as e:
        # Already in an event loop (e.g. FastMCP's async context)
        logger.warning("Cannot run asyncio.run(), falling back to REST polling: %s", e)
        result = _poll_until_done(client, prompt_id)

    result["prompt_id"] = prompt_id
    return result


def _poll_until_done(client: ComfyUIClient, prompt_id: str) -> dict:
    """REST polling fallback — waits for execution to complete."""
    events = []
    deadline = time.time() + POLL_TIMEOUT

    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        status = get_execution_status(client, prompt_id)
        s = status.get("status", "unknown")
        events.append({"type": "poll", "status": s})
        if s in ("completed", "failed"):
            status["events"] = events
            return status

    return {
        "success": True,
        "prompt_id": prompt_id,
        "status": "timeout",
        "outputs": {},
        "events": events,
        "error": f"Execution timed out after {POLL_TIMEOUT}s",
        "error_code": "COMFYUI_TIMEOUT",
    }


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