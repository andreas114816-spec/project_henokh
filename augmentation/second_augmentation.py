"""Augmentasi ringan yang wajar untuk gambar wajah PIL."""

from __future__ import annotations

import random

import numpy as np
from PIL import Image, ImageEnhance


def reasonable_augment(image: Image.Image) -> Image.Image:
    """Return an RGB image with randomized, non-destructive augmentation."""
    image = image.convert("RGB")

    if random.random() < 0.5:
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if random.random() < 0.6:
        image = image.rotate(
            random.uniform(-5, 5), resample=Image.Resampling.BICUBIC, expand=False
        )
    if random.random() < 0.7:
        image = ImageEnhance.Brightness(image).enhance(random.uniform(0.85, 1.15))
    if random.random() < 0.7:
        image = ImageEnhance.Contrast(image).enhance(random.uniform(0.85, 1.15))
    if random.random() < 0.5:
        image = ImageEnhance.Color(image).enhance(random.uniform(0.90, 1.10))
    if random.random() < 0.4:
        image = ImageEnhance.Sharpness(image).enhance(random.uniform(0.85, 1.15))
    if random.random() < 0.5:
        image = mild_zoom(image)
    if random.random() < 0.3:
        image = add_mild_noise(image)
    return image


def mild_zoom(image: Image.Image, zoom_range: tuple[float, float] = (1.00, 1.08)) -> Image.Image:
    """Crop by a small random amount and resize to the original dimensions."""
    w, h = image.size
    zoom = random.uniform(*zoom_range)
    new_w, new_h = max(1, int(w / zoom)), max(1, int(h / zoom))
    if new_w >= w or new_h >= h:
        return image
    left = random.randint(0, w - new_w)
    top = random.randint(0, h - new_h)
    return image.crop((left, top, left + new_w, top + new_h)).resize(
        (w, h), Image.Resampling.BICUBIC
    )


def add_mild_noise(
    image: Image.Image, std_range: tuple[float, float] = (1, 4)
) -> Image.Image:
    """Add weak Gaussian sensor noise without changing image dimensions."""
    array = np.asarray(image, dtype=np.float32)
    noise = np.random.normal(0, random.uniform(*std_range), array.shape)
    return Image.fromarray(np.clip(array + noise, 0, 255).astype(np.uint8), mode="RGB")
