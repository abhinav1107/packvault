from __future__ import annotations

from pathlib import Path

BRANDING_DIR = Path(__file__).resolve().parent / "static" / "branding"
LOGO_SOURCE = BRANDING_DIR / "logo.png"
FAVICON_PATH = BRANDING_DIR / "favicon.ico"
STATIC_FAVICON_PATH = Path(__file__).resolve().parent / "static" / "favicon.ico"

ICON_SIZES: tuple[int, ...] = (16, 32, 48, 180, 192, 512)


def icon_png(size: int) -> Path:
    if size not in ICON_SIZES:
        supported = ", ".join(str(s) for s in ICON_SIZES)
        raise ValueError(f"Unsupported icon size {size}; use one of: {supported}")
    return BRANDING_DIR / f"icon-{size}.png"


def icon_static_url(size: int) -> str:
    return f"/static/branding/icon-{size}.png"
