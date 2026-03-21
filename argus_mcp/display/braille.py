"""Braille progress bar rendering for the installer display.

Extracted from internal/art/shard_rain_variants/common.py — provides the minimum
braille animation logic needed for parallel deployment progress bars.
"""

from __future__ import annotations

from rich.text import Text

BRAILLE_BASE = 0x2800
DOT_BITS = (0x01, 0x02, 0x04, 0x40, 0x80, 0x20, 0x10, 0x08)
SPARSE_MASKS = (
    0x00,
    0x01,
    0x02,
    0x04,
    0x08,
    0x10,
    0x20,
    0x40,
    0x80,
    0x03,
    0x18,
    0x24,
    0x42,
    0x81,
)
_MONO_PALETTE = ("#ffffff", "#d9dce6", "#9aa1b6", "#495167")


def braille(mask: int) -> str:
    return chr(BRAILLE_BASE + (mask & 0xFF))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _hash32(a: int, b: int, c: int) -> int:
    value = (a * 0x45D9F3B) ^ (b * 0x27D4EB2D) ^ (c * 0x165667B1)
    value ^= value >> 15
    value *= 0x2C1B3C6D
    value ^= value >> 12
    return value & 0xFFFFFFFF


def _base_shard_masks(frame: int, width: int, salt: int) -> list[int]:
    return [SPARSE_MASKS[_hash32(frame, i, salt) % len(SPARSE_MASKS)] for i in range(width)]


def _ordered_missing_bits(base_mask: int, index: int, salt: int) -> list[int]:
    missing = [bit for bit in DOT_BITS if not (base_mask & bit)]
    return sorted(missing, key=lambda bit: _hash32(index, salt, bit))


def _fill_mask_from_gaps(
    base_mask: int,
    local_progress: float,
    index: int,
    salt: int,
) -> int:
    if local_progress <= 0.0:
        return base_mask
    if local_progress >= 1.0:
        return 0xFF
    missing = _ordered_missing_bits(base_mask, index, salt)
    if not missing:
        return 0xFF
    add_count = max(1, round(local_progress * len(missing)))
    mask = base_mask
    for bit in missing[:add_count]:
        mask |= bit
    return mask


def _threshold_scattered(index: int, width: int) -> float:
    del width
    return 0.08 + 0.72 * ((_hash32(index, 211, 911) & 0xFFFF) / 0xFFFF)


def _solidify_progress(
    elapsed: float,
    rise_seconds: float,
    hold_seconds: float,
) -> float:
    cycle = rise_seconds + hold_seconds
    moment = elapsed % cycle
    if moment >= rise_seconds:
        return 1.0
    return moment / rise_seconds


def _style_for_mask(mask: int, frame: int, index: int, salt: int) -> str:
    if mask == 0:
        return "grey23"
    palette_index = (frame * 3 + index * 5 + mask + salt) % len(_MONO_PALETTE)
    if mask.bit_count() >= 5:
        return f"bold {_MONO_PALETTE[palette_index]}"
    return _MONO_PALETTE[palette_index]


def _build_mask_line(
    masks: list[int],
    frame: int,
    salt: int,
    monotone_style: str | None = None,
) -> Text:
    text = Text("[", style="bright_black")
    for index, mask in enumerate(masks):
        if mask == 0:
            style = "grey23"
        elif monotone_style is not None:
            style = monotone_style
        else:
            style = _style_for_mask(mask, frame, index, salt)
        text.append(braille(mask), style=style)
    text.append("]", style="bright_black")
    return text


def render_scattered_bar(
    elapsed: float,
    width: int = 17,
    *,
    monotone_style: str = "bold white",
    salt: int = 68,
) -> Text:
    """Animated scattered braille bar that solidifies over time.

    Used for remote backends and local backends without a build step.
    Cycles: 8.8s rise then 2.6s hold, scattered mode.
    """
    frame_rate = 5.4
    rise_seconds = 8.8
    hold_seconds = 2.6

    frame = int(elapsed * frame_rate)
    progress = _solidify_progress(elapsed, rise_seconds, hold_seconds)
    base_masks = _base_shard_masks(frame, width, salt=salt)
    masks: list[int] = []

    for index, base_mask in enumerate(base_masks):
        threshold = _threshold_scattered(index, width)
        local = _clamp01((progress - threshold) / 0.22)
        masks.append(_fill_mask_from_gaps(base_mask, local, index, salt + 100))

    return _build_mask_line(masks, frame, salt=salt, monotone_style=monotone_style)


def render_progress_bar(
    progress: float,
    width: int = 17,
    *,
    monotone_style: str = "bold white",
) -> Text:
    """Left-to-right fill bar based on a 0.0-1.0 progress value.

    Used for local backends with docker build progress (step X/Y).
    Fills braille cells from left (solid 0xFF) to right (empty) proportionally.
    """
    progress = _clamp01(progress)
    filled_exact = progress * width
    full_cells = int(filled_exact)
    partial = filled_exact - full_cells

    text = Text("[", style="bright_black")
    for i in range(width):
        if i < full_cells:
            text.append(braille(0xFF), style=monotone_style)
        elif i == full_cells and partial > 0:
            # Partial cell: fill dots proportional to partial fraction
            dot_count = max(1, round(partial * 8))
            mask = 0
            for bit in DOT_BITS[:dot_count]:
                mask |= bit
            text.append(braille(mask), style=monotone_style)
        else:
            text.append(braille(0x00), style="grey23")
    text.append("]", style="bright_black")
    return text


def render_solid_bar(
    width: int = 17,
    *,
    style: str = "bold white",
) -> Text:
    """solid bar for completed backends"""
    text = Text("[", style="bright_black")
    for _ in range(width):
        text.append(braille(0xFF), style=style)
    text.append("]", style="bright_black")
    return text


def render_empty_bar(width: int = 17) -> Text:
    """empty bar for pending backends"""
    text = Text("[", style="bright_black")
    for _ in range(width):
        text.append(braille(0x00), style="grey23")
    text.append("]", style="bright_black")
    return text
