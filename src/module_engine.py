"""Module Engine — translates Pipeline IR steps into ComfyUI nodes with auto-wiring."""

from __future__ import annotations

import logging
import random
from typing import Any

logger = logging.getLogger(__name__)


def _resolve_seed(raw_seed) -> int:
    if raw_seed is None or raw_seed < 0:
        return random.randint(0, 2**31 - 1)
    return int(raw_seed)


class ModuleEngine:
    """Builds a ComfyUI workflow JSON from a Pipeline IR."""

    def __init__(self):
        self.workflow: dict[str, dict] = {}
        self._next_id = 1
        self._producers: dict[str, list] = {}

    def _alloc_id(self) -> str:
        nid = str(self._next_id)
        self._next_id += 1
        return nid

    def _add_node(self, class_type: str, inputs: dict) -> str:
        nid = self._alloc_id()
        self.workflow[nid] = {"inputs": inputs, "class_type": class_type}
        return nid

    def _find_producer(self, output_type: str) -> list | None:
        return self._producers.get(output_type)

    def _register_producer(self, output_type: str, node_id: str, slot: int):
        self._producers[output_type] = [node_id, slot]

    def build(self, ir: dict) -> dict:
        self.workflow.clear()
        self._next_id = 1
        self._producers.clear()

        meta = ir.get("meta", {})
        pipeline = ir.get("pipeline", [])

        if not pipeline:
            raise ValueError("Pipeline is empty")

        for step in pipeline:
            module_name = step.get("module", "")
            handler = getattr(self, f"_handle_{module_name}", None)
            if handler is None:
                raise ValueError(f"Unknown pipeline module: {module_name}")
            handler(step, meta)

        return dict(self.workflow)

    # ── load_checkpoint ───────────────────────────────────────────

    def _handle_load_checkpoint(self, step: dict, meta: dict):
        checkpoint = step.get("checkpoint", "")
        if not checkpoint:
            raise ValueError("load_checkpoint requires 'checkpoint' parameter")

        nid = self._add_node("CheckpointLoaderSimple", {"ckpt_name": checkpoint})
        self._register_producer("MODEL", nid, 0)
        self._register_producer("CLIP", nid, 1)
        self._register_producer("VAE", nid, 2)

    # ── lora ──────────────────────────────────────────────────────

    def _handle_lora(self, step: dict, meta: dict):
        lora_name = step.get("lora_name", "")
        if not lora_name:
            raise ValueError("lora requires 'lora_name' parameter")

        model_producer = self._find_producer("MODEL")
        clip_producer = self._find_producer("CLIP")
        if not model_producer or not clip_producer:
            raise ValueError("lora requires MODEL and CLIP from a preceding load_checkpoint")

        strength = step.get("strength", 1.0)
        nid = self._add_node("LoraLoader", {
            "model": model_producer,
            "clip": clip_producer,
            "lora_name": lora_name,
            "strength_model": strength,
            "strength_clip": strength,
        })
        self._register_producer("MODEL", nid, 0)
        self._register_producer("CLIP", nid, 1)

    # ── prompt_pos ────────────────────────────────────────────────

    def _handle_prompt_pos(self, step: dict, meta: dict):
        clip_producer = self._find_producer("CLIP")
        if not clip_producer:
            raise ValueError("prompt_pos requires CLIP from a preceding load_checkpoint")

        text = meta.get("positive_prompt", "")
        nid = self._add_node("CLIPTextEncode", {"text": text, "clip": clip_producer})
        self._register_producer("CONDITIONING_POSITIVE", nid, 0)

    # ── prompt_neg ────────────────────────────────────────────────

    def _handle_prompt_neg(self, step: dict, meta: dict):
        clip_producer = self._find_producer("CLIP")
        if not clip_producer:
            raise ValueError("prompt_neg requires CLIP from a preceding load_checkpoint")

        text = meta.get("negative_prompt", "")
        nid = self._add_node("CLIPTextEncode", {"text": text, "clip": clip_producer})
        self._register_producer("CONDITIONING_NEGATIVE", nid, 0)

    # ── empty_latent ──────────────────────────────────────────────

    def _handle_empty_latent(self, step: dict, meta: dict):
        width = meta.get("width", 512)
        height = meta.get("height", 512)
        batch_size = meta.get("batch_size", 1)
        nid = self._add_node("EmptyLatentImage", {
            "width": width,
            "height": height,
            "batch_size": batch_size,
        })
        self._register_producer("LATENT", nid, 0)

    # ── load_image ────────────────────────────────────────────────

    def _handle_load_image(self, step: dict, meta: dict):
        image = step.get("image", "")
        if not image:
            raise ValueError("load_image requires 'image' parameter")
        nid = self._add_node("LoadImage", {"image": image})
        self._register_producer("IMAGE", nid, 0)

    # ── vae_encode ────────────────────────────────────────────────

    def _handle_vae_encode(self, step: dict, meta: dict):
        image_producer = self._find_producer("IMAGE")
        vae_producer = self._find_producer("VAE")
        if not image_producer:
            raise ValueError("vae_encode requires IMAGE from a preceding load_image")
        if not vae_producer:
            raise ValueError("vae_encode requires VAE from a preceding load_checkpoint")

        nid = self._add_node("VAEEncode", {
            "pixels": image_producer,
            "vae": vae_producer,
        })
        self._register_producer("LATENT", nid, 0)

    # ── controlnet (composite: LoadImage + ControlNetLoader + ApplyControlNet) ──

    def _handle_controlnet(self, step: dict, meta: dict):
        image = step.get("image", "")
        control_net_name = step.get("control_net_name", "")
        if not image:
            raise ValueError("controlnet requires 'image' parameter")
        if not control_net_name:
            raise ValueError("controlnet requires 'control_net_name' parameter")

        pos_producer = self._find_producer("CONDITIONING_POSITIVE")
        neg_producer = self._find_producer("CONDITIONING_NEGATIVE")
        if not pos_producer or not neg_producer:
            raise ValueError("controlnet requires CONDITIONING from preceding prompt_pos/prompt_neg")

        img_nid = self._add_node("LoadImage", {"image": image})
        cn_nid = self._add_node("ControlNetLoader", {"control_net_name": control_net_name})

        apply_nid = self._add_node("ControlNetApplyAdvanced", {
            "positive": pos_producer,
            "negative": neg_producer,
            "control_net": [cn_nid, 0],
            "image": [img_nid, 0],
        })
        self._register_producer("CONDITIONING_POSITIVE", apply_nid, 0)
        self._register_producer("CONDITIONING_NEGATIVE", apply_nid, 1)

    # ── ksampler ──────────────────────────────────────────────────

    def _handle_ksampler(self, step: dict, meta: dict):
        model_producer = self._find_producer("MODEL")
        pos_producer = self._find_producer("CONDITIONING_POSITIVE")
        neg_producer = self._find_producer("CONDITIONING_NEGATIVE")
        latent_producer = self._find_producer("LATENT")

        if not model_producer:
            raise ValueError("ksampler requires MODEL from a preceding load_checkpoint")
        if not pos_producer:
            raise ValueError("ksampler requires CONDITIONING_POSITIVE from a preceding prompt_pos")
        if not neg_producer:
            raise ValueError("ksampler requires CONDITIONING_NEGATIVE from a preceding prompt_neg")
        if not latent_producer:
            raise ValueError("ksampler requires LATENT from a preceding empty_latent or vae_encode")

        seed = _resolve_seed(meta.get("seed", -1))
        steps = meta.get("steps", 20)
        cfg = meta.get("cfg", 7.0)
        sampler = meta.get("sampler_name", "euler")
        scheduler = meta.get("scheduler", "normal")
        denoise = meta.get("denoise", 1.0)

        nid = self._add_node("KSampler", {
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": sampler,
            "scheduler": scheduler,
            "denoise": denoise,
            "model": model_producer,
            "positive": pos_producer,
            "negative": neg_producer,
            "latent_image": latent_producer,
        })
        self._register_producer("LATENT", nid, 0)

    # ── vae_decode ────────────────────────────────────────────────

    def _handle_vae_decode(self, step: dict, meta: dict):
        latent_producer = self._find_producer("LATENT")
        vae_producer = self._find_producer("VAE")
        if not latent_producer:
            raise ValueError("vae_decode requires LATENT from a preceding ksampler")
        if not vae_producer:
            raise ValueError("vae_decode requires VAE from a preceding load_checkpoint")

        nid = self._add_node("VAEDecode", {
            "samples": latent_producer,
            "vae": vae_producer,
        })
        self._register_producer("IMAGE", nid, 0)

    # ── upscale (composite: UpscaleModelLoader + ImageUpscaleWithModel) ──

    def _handle_upscale(self, step: dict, meta: dict):
        upscale_model = step.get("upscale_model", "")
        if not upscale_model:
            raise ValueError("upscale requires 'upscale_model' parameter")

        image_producer = self._find_producer("IMAGE")
        if not image_producer:
            raise ValueError("upscale requires IMAGE from a preceding vae_decode")

        um_nid = self._add_node("UpscaleModelLoader", {"model_name": upscale_model})
        upscale_nid = self._add_node("ImageUpscaleWithModel", {
            "upscale_model": [um_nid, 0],
            "image": image_producer,
        })
        self._register_producer("IMAGE", upscale_nid, 0)

    # ── save_image ────────────────────────────────────────────────

    def _handle_save_image(self, step: dict, meta: dict):
        image_producer = self._find_producer("IMAGE")
        if not image_producer:
            raise ValueError("save_image requires IMAGE from a preceding vae_decode or upscale")

        filename_prefix = meta.get("filename_prefix", "ComfyUI")
        self._add_node("SaveImage", {
            "images": image_producer,
            "filename_prefix": filename_prefix,
        })

    # ── ip_adapter (composite: LoadImage + IPAdapterModelLoader + IPAdapterApply) ──

    def _handle_ip_adapter(self, step: dict, meta: dict):
        image = step.get("image", "")
        ipadapter_file = step.get("ipadapter_file", "")
        weight = step.get("weight", 1.0)

        if not image:
            raise ValueError("ip_adapter requires 'image' parameter")
        if not ipadapter_file:
            raise ValueError("ip_adapter requires 'ipadapter_file' parameter")

        model_producer = self._find_producer("MODEL")
        if not model_producer:
            raise ValueError("ip_adapter requires MODEL from a preceding load_checkpoint")

        img_nid = self._add_node("LoadImage", {"image": image})
        loader_nid = self._add_node("IPAdapterModelLoader", {"ipadapter_file": ipadapter_file})

        apply_nid = self._add_node("IPAdapterApply", {
            "ipadapter": [loader_nid, 0],
            "clip_vision": [loader_nid, 1],
            "image": [img_nid, 0],
            "model": model_producer,
            "weight": weight,
        })
        self._register_producer("MODEL", apply_nid, 0)
