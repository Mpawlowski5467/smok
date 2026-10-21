"""Bounded inline vision input. No URLs or local paths are fetched by image blocks."""

import base64
import binascii
import io
import math
from dataclasses import dataclass
from typing import Literal

from PIL import Image as PillowImage

MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_CONTEXT_IMAGE_BYTES = 6 * 1024 * 1024
MEDIA = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}


@dataclass(frozen=True)
class Image:
    media_type: str
    data: str
    type: Literal["image"] = "image"

    def __post_init__(self):
        if self.media_type not in MEDIA or not isinstance(self.data, str):
            raise ValueError("Images must be PNG, JPEG, or WebP.")
        if len(self.data) > 4 * math.ceil(MAX_IMAGE_BYTES / 3):
            raise ValueError("Each image must be at most 2 MiB.")
        try:
            raw = base64.b64decode(self.data, validate=True)
            if not raw or len(raw) > MAX_IMAGE_BYTES:
                raise ValueError("Each image must be at most 2 MiB.")
            with PillowImage.open(io.BytesIO(raw)) as image:
                if image.format != MEDIA[self.media_type]:
                    raise ValueError("Image bytes do not match the declared media type.")
                if max(image.size) > 4096 or image.width * image.height > 16_000_000:
                    raise ValueError("Images must fit within 4096 pixels and 16 megapixels.")
                if getattr(image, "n_frames", 1) != 1:
                    raise ValueError("Use a still image, not an animation.")
                image.verify()
        except (OSError, binascii.Error, PillowImage.DecompressionBombError) as exc:
            raise ValueError("Invalid image data.") from exc

    @property
    def estimated_tokens(self):
        # A labeled heuristic, never a provider bill. Do not count base64 as prose.
        with PillowImage.open(io.BytesIO(base64.b64decode(self.data))) as image:
            return 1024 + 256 * math.ceil(image.width / 512) * math.ceil(image.height / 512)


def validate_images(messages, images):
    if len(images) > 4 or not all(isinstance(image, Image) for image in images):
        raise ValueError("Attach at most four validated images per turn.")
    total = sum(len(b.data) for m in messages for b in m.content if isinstance(b, Image)) + sum(
        len(b.data) for b in images
    )
    if total > MAX_CONTEXT_IMAGE_BYTES * 4 // 3:
        raise ValueError("Image context exceeds 6 MiB; compact or start a new session.")
