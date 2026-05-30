#!/usr/bin/env python3
"""Generate PackVault branding assets from a single master logo.

Edit packvault/ui/static/branding/logo.png, then run:

    python scripts/generate_branding_assets.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
BRANDING_DIR = REPO_ROOT / "packvault" / "ui" / "static" / "branding"
DEFAULT_SOURCE = BRANDING_DIR / "logo.png"
STATIC_FAVICON = REPO_ROOT / "packvault" / "ui" / "static" / "favicon.ico"

# PNG sizes used across UI, docs, and future manifest references.
PNG_SIZES: tuple[int, ...] = (16, 32, 48, 180, 192, 512)
ICO_SIZES: tuple[int, ...] = (16, 32, 48)


def _resize_square(img: Image.Image, size: int) -> Image.Image:
    if img.size != (size, size):
        return img.resize((size, size), Image.Resampling.LANCZOS)
    return img.copy()


def generate(source: Path, out_dir: Path, static_favicon: Path) -> None:
    if not source.is_file():
        raise SystemExit(f"Source logo not found: {source}")

    out_dir.mkdir(parents=True, exist_ok=True)
    master = Image.open(source)
    if master.mode not in {"RGB", "RGBA"}:
        master = master.convert("RGBA")

    for size in PNG_SIZES:
        target = out_dir / f"icon-{size}.png"
        _resize_square(master, size).save(target, format="PNG", optimize=True)
        print(f"wrote {target.relative_to(REPO_ROOT)}")

    ico_images = [_resize_square(master, size) for size in ICO_SIZES]
    favicon_path = out_dir / "favicon.ico"
    ico_images[0].save(
        favicon_path,
        format="ICO",
        sizes=[(image.width, image.height) for image in ico_images],
        append_images=ico_images[1:],
    )
    print(f"wrote {favicon_path.relative_to(REPO_ROOT)}")

    static_favicon.parent.mkdir(parents=True, exist_ok=True)
    static_favicon.write_bytes(favicon_path.read_bytes())
    print(f"wrote {static_favicon.relative_to(REPO_ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"Master logo PNG (default: {DEFAULT_SOURCE.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=BRANDING_DIR,
        help=f"Output directory (default: {BRANDING_DIR.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--static-favicon",
        type=Path,
        default=STATIC_FAVICON,
        help="favicon.ico path served at /favicon.ico",
    )
    args = parser.parse_args()
    generate(args.source, args.out_dir, args.static_favicon)


if __name__ == "__main__":
    main()
