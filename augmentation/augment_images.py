#!/usr/bin/env python3
"""Buat empat augmentasi untuk setiap gambar real/spoof dalam sebuah folder."""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from first_augmentation import spoof_image
from second_augmentation import reasonable_augment


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "augmented_images"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
CLASS_ALIASES = {"real": "real", "live": "real", "spoof": "spoof", "fake": "spoof"}


def parse_identity(image_path: Path, input_dir: Path) -> tuple[str, str, str, str]:
    """Extract class, name, NIM and optional suffix from CLASS_NAME_NIM*."""
    tokens = [token.strip() for token in image_path.stem.split("_") if token.strip()]
    class_name = CLASS_ALIASES.get(tokens[0].casefold()) if tokens else None

    if class_name:
        identity_tokens = tokens[1:]
    else:
        relative_parents = image_path.relative_to(input_dir).parts[:-1]
        class_name = next(
            (CLASS_ALIASES[part.casefold()] for part in reversed(relative_parents)
             if part.casefold() in CLASS_ALIASES),
            None,
        )
        identity_tokens = tokens

    if class_name is None:
        raise ValueError("kelas real/spoof tidak ditemukan pada nama file atau folder induk")

    nim_index = next(
        (index for index, token in enumerate(identity_tokens[1:], start=1) if token.isdigit()),
        None,
    )
    if nim_index is None:
        raise ValueError("gunakan format {class}_{Name}_{NIM}* dengan NIM berupa angka")

    name_tokens = identity_tokens[:nim_index]
    if not name_tokens:
        raise ValueError("Name tidak boleh kosong")

    name = "_".join(name_tokens)
    nim = identity_tokens[nim_index]
    suffix = "_".join(identity_tokens[nim_index + 1 :])
    return class_name, name, nim, suffix


def pil_to_bgr(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)


def bgr_to_pil(image: np.ndarray) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))


def augmented_image(source: Image.Image, class_name: str) -> Image.Image:
    """Real uses stage two; spoof uses stage one followed by stage two."""
    if class_name == "spoof":
        source = bgr_to_pil(spoof_image(pil_to_bgr(source)))
    return reasonable_augment(source)


def find_images(input_dir: Path, output_dir: Path) -> list[Path]:
    output_resolved = output_dir.resolve()
    return sorted(
        path
        for path in input_dir.rglob("*")
        if path.is_file()
        and path.suffix.lower() in IMAGE_EXTENSIONS
        and output_resolved not in path.resolve().parents
    )


def run(input_dir: Path, output_dir: Path, copies: int = 4, seed: int | None = None) -> tuple[int, int]:
    input_dir = input_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not input_dir.is_dir():
        raise ValueError(f"folder input tidak ditemukan: {input_dir}")
    if copies < 1:
        raise ValueError("jumlah duplikasi minimal 1")
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)

    images = find_images(input_dir, output_dir)
    if not images:
        raise ValueError(f"tidak ada gambar yang didukung di: {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    skipped = 0
    for image_path in images:
        try:
            _source_class, name, nim, old_suffix = parse_identity(image_path, input_dir)
            with Image.open(image_path) as opened:
                source = opened.convert("RGB")
            source_tag = f"_{old_suffix}" if old_suffix else ""
            for output_class in ("real", "spoof"):
                for copy_number in range(1, copies + 1):
                    result = augmented_image(source.copy(), output_class)
                    output_name = (
                        f"{output_class}_{name}_{nim}{source_tag}_aug{copy_number}"
                        f"{image_path.suffix.lower()}"
                    )
                    destination = output_dir / output_name
                    if destination.exists():
                        raise FileExistsError(
                            f"hasil sudah ada: {destination}; hapus/pindahkan output "
                            "atau gunakan --output lain"
                        )
                    result.save(destination)
                    written += 1
        except (OSError, ValueError) as error:
            skipped += 1
            print(f"Lewati {image_path}: {error}", file=sys.stderr)

    return written, skipped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Augmentasi folder gambar. real melewati second_augmentation.py; "
            "spoof melewati first_augmentation.py lalu second_augmentation.py."
        )
    )
    parser.add_argument(
        "folder", nargs="?", type=Path,
        help="path folder sumber gambar (akan ditanyakan jika tidak diisi)",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT_DIR,
        help=f"folder hasil (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument("--seed", type=int, help="seed opsional agar hasil dapat diulang")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.folder is None:
        folder_value = input("Masukkan path folder gambar: ").strip().strip('"').strip("'")
        if not folder_value:
            print("Error: path folder wajib diisi", file=sys.stderr)
            return 1
        args.folder = Path(folder_value)
    try:
        written, skipped = run(args.folder, args.output, copies=4, seed=args.seed)
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(f"Selesai: {written} gambar dibuat di {args.output.expanduser().resolve()}")
    if skipped:
        print(f"Peringatan: {skipped} file dilewati karena nama/file tidak valid.")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
