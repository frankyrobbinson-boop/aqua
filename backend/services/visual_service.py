import os
from PIL import Image, ImageDraw, ImageFont

# Distinct colors per scene — rotate so adjacent scenes are visually different
_PALETTE = [
    (31, 97, 141),   # steel blue
    (118, 68, 138),  # purple
    (23, 165, 137),  # teal
    (186, 74, 0),    # burnt orange
    (39, 174, 96),   # green
    (192, 57, 43),   # red
    (93, 109, 126),  # slate
    (142, 68, 173),  # violet
]

W, H = 2304, 1296  # 1.2× 1080p so zoompan has room to move


def generate_placeholder(scene: dict, output_path: str):
    color = _PALETTE[scene['id'] % len(_PALETTE)]
    img = Image.new('RGB', (W, H), color)
    draw = ImageDraw.Draw(img)

    font_large = font_small = None
    for candidate in ['/System/Library/Fonts/Helvetica.ttc',
                      '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf']:
        if os.path.exists(candidate):
            try:
                font_large = ImageFont.truetype(candidate, 120)
                font_small = ImageFont.truetype(candidate, 60)
            except Exception:
                pass
            break

    _draw_centered(draw, f"Scene {scene['id']}", W // 2, H // 2 - 120, font_large, (255, 255, 255))
    window = f"{scene['start_time']:.1f}s – {scene['end_time']:.1f}s  ({scene['duration']:.1f}s)"
    _draw_centered(draw, window, W // 2, H // 2 + 20, font_small, (220, 220, 220))
    hint = scene.get('visual_description', '')[:80]
    _draw_centered(draw, hint, W // 2, H // 2 + 120, font_small, (180, 180, 180))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path, 'PNG')


def _draw_centered(draw, text, cx, cy, font, fill):
    if font:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((cx - tw // 2, cy - th // 2), text, font=font, fill=fill)
    else:
        draw.text((cx, cy), text, fill=fill)


def generate_all_placeholders(project_name: str, scene_windows: list) -> dict:
    """Generate one placeholder PNG per scene. Returns {scene_id: path}."""
    img_dir = f"../projects/{project_name}/images"
    paths = {}
    for scene in scene_windows:
        path = os.path.join(img_dir, f"scene_{scene['id']:03d}.png")
        generate_placeholder(scene, path)
        paths[scene['id']] = path
    return paths
