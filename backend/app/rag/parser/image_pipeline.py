import base64
import mimetypes
import os
import random
import time
from pathlib import Path
from urllib.parse import unquote, urlparse
import uuid
from datetime import datetime, timezone
import logging


from openai import OpenAI
from PIL import Image

from app.core.config import env_config
from app.utils.storage import BucketStorage
from app.models.bucket_file import BucketFileType

logger = logging.getLogger(__name__)

class VisionFilePipeline:
    def __init__(
        self,
        min_dim: int = 120,
        min_pixels: int = 25000,
        max_aspect_ratio: float = 5.0,
    ) -> None:
        self.min_dim = min_dim
        self.min_pixels = min_pixels
        self.max_aspect_ratio = max_aspect_ratio
        pass

    def _generate_unique_filename(self, original_path: str, ext: str) -> str:
        """Generates {original_name}_{time_in_ms}_{random}.{new_ext}"""
        base_name = os.path.splitext(os.path.basename(original_path))[0]
        time_ms = int(time.time() * 1000)
        random_num = random.randint(1000, 9999)
        return f"{base_name}_{time_ms}_{random_num}.{ext}"

    def _get_image_path(self, image_url: str) -> dict:
        if not image_url or not image_url.strip():
            raise ValueError("image_url must not be empty")

        is_internal = False
        parsed_url = urlparse(image_url)
        if parsed_url.scheme in {"http", "https"}:
            is_internal = False
            image_path = image_url
            image_input = image_url
        else:
            is_internal = True
            if parsed_url.scheme == "file":
                image_path = Path(unquote(parsed_url.path))
            else:
                requested_path = Path(image_url).expanduser()
                source_file = getattr(self, "file_path", None)
                source_dir = (
                    Path(source_file).expanduser().resolve().parent
                    if source_file
                    else Path.cwd()
                )

                candidates = []
                if requested_path.is_absolute():
                    candidates.append(source_dir / str(requested_path).lstrip("/"))
                else:
                    candidates.append(source_dir / requested_path)
                candidates.append(requested_path)

                image_path = next(
                    (
                        candidate.resolve()
                        for candidate in candidates
                        if candidate.is_file()
                    ),
                    candidates[-1].resolve(),
                )

            if not image_path.is_file():
                raise FileNotFoundError(f"Image file not found: {image_url}")

            mime_type = (
                mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
            )
            encoded_image = base64.b64encode(image_path.read_bytes()).decode("ascii")
            image_input = f"data:{mime_type};base64,{encoded_image}"

        return {
            "image_path": image_path,
            "image_input": image_input,
            "internal": is_internal,
        }

    def _vission_LLM(
        self,
        image_url: str,
        # *,
        # file_id: uuid.UUID,
        # repo_id: uuid.UUID,
    ) -> str:
        """Describe a local or remotely hosted image with Groq's vision model."""
        image_details = self._get_image_path(image_url=image_url)
        image_input = image_details.get("image_input", None)

        if not image_input:
            raise KeyError("[VISSION-LLM] image_input VALUE IS NOT DEFINED")

        if not env_config.GROQ_API_KEY:
            raise RuntimeError("[VISSION-LLM] GROQ_API_KEY IS NOT CONFIGURED")

        client = OpenAI(
            api_key=env_config.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
        )
        response = client.chat.completions.create(
            model="qwen/qwen3.8-27b",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Describe this image accurately in under 180 tokens.",
                        },
                        {"type": "image_url", "image_url": {"url": image_input}},
                    ],
                }
            ],
            max_tokens=180,
        )

        description = response.choices[0].message.content
        if not description:
            raise RuntimeError(
                "[VISSION-LLM] THE GROQ IMAGE MODEL RETURNED A EMPTY DISCRIPTION"
            )

        # await BucketStorage.store_file(bucket_name=env_config.IMAGE_BUCKET_NAME, object_name="", file_path="")
        return description.strip()

    def _is_meaningful_image(self, pil_img: Image.Image) -> bool:
        """Filters out decorative lines, small icons, bullets, and header logos."""
        w, h = pil_img.size

        # 1. Reject tiny images/icons
        if w < self.min_dim or h < self.min_dim or (w * h) < self.min_pixels:
            return False

        # 2. Reject extreme aspect ratios (e.g., thin divider lines or vertical banners)
        aspect_ratio = max(w / h, h / w)
        if aspect_ratio > self.max_aspect_ratio:
            return False

        return True

    async def _save_image(self, file_id: uuid.UUID, repo_id: uuid.UUID, url: str):
        """Saves or moves the extracted image to your designated storage."""
        image_details = self._get_image_path(url)
        image_file_path = image_details.get("image_path", None)

        if image_file_path is None:
            raise KeyError("[SAVE-IMAGE] UNABLE TO GET THE FILE TO SAVE")

        is_internal = image_details.get("internal", False)

        if not is_internal:
            return

        time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        object_name = (
            f"{repo_id}/{file_id}/{uuid.uuid4}-{time}{image_file_path.suffix}"
        )

        bucket_name = "bucket"
        if env_config.IMAGE_BUCKET_NAME:
            bucket_name = env_config.IMAGE_BUCKET_NAME

        try:

            bucket_url = BucketStorage.store_file(
                bucket_name=bucket_name,
                object_name=object_name,
                file_path=image_file_path,
                public_bucket=True,
            )

            if bucket_url:
                await BucketStorage.update_file_upload_status(
                    file_id=file_id,
                    repo_id=repo_id,
                    url=url,
                    storage_key=bucket_url,
                    file_type=BucketFileType.image,
                )
        except Exception as e:
            logger.exception("[SAVE-IMAGE] OPERATION FAILED WITH EXCEPTION, %s", e)
            
