"""Batch image generation tool — split a script prompt into multiple image sub-prompts and generate them in sequence."""

from __future__ import annotations

import logging
import time
from typing import Any

from src.comfyui_client import ComfyUIClient
from src.tools import workflow as workflow_mod
from src.tools import execution as execution_mod
from src.tools import images as images_mod

logger = logging.getLogger(__name__)

_DEFAULT_MAX_IMAGES = 10


def _split_script_prompt(script_prompt: str, delimiter: str) -> list[str]:
    """Split the script prompt into sub-prompts.

    Rules:
      * If the delimiter is explicitly provided and present, use it to split.
      * If delimiter is empty, split by blank lines.
      * Always strip whitespace; skip empty entries.
    """
    raw = script_prompt.strip()

    if delimiter and delimiter in raw:
        parts = raw.split(delimiter)
    else:
        # Split by blank lines (two or more consecutive newlines)
        import re

        parts = re.split(r"\n\s*\n+", raw)
        # If no blank line, fall back to single newlines
        if len(parts) == 1 and "\n" in parts[0]:
            parts = parts[0].splitlines()

    return [p.strip() for p in parts if p and p.strip()]


def batch_generate_images(
    script_prompt: str,
    delimiter: str = "---",
    checkpoint: str | None = None,
    common_prefix: str = "",
    common_suffix: str = "",
    negative_prompt: str = "",
    width: int = 1024,
    height: int = 1024,
    steps: int = 20,
    cfg: float = 7.0,
    seed: int = -1,
    sampler_name: str = "euler_ancestral",
    scheduler: str = "normal",
    max_images: int = _DEFAULT_MAX_IMAGES,
    max_wait_seconds: int = 300,
) -> dict[str, Any]:
    """Parse a script prompt into multiple sub-prompts and generate one image per sub-prompt.

    Args:
        script_prompt: Multi-image prompt text. Sub-prompts are split using the delimiter
                        (default ``---`` on its own line) or by blank lines.
        delimiter: String used to split the script prompt. Default ``---``.
                   If the delimiter is empty, blank-line splitting is used.
        checkpoint: ComfyUI checkpoint filename. If omitted, defaults to the first available checkpoint.
        common_prefix: Optional text prepended to every sub-prompt (e.g. ``"pixel art, "``).
        common_suffix: Optional text appended to every sub-prompt (e.g. ``", masterpiece"``).
        negative_prompt: Shared negative prompt (applied to all images).
        width: Image width in px. Default 1024.
        height: Image height in px. Default 1024.
        steps: Sampling steps. Default 20.
        cfg: CFG scale. Default 7.0.
        seed: Seed (-1 for random). Default -1.
        sampler_name: Sampler name. Default ``euler_ancestral``.
        scheduler: Scheduler name. Default ``normal``.
        max_images: Maximum number of images to generate. Default 10.
        max_wait_seconds: Maximum time in seconds to wait for any single image. Default 300.

    Returns:
        Dict with ``success``, ``total`` (number of sub-prompts found),
        and ``results`` — a list where each entry describes one generated image
        (keys: ``index``, ``prompt``, ``status``, ``prompt_id``, ``original_path``,
        ``thumbnail_base64``, or ``error`` on failure).
    """
    client = ComfyUIClient()

    # 1. Discover a default checkpoint if the user didn't provide one
    effective_checkpoint = checkpoint
    if not effective_checkpoint:
        from src.tools import models as models_mod

        logger.info("No checkpoint provided, probing available checkpoints")
        probe = models_mod.list_models(client, "checkpoints")
        cks = probe.get("checkpoints") or probe.get("models") or []
        if not cks:
            return {
                "success": False,
                "error": "No checkpoint selected and ComfyUI has no checkpoints available. "
                         "Please pass an explicit checkpoint name.",
                "error_code": "MISSING_CHECKPOINT",
            }
        effective_checkpoint = cks[0]
        logger.info("Auto-selected checkpoint: %s", effective_checkpoint)

    # 2. Split the script prompt
    if not script_prompt or not script_prompt.strip():
        return {
            "success": False,
            "error": "script_prompt is empty.",
            "error_code": "EMPTY_PROMPT",
        }

    sub_prompts = _split_script_prompt(script_prompt, delimiter)
    if not sub_prompts:
        return {
            "success": False,
            "error": "Could not parse any sub-prompts from script_prompt. "
                     "Use delimiter (e.g. ---) to separate image descriptions.",
            "error_code": "NO_SUB_PROMPTS",
        }

    if len(sub_prompts) > max_images:
        logger.info(
            "Found %d sub-prompts but max_images=%d; truncating.", len(sub_prompts), max_images
        )
        sub_prompts = sub_prompts[:max_images]

    results: list[dict] = []

    for idx, sub in enumerate(sub_prompts):
        positive = f"{common_prefix}{sub}{common_suffix}".strip()

        result_entry: dict[str, Any] = {"index": idx + 1, "prompt": positive, "status": "pending"}

        ir = {
            "type": "txt2img",
            "checkpoint": effective_checkpoint,
            "positive_prompt": positive,
            "negative_prompt": negative_prompt,
            "width": int(width),
            "height": int(height),
            "steps": int(steps),
            "cfg": float(cfg),
            "seed": int(seed),
            "sampler_name": sampler_name,
            "scheduler": scheduler,
            "batch_size": 1,
        }

        # Build workflow
        build_result = workflow_mod.build_workflow(ir)
        if not build_result.get("success"):
            result_entry["status"] = "failed"
            result_entry["error"] = build_result.get("error", "build failed")
            results.append(result_entry)
            continue

        # Execute
        exec_result = execution_mod.execute_workflow(client, "")
        if not exec_result.get("success"):
            result_entry["status"] = "failed"
            result_entry["error"] = exec_result.get("error", "execute failed")
            results.append(result_entry)
            continue

        prompt_id = exec_result.get("prompt_id")
        result_entry["prompt_id"] = prompt_id

        # Poll for completion
        logger.info("[%d/%d] executing prompt_id=%s ...", idx + 1, len(sub_prompts), prompt_id)
        start = time.time()
        status_result = None
        completed = False

        while time.time() - start < max_wait_seconds:
            time.sleep(5)
            status_result = execution_mod.get_execution_status(client, prompt_id)
            s = status_result.get("status")
            if s == "completed":
                completed = True
                break
            if s == "failed":
                break

        if not completed:
            result_entry["status"] = status_result.get("status", "timeout")
            result_entry["error"] = status_result.get("error", f"timed out after {max_wait_seconds}s")
            results.append(result_entry)
            continue

        result_entry["status"] = "completed"

        # Extract image
        outputs = status_result.get("outputs", {}) if status_result else {}
        image_found = False
        for node_id, node_output in outputs.items():
            if isinstance(node_output, dict) and node_output.get("images"):
                for img in node_output["images"]:
                    image_found = True
                    img_result = images_mod.get_generated_image(
                        client,
                        filename=img.get("filename", ""),
                        subfolder=img.get("subfolder", ""),
                        image_type=img.get("type", "output"),
                        thumbnail=True,
                    )
                    if img_result.get("success"):
                        result_entry["original_path"] = img_result.get("original_path", "")
                        result_entry["thumbnail_base64"] = img_result.get("thumbnail_base64", "")
                    else:
                        result_entry["error"] = img_result.get("error", "image download failed")
                    break
            if image_found:
                break

        if not image_found:
            result_entry["error"] = "no image output found for this prompt"

        results.append(result_entry)

    total_completed = sum(1 for r in results if r.get("status") == "completed")
    return {
        "success": True,
        "total": len(sub_prompts),
        "completed": total_completed,
        "failed": len(sub_prompts) - total_completed,
        "checkpoint": effective_checkpoint,
        "results": results,
    }
