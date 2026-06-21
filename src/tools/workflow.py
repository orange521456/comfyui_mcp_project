"""MCP tools — workflow management (load, build, get, save)."""

import json
import os
import re
from typing import Any

from src.context import get_context
from src.workflow_builder import WorkflowBuilder

BUILTIN_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
USER_TEMPLATES_DIR = os.environ.get("USER_TEMPLATES_DIR", "user_templates")

# Make sure user_templates is an absolute path
if not os.path.isabs(USER_TEMPLATES_DIR):
    USER_TEMPLATES_DIR = os.path.abspath(USER_TEMPLATES_DIR)

# Default template params
DEFAULT_PARAMS = {
    "checkpoint": "",
    "positive_prompt": "",
    "negative_prompt": "",
    "width": 512,
    "height": 512,
    "batch_size": 1,
    "steps": 20,
    "cfg": 7.0,
    "sampler_name": "euler",
    "scheduler": "normal",
    "seed": -1,
    "denoise": 1.0,
    "input_image": "",
    "filename_prefix": "ComfyUI",
}


def _find_template(name: str) -> str | None:
    """Find a template file by name. Returns the file path or None."""
    # Check builtin first
    builtin = os.path.join(BUILTIN_TEMPLATES_DIR, f"{name}.json")
    if os.path.isfile(builtin):
        return builtin
    # Check user templates
    user = os.path.join(USER_TEMPLATES_DIR, f"{name}.json")
    if os.path.isfile(user):
        return user
    return None


def _resolve_template(workflow: dict, params: dict) -> dict:
    """Replace {{placeholders}} in a workflow dict with actual values."""
    merged = {**DEFAULT_PARAMS, **params}
    workflow_str = json.dumps(workflow)
    for key, value in merged.items():
        workflow_str = workflow_str.replace(f'"{{{{{key}}}}}"', json.dumps(value))
    return json.loads(workflow_str)


def load_template(template_name: str, params: dict | None = None) -> dict:
    """Load a workflow template and apply parameters."""
    params = params or {}
    filepath = _find_template(template_name)
    if not filepath:
        return {
            "success": False,
            "error": f"Template not found: {template_name}",
            "error_code": "TEMPLATE_NOT_FOUND",
        }

    with open(filepath, "r", encoding="utf-8") as f:
        template = json.load(f)

    # Check if it's a builtin template (has placeholders)
    raw = json.dumps(template)
    is_builtin = "{{" in raw

    if is_builtin:
        workflow = _resolve_template(template, params)
        applied = params
    else:
        # User template: just load it, params are ignored
        workflow = template
        applied = {}

    get_context().set_workflow(workflow)
    return {
        "success": True,
        "template_name": template_name,
        "node_count": len(workflow),
        "applied_params": applied,
    }


def list_templates() -> dict:
    """List all available templates."""
    builtin = []
    if os.path.isdir(BUILTIN_TEMPLATES_DIR):
        for fname in os.listdir(BUILTIN_TEMPLATES_DIR):
            if fname.endswith(".json"):
                builtin.append({"name": fname[:-5]})

    user = []
    if os.path.isdir(USER_TEMPLATES_DIR):
        for fname in os.listdir(USER_TEMPLATES_DIR):
            if fname.endswith(".json"):
                user.append({"name": fname[:-5], "path": os.path.join(USER_TEMPLATES_DIR, fname)})

    return {"success": True, "builtin": builtin, "user": user}


def build_workflow(ir: dict) -> dict:
    """Build a workflow from an Intermediate Representation (IR)."""
    try:
        builder = WorkflowBuilder()
        workflow = builder.build(ir)
        get_context().set_workflow(workflow, ir=ir)
        return {
            "success": True,
            "node_count": len(workflow),
        }
    except ValueError as e:
        return {"success": False, "error": str(e), "error_code": "INVALID_PARAM"}
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "INTERNAL_ERROR"}


def get_workflow() -> dict:
    """Get the current workflow JSON."""
    ctx = get_context()
    if ctx.current_workflow is None:
        return {
            "success": False,
            "error": "No workflow loaded. Use load_template or build_workflow first.",
            "error_code": "WORKFLOW_NOT_FOUND",
        }

    nodes = []
    for nid, node in ctx.current_workflow.items():
        nodes.append({
            "id": nid,
            "type": node.get("class_type", "Unknown"),
            "title": node.get("_meta", {}).get("title", node.get("class_type", "")),
        })

    return {
        "success": True,
        "node_count": len(ctx.current_workflow),
        "nodes": nodes,
    }


def save_workflow(filepath: str, overwrite: bool = False) -> dict:
    """Save the current workflow to a file."""
    ctx = get_context()
    if ctx.current_workflow is None:
        return {
            "success": False,
            "error": "No workflow to save.",
            "error_code": "WORKFLOW_NOT_FOUND",
        }

    if not os.path.isabs(filepath):
        filepath = os.path.join(USER_TEMPLATES_DIR, filepath)

    if not filepath.endswith(".json"):
        filepath += ".json"

    if os.path.exists(filepath) and not overwrite:
        return {
            "success": False,
            "error": f"File exists: {filepath}. Set overwrite=true to overwrite.",
            "error_code": "INVALID_PARAM",
        }

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(ctx.current_workflow, f, indent=2)

    return {"success": True, "filepath": filepath}