"""ComfyUI REST API client — encapsulates all HTTP communication."""

import asyncio
import json
import httpx
import logging
import os
import uuid
from typing import Any, AsyncIterator

import websockets
import websockets.asyncio.client

logger = logging.getLogger(__name__)


class ComfyUIClient:
    """HTTP client for ComfyUI's REST API."""

    def __init__(self, base_url: str = "http://127.0.0.1:8188"):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=30)

    # ── health check ──────────────────────────────────────────────

    def check_health(self) -> bool:
        """Check if ComfyUI is reachable. Returns True/False."""
        try:
            r = self._client.get(f"{self.base_url}/system_stats")
            return r.status_code == 200
        except Exception:
            return False

    def get_system_stats(self) -> dict:
        """GET /system_stats — returns system info."""
        r = self._client.get(f"{self.base_url}/system_stats")
        r.raise_for_status()
        return r.json()

    # ── node types / object info ──────────────────────────────────

    def get_object_info(self) -> dict:
        """GET /object_info — returns all node type definitions."""
        r = self._client.get(f"{self.base_url}/object_info")
        r.raise_for_status()
        return r.json()

    # ── queue ─────────────────────────────────────────────────────

    def get_queue(self) -> dict:
        """GET /queue — returns current queue status."""
        r = self._client.get(f"{self.base_url}/queue")
        r.raise_for_status()
        return r.json()

    def clear_queue(self) -> dict:
        """POST /queue with {"clear": true} — clears the queue."""
        r = self._client.post(f"{self.base_url}/queue", json={"clear": True})
        r.raise_for_status()
        return r.json()

    def cancel_current(self) -> None:
        """POST /interrupt — cancels the currently running task."""
        r = self._client.post(f"{self.base_url}/interrupt")
        r.raise_for_status()

    # ── prompt execution ──────────────────────────────────────────

    def submit_prompt(self, workflow: dict, client_id: str = "") -> str:
        """POST /prompt — submit workflow for execution. Returns prompt_id."""
        payload = {"prompt": workflow}
        if client_id:
            payload["client_id"] = client_id
        r = self._client.post(f"{self.base_url}/prompt", json=payload)
        r.raise_for_status()
        data = r.json()
        if "prompt_id" not in data:
            raise ComfyUIError("No prompt_id in response", data)
        return data["prompt_id"]

    def get_history(self, max_items: int = 10) -> dict:
        """GET /history?max_items=N — returns execution history."""
        r = self._client.get(f"{self.base_url}/history", params={"max_items": max_items})
        r.raise_for_status()
        return r.json()

    def get_history_by_prompt_id(self, prompt_id: str) -> dict:
        """GET /history/{prompt_id} — returns specific execution history."""
        r = self._client.get(f"{self.base_url}/history/{prompt_id}")
        r.raise_for_status()
        return r.json()

    # ── images ────────────────────────────────────────────────────

    def get_image(self, filename: str, subfolder: str = "", image_type: str = "output") -> bytes:
        """GET /view — download generated image."""
        params = {"filename": filename, "type": image_type}
        if subfolder:
            params["subfolder"] = subfolder
        r = self._client.get(f"{self.base_url}/view", params=params)
        r.raise_for_status()
        return r.content

    def upload_image(self, filepath: str, subfolder: str = "", overwrite: bool = False) -> dict:
        """POST /upload/image — upload an image to ComfyUI's input directory."""
        filename = os.path.basename(filepath)
        with open(filepath, "rb") as f:
            files = {"image": (filename, f, "image/png")}
            data = {"overwrite": str(overwrite).lower()}
            if subfolder:
                data["subfolder"] = subfolder
            r = self._client.post(f"{self.base_url}/upload/image", files=files, data=data)
        r.raise_for_status()
        return r.json()

    # ── models ────────────────────────────────────────────────────

    def get_model_list(self) -> dict[str, list[dict]]:
        """Extract model lists from /object_info node definitions.

        Returns a dict keyed by model type:
        {"checkpoints": [...], "loras": [...], "vaes": [...]}
        """
        info = self.get_object_info()
        result: dict[str, list[dict]] = {}

        # Checkpoints from CheckpointLoaderSimple
        if "CheckpointLoaderSimple" in info:
            ckpt_input = info["CheckpointLoaderSimple"]["input"]["required"].get("ckpt_name", None)
            if ckpt_input and isinstance(ckpt_input, list) and len(ckpt_input) > 0 and isinstance(ckpt_input[0], list):
                result["checkpoints"] = [{"name": name} for name in ckpt_input[0]]

        # LoRAs from LoraLoader
        if "LoraLoader" in info:
            lora_input = info["LoraLoader"]["input"]["required"].get("lora_name", None)
            if lora_input and isinstance(lora_input, list) and len(lora_input) > 0 and isinstance(lora_input[0], list):
                result["loras"] = [{"name": name} for name in lora_input[0]]

        # VAEs from VaeLoader
        if "VAELoader" in info:
            vae_input = info["VAELoader"]["input"]["required"].get("vae_name", None)
            if vae_input and isinstance(vae_input, list) and len(vae_input) > 0 and isinstance(vae_input[0], list):
                result["vaes"] = [{"name": name} for name in vae_input[0]]

        # Upscalers from UpscaleModelLoader
        if "UpscaleModelLoader" in info:
            upscale_input = info["UpscaleModelLoader"]["input"]["required"].get("model_name", None)
            if upscale_input and isinstance(upscale_input, list) and len(upscale_input) > 0 and isinstance(upscale_input[0], list):
                result["upscalers"] = [{"name": name} for name in upscale_input[0]]

        # ControlNet from ControlNetLoader
        if "ControlNetLoader" in info:
            cn_input = info["ControlNetLoader"]["input"]["required"].get("control_net_name", None)
            if cn_input and isinstance(cn_input, list) and len(cn_input) > 0 and isinstance(cn_input[0], list):
                result["controlnet"] = [{"name": name} for name in cn_input[0]]

        # CLIP models from CLIPLoader
        if "CLIPLoader" in info:
            clip_input = info["CLIPLoader"]["input"]["required"].get("clip_name", None)
            if clip_input and isinstance(clip_input, list) and len(clip_input) > 0 and isinstance(clip_input[0], list):
                result["clip"] = [{"name": name} for name in clip_input[0]]

        return result

    def close(self):
        self._client.close()


