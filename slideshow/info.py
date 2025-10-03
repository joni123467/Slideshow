"""Erzeugt Informations-Bildschirme für die Slideshow."""
from __future__ import annotations

import datetime as _dt
import pathlib
from typing import Iterable, Optional, Sequence

from PIL import Image, ImageDraw, ImageFont

from .config import DATA_DIR

INFO_DIR = DATA_DIR / "info"


class InfoScreen:
    """Erzeugt ein Bild mit Hostname und IP-Adressen."""

    def __init__(self, output_dir: pathlib.Path = INFO_DIR):
        self.output_dir = pathlib.Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def render(
        self,
        hostname: str,
        addresses: Iterable[str],
        manual: bool = False,
        details: Optional[Sequence[str]] = None,
    ) -> pathlib.Path:
        width, height = 1280, 720
        image = Image.new("RGB", (width, height), color="#0b1d36")
        draw = ImageDraw.Draw(image)

        try:
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 56)
            font_text = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
        except Exception:
            font_title = ImageFont.load_default()
            font_text = ImageFont.load_default()

        now = _dt.datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        lines = [
            "Slideshow bereit",
            f"Hostname: {hostname}",
            "IP-Adressen:",
        ]
        ips = list(addresses) or ["keine Adresse verfügbar"]
        lines.extend([f"  - {ip}" for ip in ips])
        lines.append("")
        lines.append(f"Stand: {now}")
        if manual:
            lines.append("(Infobildschirm manuell aktiviert)")
        if details:
            lines.append("")
            lines.extend(details)

        draw.text((60, 60), lines[0], font=font_title, fill="#f7faff")
        offset_y = 160
        for line in lines[1:]:
            draw.text((60, offset_y), line, font=font_text, fill="#e2ebff")
            offset_y += 50

        output_path = self.output_dir / "info_screen.png"
        image.save(output_path, format="PNG")
        return output_path
