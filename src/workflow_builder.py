"""Workflow Builder — translates Intermediate Representation (IR) to ComfyUI native JSON."""

from __future__ import annotations

import logging
import random

logger = logging.getLogger(__name__)

# Seed must be >= 0 for ComfyUI's KSampler
# Treat -1 (or any negative) as "random seed"
def _resolve_seed(raw_seed) -> int:
    if raw_seed is None or raw_seed < 0:
        return random.randint(0, 2**31 - 1)
    return int(raw_seed)

# ── IR → ComfyUI node type mapping ─────────────────────────────────

# Node IDs for the standard txt2img pipeline
NodeIdx = int  # just for readability, not enforced


class WorkflowBuilder:
    """Builds ComfyUI workflow JSON from an IR dict."""

    def __init__(self, start_id: int = 1):
        self._next_id = start_id
        self.workflow: dict[str, dict] = {}

    def _alloc_id(self) -> str:
        nid = str(self._next_id)
        self._next_id += 1
        return nid

    def build(self, ir: dict) -> dict:
        """Build a ComfyUI workflow from an IR dict. Returns the workflow JSON."""
        self.workflow.clear()
        self._next_id = 1

        wf_type = ir.get("type", "txt2img")

        if wf_type == "txt2img":
            return self._build_txt2img(ir)
        elif wf_type == "img2img":
            return self._build_img2img(ir)
        else:
            raise ValueError(f"Unknown workflow type: {wf_type}")

    # ── txt2img ───────────────────────────────────────────────────

    def _build_txt2img(self, ir: dict) -> dict:
        checkpoint = ir["checkpoint"]
        positive = ir["positive_prompt"]
        negative = ir.get("negative_prompt", "")
        width = ir.get("width", 512)
        height = ir.get("height", 512)
        batch_size = ir.get("batch_size", 1)
        steps = ir.get("steps", 20)
        cfg = ir.get("cfg", 7.0)
        sampler = ir.get("sampler_name", "euler")
        scheduler = ir.get("scheduler", "normal")
        seed = _resolve_seed(ir.get("seed", -1))
        denoise = ir.get("denoise", 1.0)
        filename_prefix = ir.get("filename_prefix", "ComfyUI")

        # Node 1: LoadCheckpoint
        n_load = self._alloc_id()
        self.workflow[n_load] = {
            "inputs": {"ckpt_name": checkpoint},
            "class_type": "CheckpointLoaderSimple",
        }

        # Node 2: CLIPTextEncode (positive)
        n_pos = self._alloc_id()
        self.workflow[n_pos] = {
            "inputs": {"text": positive, "clip": [n_load, 1]},
            "class_type": "CLIPTextEncode",
        }

        # Node 3: CLIPTextEncode (negative)
        n_neg = self._alloc_id()
        self.workflow[n_neg] = {
            "inputs": {"text": negative, "clip": [n_load, 1]},
            "class_type": "CLIPTextEncode",
        }

        # Node 4: EmptyLatentImage
        n_latent = self._alloc_id()
        self.workflow[n_latent] = {
            "inputs": {"width": width, "height": height, "batch_size": batch_size},
            "class_type": "EmptyLatentImage",
        }

        # Node 5: KSampler
        n_sample = self._alloc_id()
        self.workflow[n_sample] = {
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler,
                "scheduler": scheduler,
                "denoise": denoise,
                "model": [n_load, 0],
                "positive": [n_pos, 0],
                "negative": [n_neg, 0],
                "latent_image": [n_latent, 0],
            },
            "class_type": "KSampler",
        }

        # Node 6: VAEDecode
        n_decode = self._alloc_id()
        self.workflow[n_decode] = {
            "inputs": {"samples": [n_sample, 0], "vae": [n_load, 2]},
            "class_type": "VAEDecode",
        }

        # Node 7: SaveImage (preview in UI) + PreviewImage
        n_save = self._alloc_id()
        self.workflow[n_save] = {
            "inputs": {"images": [n_decode, 0], "filename_prefix": filename_prefix},
            "class_type": "SaveImage",
        }

        return dict(self.workflow)

    # ── img2img ───────────────────────────────────────────────────

    def _build_img2img(self, ir: dict) -> dict:
        checkpoint = ir["checkpoint"]
        positive = ir["positive_prompt"]
        negative = ir.get("negative_prompt", "")
        input_image = ir.get("input_image", "")
        width = ir.get("width", 512)
        height = ir.get("height", 512)
        steps = ir.get("steps", 20)
        cfg = ir.get("cfg", 7.0)
        sampler = ir.get("sampler_name", "euler")
        scheduler = ir.get("scheduler", "normal")
        seed = _resolve_seed(ir.get("seed", -1))
        denoise = ir.get("denoise", 0.75)
        filename_prefix = ir.get("filename_prefix", "ComfyUI")

        # Node 1: LoadCheckpoint (img2img)
        n_load = self._alloc_id()
        self.workflow[n_load] = {
            "inputs": {"ckpt_name": checkpoint},
            "class_type": "CheckpointLoaderSimple",
        }

        # Node 2: CLIPTextEncode (positive)
        n_pos = self._alloc_id()
        self.workflow[n_pos] = {
            "inputs": {"text": positive, "clip": [n_load, 1]},
            "class_type": "CLIPTextEncode",
        }

        # Node 3: CLIPTextEncode (negative)
        n_neg = self._alloc_id()
        self.workflow[n_neg] = {
            "inputs": {"text": negative, "clip": [n_load, 1]},
            "class_type": "CLIPTextEncode",
        }

        # Node 4: LoadImage
        n_loader = self._alloc_id()
        self.workflow[n_loader] = {
            "inputs": {"image": input_image},
            "class_type": "LoadImage",
        }

        # Node 5: VAEEncode (encode loaded image to latent)
        n_encode = self._alloc_id()
        self.workflow[n_encode] = {
            "inputs": {"pixels": [n_loader, 0], "vae": [n_load, 2]},
            "class_type": "VAEEncode",
        }

        # Node 6: KSampler
        n_sample = self._alloc_id()
        self.workflow[n_sample] = {
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler,
                "scheduler": scheduler,
                "denoise": denoise,
                "model": [n_load, 0],
                "positive": [n_pos, 0],
                "negative": [n_neg, 0],
                "latent_image": [n_encode, 0],
            },
            "class_type": "KSampler",
        }

        # Node 7: VAEDecode
        n_decode = self._alloc_id()
        self.workflow[n_decode] = {
            "inputs": {"samples": [n_sample, 0], "vae": [n_load, 2]},
            "class_type": "VAEDecode",
        }

        # Node 8: SaveImage
        n_save = self._alloc_id()
        self.workflow[n_save] = {
            "inputs": {"images": [n_decode, 0], "filename_prefix": filename_prefix},
            "class_type": "SaveImage",
        }

        return dict(self.workflow)