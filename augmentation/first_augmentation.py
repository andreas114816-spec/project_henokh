"""Efek spoof untuk mensimulasikan foto cetak atau layar ponsel."""

from __future__ import annotations

import random

import cv2
import numpy as np


SPOOF_MODES = ("phone", "printed", "both")


def _odd_kernel(maximum: int, preferred: int) -> int:
    """Return an odd OpenCV kernel that fits a possibly small image."""
    size = min(maximum, preferred)
    if size % 2 == 0:
        size -= 1
    return max(1, size)


def recapture_phone_effect(image: np.ndarray) -> np.ndarray:
    """Simulate an image photographed again from a phone screen."""
    if image is None or image.ndim != 3:
        raise ValueError("image must be a non-empty BGR image")

    h, w = image.shape[:2]
    if h < 2 or w < 2:
        raise ValueError("image must be at least 2x2 pixels")

    scale = random.uniform(0.65, 0.85)
    small = cv2.resize(image, (max(1, int(w * scale)), max(1, int(h * scale))))
    image = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)

    blur_kernel = _odd_kernel(min(h, w), random.choice((3, 5)))
    image = cv2.GaussianBlur(image, (blur_kernel, blur_kernel), 0)
    image = cv2.convertScaleAbs(
        image, alpha=random.uniform(0.75, 0.95), beta=random.randint(20, 55)
    )

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] *= random.uniform(0.45, 0.75)
    hsv[:, :, 2] *= random.uniform(1.02, 1.12)
    image = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR)

    line_strength = random.randint(12, 32)
    line_gap = random.choice((2, 3, 4))
    moire = np.zeros((h, w), dtype=np.float32)
    moire[:, ::line_gap] = line_strength
    x_axis = np.arange(w)
    moire += (
        np.sin(2 * np.pi * x_axis / random.uniform(3.5, 7.0))
        * random.uniform(8, 18)
    )[None, :]
    moire = np.clip(moire, 0, 255).astype(np.uint8)
    image = cv2.subtract(image, cv2.merge((moire, moire, moire)))

    for y in range(0, h, random.randint(6, 12)):
        image[y : y + 1] = np.clip(
            image[y : y + 1].astype(np.float32) * random.uniform(0.82, 0.94),
            0,
            255,
        ).astype(np.uint8)

    overlay = image.copy()
    radius_low = max(1, int(min(h, w) * 0.12))
    radius_high = max(radius_low, int(min(h, w) * 0.28))
    cv2.circle(
        overlay,
        (random.randint(w // 4, max(w // 4, 3 * w // 4)),
         random.randint(max(0, int(h * 0.15)), max(0, int(h * 0.45)))),
        random.randint(radius_low, radius_high),
        (255, 255, 255),
        -1,
    )
    glare_kernel = _odd_kernel(min(h, w), 99)
    overlay = cv2.GaussianBlur(overlay, (glare_kernel, glare_kernel), 0)
    image = cv2.addWeighted(image, 0.82, overlay, 0.18, 0)

    y_grid, x_grid = np.indices((h, w))
    center_x = w / 2 + random.randint(-max(1, w // 8), max(1, w // 8))
    center_y = h / 2 + random.randint(-max(1, h // 8), max(1, h // 8))
    dist = np.sqrt((x_grid - center_x) ** 2 + (y_grid - center_y) ** 2)
    max_dist = float(dist.max()) or 1.0
    vignette = np.clip(1 - (dist / max_dist) * random.uniform(0.25, 0.45), 0.55, 1.0)
    image = np.clip(image.astype(np.float32) * vignette[:, :, None], 0, 255).astype(np.uint8)

    noise = np.random.normal(0, random.uniform(5, 14), image.shape)
    image = np.clip(image.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    dust = np.random.normal(0, random.uniform(3, 8), image.shape)
    image = np.clip(image.astype(np.float32) + dust, 0, 255).astype(np.uint8)

    margin_x = max(1, int(w * random.uniform(0.02, 0.07)))
    margin_y = max(1, int(h * random.uniform(0.02, 0.07)))
    src = np.float32(((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)))
    dst = np.float32(
        (
            (random.randint(0, margin_x), random.randint(0, margin_y)),
            (w - 1 - random.randint(0, margin_x), random.randint(0, margin_y)),
            (random.randint(0, margin_x), h - 1 - random.randint(0, margin_y)),
            (w - 1 - random.randint(0, margin_x), h - 1 - random.randint(0, margin_y)),
        )
    )
    image = cv2.warpPerspective(
        image,
        cv2.getPerspectiveTransform(src, dst),
        (w, h),
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(10, 10, 10),
    )

    border_x = min(max(1, int(w * random.uniform(0.035, 0.08))), max(1, (w - 1) // 2))
    border_y = min(max(1, int(h * random.uniform(0.035, 0.08))), max(1, (h - 1) // 2))
    inner_w, inner_h = max(1, w - 2 * border_x), max(1, h - 2 * border_y)
    canvas = np.full_like(image, random.randint(5, 20))
    inner = cv2.resize(image, (inner_w, inner_h))
    canvas[border_y : border_y + inner_h, border_x : border_x + inner_w] = inner
    final_kernel = _odd_kernel(min(h, w), 3)
    return cv2.GaussianBlur(canvas, (final_kernel, final_kernel), 0)


def printed_photo_effect(image: np.ndarray) -> np.ndarray:
    """Simulate a face photo printed on plain white paper."""
    if image is None or image.ndim != 3:
        raise ValueError("image must be a non-empty BGR image")

    h, w = image.shape[:2]
    kernel = _odd_kernel(min(h, w), 3)
    image = cv2.GaussianBlur(image, (kernel, kernel), 0)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] *= random.uniform(0.45, 0.75)
    hsv[:, :, 2] *= random.uniform(1.02, 1.12)
    image = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR)
    image = cv2.convertScaleAbs(
        image, alpha=random.uniform(0.88, 1.05), beta=random.randint(18, 45)
    )
    paper_noise = np.random.normal(0, random.uniform(4, 10), image.shape)
    image = np.clip(image.astype(np.float32) + paper_noise, 0, 255).astype(np.uint8)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] *= random.uniform(0.75, 0.9)
    image = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR)

    y, x = np.linspace(-1, 1, h), np.linspace(-1, 1, w)
    xv, yv = np.meshgrid(x, y)
    vignette = np.clip(
        1 - random.uniform(0.05, 0.12) * (xv**2 + yv**2), 0.85, 1.0
    )
    return np.clip(image.astype(np.float32) * vignette[:, :, None], 0, 255).astype(np.uint8)


def spoof_image(image: np.ndarray, mode: str | None = None) -> np.ndarray:
    """Apply one spoof mode; choose one randomly when ``mode`` is omitted."""
    mode = mode or random.choice(SPOOF_MODES)
    if mode == "phone":
        return recapture_phone_effect(image)
    if mode == "printed":
        return printed_photo_effect(image)
    if mode == "both":
        return recapture_phone_effect(printed_photo_effect(image))
    raise ValueError(f"unknown spoof mode: {mode}; choose from {', '.join(SPOOF_MODES)}")
