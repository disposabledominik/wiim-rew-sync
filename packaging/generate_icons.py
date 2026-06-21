"""Generate platform-specific icon files from the SVG source.

Requires:
    - pillow (pip install Pillow)
    - cairosvg (pip install cairosvg)

Usage:
    python packaging/generate_icons.py

Outputs:
    - src/gui/assets/icons/app_icon.ico (Windows: 256, 128, 64, 48, 32, 16)
    - src/gui/assets/icons/app_icon.icns (macOS)
    - src/gui/assets/icons/app_icon.png (256x256 PNG)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Icon sizes to embed in the .ico file
ICO_SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SVG_PATH = PROJECT_ROOT / "src" / "gui" / "assets" / "icons" / "app_icon.svg"
ICONS_DIR = SVG_PATH.parent


def generate_png(size: int = 256) -> Path:
    """Render the SVG to a PNG at the given size.

    Returns:
        Path to the generated PNG file.
    """
    try:
        import cairosvg
    except ImportError:
        print("ERROR: cairosvg is required. Install with: pip install cairosvg")
        sys.exit(1)

    png_path = ICONS_DIR / "app_icon.png"
    cairosvg.svg2png(
        url=str(SVG_PATH),
        write_to=str(png_path),
        output_width=size,
        output_height=size,
    )
    print(f"Generated: {png_path}")
    return png_path


def generate_ico() -> Path:
    """Generate a multi-resolution .ico file.

    Returns:
        Path to the generated .ico file.
    """
    try:
        import cairosvg
        from PIL import Image
    except ImportError:
        print("ERROR: Pillow and cairosvg are required.")
        print("  pip install Pillow cairosvg")
        sys.exit(1)

    from io import BytesIO

    images = []
    for width, height in ICO_SIZES:
        png_data = cairosvg.svg2png(
            url=str(SVG_PATH), output_width=width, output_height=height
        )
        img = Image.open(BytesIO(png_data))
        images.append(img)

    ico_path = ICONS_DIR / "app_icon.ico"
    images[0].save(ico_path, format="ICO", sizes=ICO_SIZES, append_images=images[1:])
    print(f"Generated: {ico_path}")
    return ico_path


def generate_icns() -> Path:
    """Generate a macOS .icns file.

    Note: This is a simplified approach. For production, use Apple's
    iconutil or a dedicated icns library.

    Returns:
        Path to the generated .icns file.
    """
    # macOS .icns generation typically requires iconutil or a third-party lib.
    # For now, generate the 1024x1024 PNG that iconutil expects.
    try:
        import cairosvg
    except ImportError:
        print("ERROR: cairosvg is required. Install with: pip install cairosvg")
        sys.exit(1)

    iconset_dir = ICONS_DIR / "app_icon.iconset"
    iconset_dir.mkdir(exist_ok=True)

    # Generate required sizes for iconutil
    icon_sizes = [16, 32, 64, 128, 256, 512, 1024]
    for size in icon_sizes:
        png_data = cairosvg.svg2png(
            url=str(SVG_PATH), output_width=size, output_height=size
        )
        out_path = iconset_dir / f"icon_{size}x{size}.png"
        out_path.write_bytes(png_data)

    icns_path = ICONS_DIR / "app_icon.icns"
    print(f"Iconset generated at: {iconset_dir}")
    print(f"Run: iconutil -c icns {iconset_dir} -o {icns_path}")
    print("(macOS only)")
    return icns_path


if __name__ == "__main__":
    if not SVG_PATH.exists():
        print(f"ERROR: SVG source not found at {SVG_PATH}")
        sys.exit(1)

    print(f"Source SVG: {SVG_PATH}")
    print()

    generate_png()
    generate_ico()
    generate_icns()

    print("\nDone.")