# ══════════════════════════════════════════════════════════════════════
# WebSocket client — real-time execution progress
# ══════════════════════════════════════════════════════════════════════

class ComfyUIWebSocket:
    """Async WebSocket client for real-time ComfyUI execution events.

    Connects to ws://{host}/ws?clientId={client_id} and yields events
    as they arrive. Each event is a dict with 'type' and 'data' keys.

    Usage:
        ws = ComfyUIWebSocket("http://127.0.0.1:8188")
        async for event in ws.listen("my-client-id"):
            if event["type"] == "executing" and event["data"]["node"] is None:
                break  # execution complete
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8188"):
        self.base_url = base_url.rstrip("/")
        # Derive ws:// URL from http:// base
        self.ws_url = self.base_url.replace("http://", "ws://", 1).replace("https://", "wss://", 1)

    async def listen(self, client_id: str = "") -> AsyncIterator[dict]:
        """Connect to ComfyUI WebSocket and yield events.

        Args:
            client_id: Unique client identifier. If empty, a UUID is generated.
                       This should match the client_id used in submit_prompt()
                       to receive events for that specific execution.

        Yields:
            dict: {"type": "event_type", "data": {...}}
        """
        if not client_id:
            client_id = str(uuid.uuid4())

        ws_url = f"{self.ws_url}/ws?clientId={client_id}"
        logger.info("WebSocket connecting to %s", ws_url)

        try:
            async with websockets.asyncio.client.connect(ws_url, max_size=2**26) as ws:
                logger.info("WebSocket connected (clientId=%s)", client_id)

                async for raw in ws:
                    if isinstance(raw, bytes):
                        # Binary messages: preview images, skip for now
                        continue

                    try:
                        message = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning("WebSocket received non-JSON text: %s", raw[:200])
                        continue

                    event_type = message.get("type", "")
                    data = message.get("data", {})

                    yield {"type": event_type, "data": data}

        except websockets.exceptions.ConnectionClosed as e:
            logger.warning("WebSocket connection closed: %s", e)
        except Exception as e:
            logger.error("WebSocket error: %s", e)
            raise


class ComfyUIError(Exception):
    """Raised when ComfyUI returns an error."""

    def __init__(self, message: str, data: dict | None = None):
        super().__init__(message)
        self.data = data