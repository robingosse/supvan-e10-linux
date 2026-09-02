from __future__ import annotations

import base64
import io
import json
import math
import subprocess
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFont, ImageOps
import qrcode
from qrcode.constants import ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q, ERROR_CORRECT_H

DOTS_PER_MM = 8.0
PRINTABLE_WIDTH_DOTS = 88
PRINTABLE_WIDTH_MM = PRINTABLE_WIDTH_DOTS / DOTS_PER_MM  # 11 mm
DEFAULT_STOCK_WIDTH_MM = 15.0
MAX_LENGTH_MM = 6000.0
MIN_LENGTH_MM = 5.0
ONE_DOT_MM = 1.0 / DOTS_PER_MM

ECC_MAP = {
    "L": ERROR_CORRECT_L,
    "M": ERROR_CORRECT_M,
    "Q": ERROR_CORRECT_Q,
    "H": ERROR_CORRECT_H,
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def mm_to_dots(mm: float) -> int:
    return max(0, int(round(mm * DOTS_PER_MM)))


def dots_to_mm(dots: int) -> float:
    return dots / DOTS_PER_MM


def resolve_font(family: str = "DejaVu Sans", bold: bool = False) -> str:
    """Resolve a font family through fontconfig, with a stable fallback."""
    pattern = family.strip() or "DejaVu Sans"
    if bold:
        pattern += ":style=Bold"
    try:
        out = subprocess.check_output(
            ["fc-match", "-f", "%{file}\n", pattern], text=True, stderr=subprocess.DEVNULL
        ).strip().splitlines()
        if out and Path(out[0]).exists():
            return out[0]
    except Exception:
        pass
    fallbacks = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for p in fallbacks:
        if Path(p).exists():
            return p
    raise RuntimeError("No usable TrueType font found. Install fonts-dejavu-core.")


def qr_matrix(data: str, ecc: str = "M", border_modules: int = 4) -> list[list[bool]]:
    if not data:
        raise ValueError("QR code text cannot be empty")
    ecc = ecc.upper()
    if ecc not in ECC_MAP:
        raise ValueError(f"Unsupported QR error correction: {ecc}")
    qr = qrcode.QRCode(
        version=None,
        error_correction=ECC_MAP[ecc],
        box_size=1,
        border=border_modules,
    )
    qr.add_data(data)
    qr.make(fit=True)
    return qr.get_matrix()


def qr_safe_module_scale(data: str, ecc: str = "M", border_modules: int = 4) -> tuple[int, int]:
    matrix = qr_matrix(data, ecc, border_modules)
    modules = len(matrix)
    scale = PRINTABLE_WIDTH_DOTS // modules
    return modules, scale


@dataclass
class Item:
    kind: str
    x_mm: float = 0.0
    y_mm: float = 0.0
    rotation: int = 0
    id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TextItem(Item):
    kind: str = "text"
    text: str = "Text"
    size_mm: float = 3.0
    family: str = "DejaVu Sans"
    bold: bool = False
    autofit_height: bool = False


@dataclass
class QRItem(Item):
    kind: str = "qr"
    data: str = ""
    ecc: str = "M"
    full_width: bool = True
    border_modules: int = 4
    requested_size_mm: float = PRINTABLE_WIDTH_MM


@dataclass
class ImageItem(Item):
    kind: str = "image"
    png_b64: str = ""
    name: str = "image.png"
    width_mm: float = PRINTABLE_WIDTH_MM
    height_mm: float = 10.0


@dataclass
class BoxItem(Item):
    kind: str = "box"
    width_mm: float = 6.0
    height_mm: float = 4.0
    line_dots: int = 1


@dataclass
class LineItem(Item):
    kind: str = "line"
    width_mm: float = 6.0
    line_dots: int = 1


ITEM_CLASSES = {
    "text": TextItem,
    "qr": QRItem,
    "image": ImageItem,
    "box": BoxItem,
    "line": LineItem,
}


@dataclass
class LabelDocument:
    length_mm: float = 50.0
    stock_width_mm: float = DEFAULT_STOCK_WIDTH_MM
    queue: str = "gosse-e10"
    density: int = 8
    auto_size: bool = True
    auto_margin_mm: float = 3.0
    items: list[Item] = field(default_factory=list)
    version: int = 2

    def validate(self) -> None:
        self.length_mm = _clamp(float(self.length_mm), MIN_LENGTH_MM, MAX_LENGTH_MM)
        self.stock_width_mm = float(self.stock_width_mm)
        if self.stock_width_mm not in (12.0, 15.0):
            self.stock_width_mm = DEFAULT_STOCK_WIDTH_MM
        self.density = int(_clamp(int(self.density), 0, 15))
        self.auto_size = bool(self.auto_size)
        self.auto_margin_mm = _clamp(float(self.auto_margin_mm), 0.0, 100.0)

    def add(self, item: Item) -> Item:
        if not item.id:
            used = {existing.id for existing in self.items}
            number = 1
            while f"item-{number}" in used:
                number += 1
            item.id = f"item-{number}"
        self.items.append(item)
        if self.auto_size:
            self.auto_length(self.auto_margin_mm, 10.0)
        else:
            self.clamp_item(item)
        return item

    def remove(self, item: Item) -> None:
        self.items.remove(item)

    def move_layer(self, item: Item, offset: int) -> int:
        """Move an item through the paint order and return its new index."""
        if item not in self.items:
            raise ValueError("Item is not in this document")
        old_index = self.items.index(item)
        new_index = int(_clamp(old_index + offset, 0, len(self.items) - 1))
        if new_index != old_index:
            self.items.pop(old_index)
            self.items.insert(new_index, item)
        return new_index

    def align_across(self, item: Item, alignment: str) -> float:
        """Align an item within the verified 11 mm printable band."""
        if item not in self.items:
            raise ValueError("Item is not in this document")
        _, _, width, _ = self.item_bounds_mm(item)
        available = max(0.0, PRINTABLE_WIDTH_MM - width)
        if alignment == "start":
            item.x_mm = 0.0
        elif alignment == "center":
            item.x_mm = available / 2.0
        elif alignment == "end":
            item.x_mm = available
        else:
            raise ValueError(f"Unknown alignment: {alignment}")
        self.clamp_item(item, allow_length_extend=self.auto_size)
        return item.x_mm

    def content_bounds_mm(self) -> tuple[float, float, float, float] | None:
        """Return x/y/width/height for all content, or None for a blank label."""
        if not self.items:
            return None
        bounds = [self.item_bounds_mm(item) for item in self.items]
        left = min(x for x, _, _, _ in bounds)
        top = min(y for _, y, _, _ in bounds)
        right = max(x + width for x, _, width, _ in bounds)
        bottom = max(y + height for _, y, _, height in bounds)
        return left, top, right - left, bottom - top

    def duplicate(self, item: Item) -> Item:
        data = item.to_dict()
        data["id"] = ""
        data["x_mm"] = float(data.get("x_mm", 0.0)) + ONE_DOT_MM * 2
        data["y_mm"] = float(data.get("y_mm", 0.0)) + ONE_DOT_MM * 2
        dup = item_from_dict(data)
        return self.add(dup)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "version": self.version,
            "length_mm": self.length_mm,
            "stock_width_mm": self.stock_width_mm,
            "queue": self.queue,
            "density": self.density,
            "auto_size": self.auto_size,
            "auto_margin_mm": self.auto_margin_mm,
            "items": [i.to_dict() for i in self.items],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LabelDocument":
        doc = cls(
            version=int(data.get("version", 1)),
            length_mm=float(data.get("length_mm", 50.0)),
            stock_width_mm=float(data.get("stock_width_mm", DEFAULT_STOCK_WIDTH_MM)),
            queue=str(data.get("queue", "gosse-e10")),
            density=int(data.get("density", 8)),
            auto_size=bool(data.get("auto_size", True)),
            auto_margin_mm=float(data.get("auto_margin_mm", 3.0)),
        )
        for raw in data.get("items", []):
            doc.items.append(item_from_dict(raw))
        doc.validate()
        for item in doc.items:
            doc.clamp_item(item)
        return doc

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n")

    @classmethod
    def load(cls, path: str | Path) -> "LabelDocument":
        return cls.from_dict(json.loads(Path(path).read_text()))

    def item_bounds_mm(self, item: Item) -> tuple[float, float, float, float]:
        tile, _ = render_item_tile(item)
        w_mm = dots_to_mm(tile.width)
        h_mm = dots_to_mm(tile.height)
        return item.x_mm, item.y_mm, w_mm, h_mm

    def clamp_item(self, item: Item, allow_length_extend: bool = False) -> None:
        _, _, w, h = self.item_bounds_mm(item)
        item.x_mm = _clamp(item.x_mm, 0.0, max(0.0, PRINTABLE_WIDTH_MM - w))
        if allow_length_extend and self.auto_size:
            item.y_mm = _clamp(item.y_mm, 0.0, max(0.0, MAX_LENGTH_MM - h))
        else:
            item.y_mm = _clamp(item.y_mm, 0.0, max(0.0, self.length_mm - h))

    def ensure_auto_length_for(self, item: Item, minimum_mm: float = 10.0) -> float:
        """Grow an auto-sized strip while dragging without shrinking under the pointer."""
        if not self.auto_size:
            return self.length_mm
        _, y, _, h = self.item_bounds_mm(item)
        needed = max(minimum_mm, y + h + self.auto_margin_mm)
        if needed > self.length_mm:
            self.length_mm = _clamp(needed, MIN_LENGTH_MM, MAX_LENGTH_MM)
        return self.length_mm

    def hit_test(self, x_mm: float, y_mm: float) -> Item | None:
        for item in reversed(self.items):
            x, y, w, h = self.item_bounds_mm(item)
            if x <= x_mm <= x + w and y <= y_mm <= y + h:
                return item
        return None

    def render(self, background: int = 255) -> Image.Image:
        self.validate()
        height = max(1, mm_to_dots(self.length_mm))
        canvas = Image.new("L", (PRINTABLE_WIDTH_DOTS, height), background)
        for item in self.items:
            tile, mask = render_item_tile(item)
            x = mm_to_dots(item.x_mm)
            y = mm_to_dots(item.y_mm)
            if x >= canvas.width or y >= canvas.height:
                continue
            if x + tile.width > canvas.width or y + tile.height > canvas.height:
                max_w = max(0, canvas.width - x)
                max_h = max(0, canvas.height - y)
                if max_w <= 0 or max_h <= 0:
                    continue
                tile = tile.crop((0, 0, max_w, max_h))
                if mask is not None:
                    mask = mask.crop((0, 0, max_w, max_h))
            if mask is None:
                canvas.paste(tile, (x, y))
            else:
                canvas.paste(tile, (x, y), mask)
        return canvas

    def auto_length(self, trailing_margin_mm: float | None = None, minimum_mm: float = 10.0) -> float:
        if trailing_margin_mm is None:
            trailing_margin_mm = self.auto_margin_mm
        bottom = 0.0
        for item in self.items:
            x, y, w, h = self.item_bounds_mm(item)
            bottom = max(bottom, y + h)
        self.length_mm = _clamp(max(minimum_mm, bottom + trailing_margin_mm), MIN_LENGTH_MM, MAX_LENGTH_MM)
        for item in self.items:
            self.clamp_item(item)
        return self.length_mm


def item_from_dict(raw: dict[str, Any]) -> Item:
    kind = str(raw.get("kind", ""))
    cls = ITEM_CLASSES.get(kind)
    if cls is None:
        raise ValueError(f"Unknown item kind: {kind}")
    fields = cls.__dataclass_fields__
    filtered = {k: v for k, v in raw.items() if k in fields}
    return cls(**filtered)


def _rotate(tile: Image.Image, mask: Image.Image | None, rotation: int) -> tuple[Image.Image, Image.Image | None]:
    rotation = int(rotation) % 360
    if rotation not in (0, 90, 180, 270):
        rotation = 0
    if rotation == 0:
        return tile, mask
    # PIL rotates counter-clockwise; UI labels a positive click as clockwise.
    angle = -rotation
    return (
        tile.rotate(angle, expand=True, fillcolor=255),
        mask.rotate(angle, expand=True, fillcolor=0) if mask is not None else None,
    )


def _measure_multiline(text: str, font: ImageFont.FreeTypeFont, spacing: int) -> tuple[int, int, int, int]:
    dummy = Image.new("L", (2, 2), 255)
    draw = ImageDraw.Draw(dummy)
    return draw.multiline_textbbox((0, 0), text or " ", font=font, spacing=spacing)


def _font_for_height(item: TextItem, font_path: str, target_height_px: int) -> tuple[ImageFont.FreeTypeFont, int, tuple[int, int, int, int]]:
    """Largest font whose complete multiline block fits the requested height."""
    lo = 4
    hi = max(lo, int(target_height_px))
    best_size = lo
    best_font = ImageFont.truetype(font_path, best_size)
    best_spacing = max(1, best_size // 5)
    best_bbox = _measure_multiline(item.text, best_font, best_spacing)
    while lo <= hi:
        size = (lo + hi) // 2
        font = ImageFont.truetype(font_path, size)
        spacing = max(1, size // 5)
        bbox = _measure_multiline(item.text, font, spacing)
        needed = max(1, bbox[3] - bbox[1]) + 2
        if needed <= target_height_px:
            best_size = size
            best_font = font
            best_spacing = spacing
            best_bbox = bbox
            lo = size + 1
        else:
            hi = size - 1
    return best_font, best_spacing, best_bbox


def _text_tile(item: TextItem) -> tuple[Image.Image, Image.Image]:
    font_path = resolve_font(item.family, item.bold)
    if item.autofit_height:
        target_height = max(6, mm_to_dots(item.size_mm))
        font, spacing, bbox = _font_for_height(item, font_path, target_height)
        w = max(1, bbox[2] - bbox[0] + 2)
        h = target_height
        y = max(1 - bbox[1], (target_height - (bbox[3] - bbox[1])) // 2 - bbox[1])
        pos = (1 - bbox[0], y)
    else:
        font_px = max(6, mm_to_dots(item.size_mm))
        font = ImageFont.truetype(font_path, font_px)
        spacing = max(1, font_px // 5)
        bbox = _measure_multiline(item.text, font, spacing)
        w = max(1, bbox[2] - bbox[0] + 2)
        h = max(1, bbox[3] - bbox[1] + 2)
        pos = (1 - bbox[0], 1 - bbox[1])

    tile = Image.new("L", (w, h), 255)
    mask = Image.new("L", (w, h), 0)
    td = ImageDraw.Draw(tile)
    md = ImageDraw.Draw(mask)
    td.multiline_text(pos, item.text or " ", font=font, fill=0, spacing=spacing)
    md.multiline_text(pos, item.text or " ", font=font, fill=255, spacing=spacing)
    return _rotate(tile, mask, item.rotation)


def _qr_tile(item: QRItem) -> tuple[Image.Image, Image.Image | None]:
    matrix = qr_matrix(item.data, item.ecc, item.border_modules)
    modules = len(matrix)
    if item.full_width:
        total_px = PRINTABLE_WIDTH_DOTS
    else:
        total_px = max(8, min(PRINTABLE_WIDTH_DOTS, mm_to_dots(item.requested_size_mm)))
    scale = total_px // modules
    if scale < 1:
        raise ValueError(
            f"QR payload is too dense for the E10 printable width ({modules} modules > {total_px} dots)."
        )
    qr_px = modules * scale
    tile = Image.new("L", (total_px, total_px), 255)
    draw = ImageDraw.Draw(tile)
    off = (total_px - qr_px) // 2
    for row, vals in enumerate(matrix):
        for col, dark in enumerate(vals):
            if dark:
                x0 = off + col * scale
                y0 = off + row * scale
                draw.rectangle((x0, y0, x0 + scale - 1, y0 + scale - 1), fill=0)
    return _rotate(tile, None, item.rotation)


def _image_tile(item: ImageItem) -> tuple[Image.Image, Image.Image | None]:
    if not item.png_b64:
        return Image.new("L", (1, 1), 255), None
    raw = base64.b64decode(item.png_b64.encode("ascii"))
    img = Image.open(io.BytesIO(raw)).convert("L")
    w = max(1, mm_to_dots(item.width_mm))
    h = max(1, mm_to_dots(item.height_mm))
    img = ImageOps.contain(img, (w, h), method=Image.Resampling.LANCZOS)
    tile = Image.new("L", (w, h), 255)
    x = (w - img.width) // 2
    y = (h - img.height) // 2
    tile.paste(img, (x, y))
    return _rotate(tile, None, item.rotation)


def _box_tile(item: BoxItem) -> tuple[Image.Image, Image.Image | None]:
    w = max(1, mm_to_dots(item.width_mm))
    h = max(1, mm_to_dots(item.height_mm))
    tile = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(tile)
    width = max(1, int(item.line_dots))
    d.rectangle((0, 0, w - 1, h - 1), outline=0, width=width)
    return _rotate(tile, None, item.rotation)


def _line_tile(item: LineItem) -> tuple[Image.Image, Image.Image | None]:
    w = max(1, mm_to_dots(item.width_mm))
    h = max(1, int(item.line_dots))
    tile = Image.new("L", (w, h), 0)
    return _rotate(tile, None, item.rotation)


def render_item_tile(item: Item) -> tuple[Image.Image, Image.Image | None]:
    if isinstance(item, TextItem):
        return _text_tile(item)
    if isinstance(item, QRItem):
        return _qr_tile(item)
    if isinstance(item, ImageItem):
        return _image_tile(item)
    if isinstance(item, BoxItem):
        return _box_tile(item)
    if isinstance(item, LineItem):
        return _line_tile(item)
    raise TypeError(type(item))


def image_item_from_file(path: str | Path) -> ImageItem:
    p = Path(path)
    img = Image.open(p).convert("RGBA")
    # Flatten alpha onto white so templates are self-contained and predictable.
    base = Image.new("RGBA", img.size, (255, 255, 255, 255))
    base.alpha_composite(img)
    rgb = base.convert("RGB")
    buf = io.BytesIO()
    rgb.save(buf, format="PNG", optimize=True)
    aspect = rgb.height / max(1, rgb.width)
    width_mm = PRINTABLE_WIDTH_MM
    height_mm = max(ONE_DOT_MM, width_mm * aspect)
    return ImageItem(
        png_b64=base64.b64encode(buf.getvalue()).decode("ascii"),
        name=p.name,
        width_mm=width_mm,
        height_mm=height_mm,
    )
