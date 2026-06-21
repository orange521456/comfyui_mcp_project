"""MCP tools — template management (atomic operations on workflow graph)."""

from src.context import get_context


def create_node(node_type: str, params: dict | None = None, title: str | None = None) -> dict:
    """Create a new node in the current workflow."""
    ctx = get_context()
    if ctx.current_workflow is None:
        return {
            "success": False,
            "error": "No workflow loaded.",
            "error_code": "WORKFLOW_NOT_FOUND",
        }

    node_id = ctx.get_next_id()
    node = {"inputs": params or {}, "class_type": node_type}
    if title:
        node["_meta"] = {"title": title}
    ctx.current_workflow[node_id] = node

    return {"success": True, "node_id": node_id, "node_type": node_type}


def update_node(node_id: str, params: dict) -> dict:
    """Update parameters of an existing node."""
    ctx = get_context()
    if ctx.current_workflow is None:
        return {
            "success": False,
            "error": "No workflow loaded.",
            "error_code": "WORKFLOW_NOT_FOUND",
        }

    if node_id not in ctx.current_workflow:
        return {
            "success": False,
            "error": f"Node not found: {node_id}",
            "error_code": "INVALID_PARAM",
        }

    ctx.current_workflow[node_id]["inputs"].update(params)
    return {"success": True, "node_id": node_id, "updated_params": params}


def remove_node(node_id: str) -> dict:
    """Remove a node from the current workflow."""
    ctx = get_context()
    if ctx.current_workflow is None:
        return {
            "success": False,
            "error": "No workflow loaded.",
            "error_code": "WORKFLOW_NOT_FOUND",
        }

    if node_id not in ctx.current_workflow:
        return {
            "success": False,
            "error": f"Node not found: {node_id}",
            "error_code": "INVALID_PARAM",
        }

    del ctx.current_workflow[node_id]
    return {"success": True, "node_id": node_id}


def connect_nodes(
    from_node_id: str,
    from_slot: int,
    to_node_id: str,
    to_slot: int,
    to_input_name: str,
) -> dict:
    """Connect two nodes by linking from_node output to to_node input."""
    ctx = get_context()
    if ctx.current_workflow is None:
        return {
            "success": False,
            "error": "No workflow loaded.",
            "error_code": "WORKFLOW_NOT_FOUND",
        }

    if from_node_id not in ctx.current_workflow:
        return {"success": False, "error": f"Source node not found: {from_node_id}", "error_code": "INVALID_PARAM"}
    if to_node_id not in ctx.current_workflow:
        return {"success": False, "error": f"Target node not found: {to_node_id}", "error_code": "INVALID_PARAM"}

    ctx.current_workflow[to_node_id]["inputs"][to_input_name] = [from_node_id, from_slot]
    return {"success": True, "link": {"from": [from_node_id, from_slot], "to": [to_node_id, to_input_name]}}


def disconnect_nodes(node_id: str, input_name: str) -> dict:
    """Disconnect a specific input of a node."""
    ctx = get_context()
    if ctx.current_workflow is None:
        return {
            "success": False,
            "error": "No workflow loaded.",
            "error_code": "WORKFLOW_NOT_FOUND",
        }

    if node_id not in ctx.current_workflow:
        return {"success": False, "error": f"Node not found: {node_id}", "error_code": "INVALID_PARAM"}

    if input_name in ctx.current_workflow[node_id]["inputs"]:
        ctx.current_workflow[node_id]["inputs"][input_name] = None

    return {"success": True, "node_id": node_id, "input_name": input_name}