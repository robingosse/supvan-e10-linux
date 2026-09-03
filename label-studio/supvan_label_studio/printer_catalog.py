from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GeometryPreset:
    """Vendor-published media/print geometry, not a Gosse hardware validation."""

    stock_width_mm: float
    printable_width_dots: int
    dots_per_mm: float
    nominal_dpi: int
    label: str = ""

    @property
    def printable_width_mm(self) -> float:
        return self.printable_width_dots / self.dots_per_mm


@dataclass(frozen=True)
class PrinterFamily:
    key: str
    vendor: str
    name: str
    models: tuple[str, ...]
    queue_patterns: tuple[str, ...]
    transport_strategy: str
    media_kind: str
    resolutions_dpi: tuple[int, ...]
    media_width_min_mm: float | None = None
    media_width_max_mm: float | None = None
    geometry_presets: tuple[GeometryPreset, ...] = ()
    default_geometry_index: int = 0
    evidence: str = "vendor-documented"
    notes: str = ""

    def matches_queue(self, queue: str) -> bool:
        text = str(queue or "").strip().lower()
        return bool(text) and any(re.search(pattern, text, re.I) for pattern in self.queue_patterns)

    @property
    def default_geometry(self) -> GeometryPreset | None:
        if not self.geometry_presets:
            return None
        index = min(max(0, self.default_geometry_index), len(self.geometry_presets) - 1)
        return self.geometry_presets[index]

    def geometry_for_stock(self, stock_width_mm: float | None) -> GeometryPreset | None:
        """Return an exact documented stock preset, otherwise the family default.

        We deliberately do not interpolate printable margins between media sizes.
        An exact preset is used only when the vendor publishes that geometry.
        """
        if not self.geometry_presets:
            return None
        if stock_width_mm is not None:
            target = float(stock_width_mm)
            exact = min(self.geometry_presets, key=lambda item: abs(item.stock_width_mm - target))
            if abs(exact.stock_width_mm - target) <= 0.30:
                return exact
        return self.default_geometry

    @property
    def capability_summary(self) -> str:
        dpi = "/".join(str(value) for value in self.resolutions_dpi) + " dpi"
        if self.media_width_min_mm is not None and self.media_width_max_mm is not None:
            media = f"{self.media_width_min_mm:g}–{self.media_width_max_mm:g} mm media"
        elif self.media_width_max_mm is not None:
            media = f"up to {self.media_width_max_mm:g} mm media"
        else:
            media = self.media_kind
        geometry = self.default_geometry
        if geometry:
            geom = f"{geometry.printable_width_mm:.2f} mm documented printable band"
        else:
            geom = "printable band not asserted"
        return f"{self.vendor} {self.name} · {dpi} · {media} · {geom} · {self.transport_strategy}"


BROTHER_180_DPM = 180.0 / 25.4
DYMO_300_DPM = 300.0 / 25.4


