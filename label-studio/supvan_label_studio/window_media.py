from __future__ import annotations

from .printer_profiles import documented_family_for_queue, profile_for_queue


def should_apply_catalog_stock(profile, family, requested_width_mm: float) -> bool:
    """True only when a requested stock width has an exact catalog geometry.

    A saved/calibrated queue profile is production truth and must never be
    overwritten by a vendor default. Hardware-validated built-ins (currently the
    E10) are likewise immutable here. We also refuse to interpolate geometry for
    stock widths the vendor did not publish explicitly.
    """
    if profile is None or family is None:
        return False
    if not profile.built_in or profile.verified:
        return False
    requested = float(requested_width_mm)
    return any(abs(preset.stock_width_mm - requested) <= 0.30 for preset in family.geometry_presets)


class MainWindowMediaMixin:
    """Media/profile behaviors that sit between layout widgets and editor state."""

    def stock_changed(self, widget):
        if self._syncing:
            return
        before = self.snapshot()
        queue = self.doc.queue
        active_profile = profile_for_queue(queue, self.doc.stock_width_mm)
        family = documented_family_for_queue(queue)
        requested = float(widget.get_value())

        self.doc.stock_width_mm = requested
        self.preferences.stock_width_mm = requested
        self.doc.validate()

        if should_apply_catalog_stock(active_profile, family, requested):
            # profile_for_queue now sees the requested stock width and chooses the
            # exact vendor-published raster preset (for example Brother 12 mm ->
            # 70 dots). refresh_printer_profile applies/clamps it consistently.
            self.refresh_printer_profile()

        self.finish_edit(before, refresh_layers=False)
