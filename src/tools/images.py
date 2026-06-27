"""MCP tools — image upload, download, thumbnail generation."""

import os
import base64
import tempfile
from io import BytesIO
from typing import Any

from PIL import Image

from src.comfyui_client import ComfyUIClient

THUMBNAIL_MAX_SIZE = int(os.environ.get("THUMBNAIL_MAX_SIZE", "512"))
THUMBNAIL_FORMAT = os.environ.get("THUMBNAIL_FORMAT", "JPEG")
THUMBNAIL_QUALITY = int(os.environ.get("THUMBNAIL_QUALITY", "85"))


def _make_thumbnail(image_bytes: bytes) -> str:
    """Generate a base64-encoded thumbnail from raw image bytes."""
    img = Image.open(BytesIO(image_bytes))
    img.thumbnail((THUMBNAIL_MAX_SIZE, THUMBNAIL_MAX_SIZE), Image.LANCZOS)

    buf = BytesIO()
    fmt = THUMBNAIL_FORMAT.upper()
    if fmt == "JPEG":
        img = img.convert("RGB")
    img.save(buf, format=fmt, quality=THUMBNAIL_QUALITY if fmt == "JPEG" else None)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def get_generated_image(
    client: ComfyUIClient,
    filename: str,
    subfolder: str = "",
    image_type: str = "output",
    thumbnail: bool = True,
) -> dict:
    """Download a generated image from ComfyUI. Returns thumbnail + original path."""
    try:
        raw = client.get_image(filename, subfolder=subfolder, image_type=image_type)

        # Save original to a temp file
        tmp = tempfile.NamedTemporaryFile(
            suffix=".png" if filename.endswith(".png") else ".jpg",
            delete=False,
            prefix="comfyui_",
        )
        tmp.write(raw)
        tmp.close()

        result = {
            "success": True,
            "filename": filename,
            "original_path": tmp.name,
        }

        if thumbnail:
            result["thumbnail_base64"] = _make_thumbnail(raw)

        return result
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "FILE_NOT_FOUND"}


def upload_image(
    client: ComfyUIClient,
    image_path: str,
    subfolder: str = "",
    overwrite: bool = False,
) -> dict:
    """Upload an image to ComfyUI's input directory."""
    if not os.path.isfile(image_path):
        return {
            "success": False,
            "error": f"File not found: {image_path}",
            "error_code": "FILE_NOT_FOUND",
        }

    try:
        result = client.upload_image(image_path, subfolder=subfolder, overwrite=overwrite)
        return {
            "success": True,
            "filename": os.path.basename(image_path),
            "subfolder": subfolder,
            "upload_result": result,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "COMFYUI_UNREACHABLE"}