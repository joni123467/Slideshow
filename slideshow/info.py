"""Erzeugt Informations-Bildschirme für die Slideshow."""
from __future__ import annotations

import datetime as _dt
import pathlib
from typing import Iterable, List, Optional, Sequence

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
        margin = 60
        max_text_width = width - 2 * margin
        background = "#0b1d36"

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

        title_font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        text_font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

        wrapped_lines: List[str]
        try:
            title_size = 56
            text_size = 36
            title_font = ImageFont.truetype(title_font_path, title_size)
            text_font = ImageFont.truetype(text_font_path, text_size)
            measure_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))

            def text_height(font: ImageFont.FreeTypeFont, sample: str) -> int:
                bbox = font.getbbox(sample)
                return bbox[3] - bbox[1]

            def layout(
                font_title: ImageFont.FreeTypeFont, font_text: ImageFont.FreeTypeFont
            ) -> tuple[List[str], int]:
                wrapped = self._wrap_lines(lines[1:], font_text, max_text_width, measure_draw)
                title_h = text_height(font_title, lines[0])
                text_h = text_height(font_text, "Ag")
                line_gap = max(6, int(text_h * 0.35))
                gap_after_title = max(line_gap, int(text_h * 0.8))
                total_height = margin + title_h + gap_after_title
                if wrapped:
                    for entry in wrapped:
                        if entry:
                            total_height += text_h
                        else:
                            total_height += max(line_gap, text_h // 2)
                        total_height += line_gap
                    total_height -= line_gap
                total_height += margin
                return wrapped, total_height

            wrapped_lines, required_height = layout(title_font, text_font)
            while required_height > height and text_size > 20:
                text_size -= 2
                text_font = ImageFont.truetype(text_font_path, text_size)
                wrapped_lines, required_height = layout(title_font, text_font)
            while required_height > height and title_size > 32:
                title_size -= 2
                title_font = ImageFont.truetype(title_font_path, title_size)
                wrapped_lines, required_height = layout(title_font, text_font)
            if required_height > height:
                wrapped_lines = self._wrap_lines(lines[1:], text_font, max_text_width, measure_draw)
        except Exception:
            title_font = ImageFont.load_default()
            text_font = ImageFont.load_default()
            wrapped_lines = lines[1:]

        image = Image.new("RGB", (width, height), color=background)
        draw = ImageDraw.Draw(image)

        def font_text_height(font: ImageFont.ImageFont, sample: str = "Ag") -> int:
            try:
                bbox = font.getbbox(sample)
                return bbox[3] - bbox[1]
            except Exception:
                return font.getsize(sample)[1]

        title_height = font_text_height(title_font, lines[0])
        text_height = font_text_height(text_font)
        line_gap = max(6, int(text_height * 0.35))
        gap_after_title = max(line_gap, int(text_height * 0.8))

        y = margin
        draw.text((margin, y), lines[0], font=title_font, fill="#f7faff")
        y += title_height + gap_after_title
        for line in wrapped_lines:
            if not line:
                y += max(line_gap, text_height // 2)
                continue
            draw.text((margin, y), line, font=text_font, fill="#e2ebff")
            y += text_height + line_gap

        output_path = self.output_dir / "info_screen.png"
        image.save(output_path, format="PNG")
        return output_path

    def _wrap_lines(
        self,
        content_lines: Sequence[str],
        font: ImageFont.ImageFont,
        max_width: int,
        draw: ImageDraw.ImageDraw,
    ) -> List[str]:
        wrapped: List[str] = []
        for line in content_lines:
            if not line:
                wrapped.append("")
                continue
            if line.startswith("  - "):
                wrapped.extend(self._wrap_single_line(line[4:], font, max_width, draw, prefix="  - ", indent="    "))
            else:
                wrapped.extend(self._wrap_single_line(line, font, max_width, draw))
        return wrapped

    def _wrap_single_line(
        self,
        text: str,
        font: ImageFont.ImageFont,
        max_width: int,
        draw: ImageDraw.ImageDraw,
        *,
        prefix: str = "",
        indent: str = "",
    ) -> List[str]:
        words = text.split()
        if not words:
            return [prefix.rstrip() if prefix else ""]

        lines: List[str] = []
        current_words: List[str] = []
        current_prefix = prefix

        for word in words:
            candidate_words = current_words + [word]
            candidate = current_prefix + " ".join(candidate_words)
            if draw.textlength(candidate, font=font) <= max_width or not current_words:
                current_words.append(word)
                continue

            lines.append(current_prefix + " ".join(current_words))
            current_prefix = indent
            current_words = [word]

        if current_words:
            lines.append(current_prefix + " ".join(current_words))

        return lines or [prefix.rstrip() if prefix else ""]
