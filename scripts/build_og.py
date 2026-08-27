#!/usr/bin/env python3
"""Build the static Open Graph preview image used by LINE/social previews."""

from pathlib import Path
import sys

from PIL import Image


def main() -> None:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "_site/news-icon-v2.png")
    dst = Path(sys.argv[2] if len(sys.argv) > 2 else "_site/og-preview-v6.jpg")

    if not src.exists():
        raise SystemExit(f"missing icon: {src}")

    canvas = Image.new("RGB", (1200, 630), (244, 210, 48))
    with Image.open(src) as opened:
        icon = opened.convert("RGBA")
    icon.thumbnail((520, 520), Image.Resampling.LANCZOS)

    x = (canvas.width - icon.width) // 2
    y = (canvas.height - icon.height) // 2
    canvas.paste(icon, (x, y), icon)

    dst.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dst, "JPEG", quality=88, optimize=True)
    print(f"[asset] built {dst} ({canvas.width}x{canvas.height})")


if __name__ == "__main__":
    main()