# The catalog is intentionally conservative.  Geometry is included only where a
# vendor publishes an effective/max print width or an exact raster table.  A
# built-in catalog entry means "documented capability", not "physically tested
# by Gosse & Co."; the existing SUPVAN E10 profile remains the only built-in
# hardware-validated path until real-printer acceptance tests are performed.
BUILTIN_PRINTER_FAMILIES: tuple[PrinterFamily, ...] = (
    PrinterFamily(
        key="brother-pt-p710bt",
        vendor="Brother",
        name="P-touch Cube Plus PT-P710BT",
        models=("PT-P710BT",),
        queue_patterns=(r"brother.*p[-_ ]?710", r"pt[-_ ]?p?710bt", r"p[-_ ]?touch.*710"),
        transport_strategy="CUPS raster; native Brother raster adapter eligible",
        media_kind="TZe continuous tape",
        resolutions_dpi=(180, 360),
        media_width_min_mm=3.5,
        media_width_max_mm=24.0,
        geometry_presets=(
            GeometryPreset(3.5, 24, BROTHER_180_DPM, 180, "TZe 3.5 mm"),
            GeometryPreset(6.0, 32, BROTHER_180_DPM, 180, "TZe 6 mm"),
            GeometryPreset(9.0, 50, BROTHER_180_DPM, 180, "TZe 9 mm"),
            GeometryPreset(12.0, 70, BROTHER_180_DPM, 180, "TZe 12 mm"),
            GeometryPreset(18.0, 112, BROTHER_180_DPM, 180, "TZe 18 mm"),
            GeometryPreset(24.0, 128, BROTHER_180_DPM, 180, "TZe 24 mm"),
        ),
        default_geometry_index=5,
        notes="Brother publishes exact PT-P710BT TZe raster geometry. Native raster commands can print without a vendor driver, including from Linux.",
    ),
    PrinterFamily(
        key="niimbot-b1",
        vendor="NIIMBOT",
        name="B1",
        models=("B1",),
        queue_patterns=(r"niimbot.*\bb1\b", r"\bb1[-_ ]?niimbot\b"),
        transport_strategy="CUPS if installed; native Bluetooth/USB adapter experimental",
        media_kind="die-cut direct thermal labels",
        resolutions_dpi=(203,),
        media_width_min_mm=20.0,
        media_width_max_mm=50.0,
        geometry_presets=(GeometryPreset(50.0, 384, 8.0, 203, "B1 maximum effective width"),),
        notes="NIIMBOT publishes a 48 mm effective print width at 203 dpi. Direct protocol work is community-documented and must remain experimental until hardware validation.",
    ),
    PrinterFamily(
        key="dymo-labelwriter-550",
        vendor="DYMO",
        name="LabelWriter 550 / 550 Turbo",
        models=("LabelWriter 550", "LabelWriter 550 Turbo"),
        queue_patterns=(r"dymo.*label.?writer.*550", r"label.?writer.*550"),
        transport_strategy="official Linux/CUPS driver; native raster protocol documented",
        media_kind="die-cut/continuous direct thermal labels",
        resolutions_dpi=(300,),
        media_width_max_mm=62.0,
        # DYMO's user guide states a 56 mm maximum print width.  661 dots is the
        # nearest 300-dpi raster width at or below that published limit.  The
        # technical reference also documents the 672-dot physical print head.
        geometry_presets=(GeometryPreset(62.0, 661, DYMO_300_DPM, 300, "maximum published print width"),),
        notes="DYMO publishes Linux drivers and the LabelWriter 550 raster command protocol. Hardware print head is 672 dots; documented maximum print width is 56 mm.",
    ),
    PrinterFamily(
        key="zebra-zd421-203",
        vendor="Zebra",
        name="ZD421 203 dpi",
        models=("ZD421",),
        queue_patterns=(r"zebra.*zd[-_ ]?421", r"\bzd[-_ ]?421\b"),
        transport_strategy="CUPS/IPP or raw ZPL II",
        media_kind="roll/fanfold direct thermal or thermal-transfer labels",
        resolutions_dpi=(203, 300),
        media_width_min_mm=15.0,
        media_width_max_mm=108.0,
        geometry_presets=(GeometryPreset(108.0, 832, 8.0, 203, "ZD421 203 dpi maximum print width"),),
        notes="Zebra publishes a 104 mm maximum print width at 203 dpi and supports ZPL II/EPL2. A 300 dpi queue should be configured as a separate custom profile until its resolution is positively identified.",
    ),
    PrinterFamily(
        key="rollo-x1040-wireless",
        vendor="Rollo",
        name="X1040 Wireless",
        models=("X1040 Wireless",),
        queue_patterns=(r"rollo.*x[-_ ]?1040", r"rollo.*wireless", r"\bx[-_ ]?1040\b"),
        transport_strategy="driverless IPP/AirPrint over Wi-Fi",
        media_kind="direct thermal labels",
        resolutions_dpi=(203,),
        media_width_min_mm=40.0,
        media_width_max_mm=104.0,
        geometry_presets=(),
        notes="Rollo publishes supported media width and 203 dpi, but not a trustworthy exact printable band on the product page. Studio therefore refuses to invent one; configure/verify the physical band per queue.",
    ),
)


def family_for_queue(queue: str) -> PrinterFamily | None:
    for family in BUILTIN_PRINTER_FAMILIES:
        if family.matches_queue(queue):
            return family
    return None


def family_by_key(key: str) -> PrinterFamily | None:
    key = str(key or "").strip().lower()
    return next((family for family in BUILTIN_PRINTER_FAMILIES if family.key.lower() == key), None)


def builtin_family_keys() -> tuple[str, ...]:
    return tuple(family.key for family in BUILTIN_PRINTER_FAMILIES)
