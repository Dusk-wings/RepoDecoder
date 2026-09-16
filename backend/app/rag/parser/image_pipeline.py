import os
import time
import random
from PIL import Image


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

    def _vission_LLM(self, image_url: str, internal_url: bool = False):
        """
        Placeholder for your Vision LLM function.
        It should take an image URL and return a text description.
        """
        # Replace this with your actual LLM calling logic
        return (
            f"[Image Description: A detailed description of the image at {image_url}]"
        )

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

    def _save_image(self, image_path: str):
        """Saves or moves the extracted image to your designated storage."""
        print(f"[Log] Image saved permanently: {image_path}")
