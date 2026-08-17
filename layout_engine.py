"""Generic, algorithm-independent sheet layout primitives.

This module deliberately knows nothing about project layer names, block names,
or any particular drawing. Algorithms provide measured bounding boxes and
semantic roles; the engine handles sheet regions, collision checks, packing,
and conservative auto-fit/auto-scale decisions.

Coordinates are in drawing units. ``Rect`` uses the usual CAD convention:
left/bottom/right/top.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import inf
from typing import Iterable, Sequence


EPS = 1e-9


@dataclass(frozen=True)
class Rect:
    left: float
    bottom: float
    right: float
    top: float

    @property
    def width(self) -> float:
        return max(0.0, self.right - self.left)

    @property
    def height(self) -> float:
        return max(0.0, self.top - self.bottom)

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center(self) -> tuple[float, float]:
        return ((self.left + self.right) / 2, (self.bottom + self.top) / 2)

    def translated(self, dx: float, dy: float) -> "Rect":
        return Rect(self.left + dx, self.bottom + dy, self.right + dx, self.top + dy)

    def scaled_about_center(self, factor: float) -> "Rect":
        cx, cy = self.center
        hw = self.width * factor / 2
        hh = self.height * factor / 2
        return Rect(cx - hw, cy - hh, cx + hw, cy + hh)

    def inset(self, margin: float) -> "Rect":
        return Rect(self.left + margin, self.bottom + margin,
                    self.right - margin, self.top - margin)

    def intersects(self, other: "Rect", gap: float = 0.0) -> bool:
        return not (
            self.right <= other.left + gap + EPS
            or other.right <= self.left + gap + EPS
            or self.top <= other.bottom + gap + EPS
            or other.top <= self.bottom + gap + EPS
        )

    def intersection_area(self, other: "Rect") -> float:
        width = max(0.0, min(self.right, other.right) - max(self.left, other.left))
        height = max(0.0, min(self.top, other.top) - max(self.bottom, other.bottom))
        return width * height

    def contains(self, other: "Rect", margin: float = 0.0) -> bool:
        return (
            other.left >= self.left + margin - EPS
            and other.bottom >= self.bottom + margin - EPS
            and other.right <= self.right - margin + EPS
            and other.top <= self.top - margin + EPS
        )


@dataclass
class LayoutItem:
    """A semantic item to be placed on a sheet.

    ``size`` is the measured footprint at the current scale. ``role`` is a
    semantic label such as ``main_view``, ``section``, ``table``, ``notes`` or
    ``stamp``; it is not a DXF layer or block name.
    """

    id: str
    role: str
    width: float
    height: float
    priority: int = 50
    min_scale: float = 0.25
    max_scale: float = 4.0
    scale: float = 1.0
    rect: Rect | None = None
    required: bool = True
    preferred_region: str | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def scaled_width(self) -> float:
        return self.width * self.scale

    @property
    def scaled_height(self) -> float:
        return self.height * self.scale

    @property
    def area(self) -> float:
        return self.scaled_width * self.scaled_height

    def footprint_at(self, scale: float, origin: tuple[float, float] = (0, 0)) -> Rect:
        x, y = origin
        return Rect(x, y, x + self.width * scale, y + self.height * scale)


@dataclass(frozen=True)
class Region:
    id: str
    rect: Rect
    role: str = "free"
    reserved: bool = False


@dataclass
class Collision:
    first: str
    second: str
    area: float
    kind: str = "overlap"


@dataclass
class PlacementResult:
    placed: list[str]
    unplaced: list[str]
    collisions: list[Collision]
    overflow: list[str]
    fill_ratio: float


@dataclass
class Sheet:
    """A sheet with reserved regions and placed semantic items."""

    id: str
    width: float
    height: float
    margin: float = 500.0
    regions: list[Region] = field(default_factory=list)
    items: list[LayoutItem] = field(default_factory=list)

    @property
    def frame(self) -> Rect:
        return Rect(0.0, 0.0, self.width, self.height)

    @property
    def usable(self) -> Rect:
        return self.frame.inset(self.margin)

    def reserve(self, region_id: str, rect: Rect, role: str = "reserved") -> Region:
        region = Region(region_id, rect, role=role, reserved=True)
        self.regions.append(region)
        return region

    def add(self, item: LayoutItem) -> LayoutItem:
        self.items.append(item)
        return item

    def occupied_rects(self, exclude: str | None = None) -> list[tuple[str, Rect]]:
        result: list[tuple[str, Rect]] = []
        for region in self.regions:
            if region.reserved:
                result.append((region.id, region.rect))
        for item in self.items:
            if item.rect is not None and item.id != exclude:
                result.append((item.id, item.rect))
        return result

    def collisions(self, gap: float = 0.0) -> list[Collision]:
        collisions: list[Collision] = []
        occupied = self.occupied_rects()
        for index, (first, rect_a) in enumerate(occupied):
            for second, rect_b in occupied[index + 1:]:
                if rect_a.intersects(rect_b, gap=gap):
                    collisions.append(Collision(first, second, rect_a.intersection_area(rect_b)))
        return collisions

    def overflow(self) -> list[str]:
        overflow: list[str] = []
        for item in self.items:
            if item.rect is None or not self.usable.contains(item.rect):
                overflow.append(item.id)
        return overflow

    def fill_ratio(self) -> float:
        usable_area = self.usable.area
        if usable_area <= EPS:
            return 0.0
        item_area = sum(item.rect.area for item in self.items if item.rect is not None)
        return min(1.0, item_area / usable_area)

    def _candidate_origins(self, item: LayoutItem, gap: float) -> list[tuple[float, float]]:
        """Generate deterministic candidate anchors around existing geometry."""
        usable = self.usable
        points = [(usable.left, usable.top - item.scaled_height)]
        occupied = self.occupied_rects(exclude=item.id)
        for _, rect in occupied:
            points.extend([
                (rect.right + gap, rect.bottom),
                (rect.left, rect.top + gap),
                (rect.right + gap, rect.top + gap),
            ])
        points.extend([
            (usable.left, usable.bottom),
            (usable.right - item.scaled_width, usable.bottom),
            (usable.right - item.scaled_width, usable.top - item.scaled_height),
        ])
        # Stable de-duplication keeps the output deterministic for CI.
        seen: set[tuple[float, float]] = set()
        unique: list[tuple[float, float]] = []
        for point in points:
            rounded = (round(point[0], 6), round(point[1], 6))
            if rounded not in seen:
                seen.add(rounded)
                unique.append(point)
        return unique

    def place(self, item: LayoutItem, gap: float = 250.0) -> bool:
        """Place one item without intersecting reserved or placed geometry."""
        for scale in _scale_candidates(item):
            item.scale = scale
            for origin in self._candidate_origins(item, gap):
                candidate = item.footprint_at(scale, origin)
                if not self.usable.contains(candidate):
                    continue
                if any(candidate.intersects(rect, gap=gap) for _, rect in self.occupied_rects(exclude=item.id)):
                    continue
                item.rect = candidate
                return True
        item.rect = None
        return False

    def auto_place(self, gap: float = 250.0) -> PlacementResult:
        """Place required/high-priority content first, then optional content."""
        ordered = sorted(self.items, key=lambda item: (-item.priority, item.id))
        placed: list[str] = []
        unplaced: list[str] = []
        for item in ordered:
            if self.place(item, gap=gap):
                placed.append(item.id)
            else:
                unplaced.append(item.id)
        collisions = self.collisions(gap=0.0)
        return PlacementResult(placed, unplaced, collisions, self.overflow(), self.fill_ratio())


def _scale_candidates(item: LayoutItem, steps: int = 12) -> list[float]:
    """Try current scale first, then progressively smaller/larger scales."""
    current = max(item.min_scale, min(item.max_scale, item.scale))
    values = [current]
    # Prefer shrinking when something does not fit; growing is handled later
    # by ``grow_to_fill`` once all required content has a valid placement.
    for index in range(1, steps + 1):
        values.append(max(item.min_scale, current * (0.92 ** index)))
    return list(dict.fromkeys(round(value, 6) for value in values))


def grow_to_fill(sheet: Sheet, item_ids: Sequence[str] | None = None,
                 target_fill: float = 0.72, max_scale_steps: int = 10,
                 gap: float = 250.0) -> bool:
    """Conservatively enlarge items while preserving collision-free layout.

    The function never enlarges an item beyond ``max_scale`` and only accepts
    a larger scale when all placed items remain inside the usable frame and no
    collisions are introduced. It is therefore safe to run after ``auto_place``.
    """
    selected = [item for item in sheet.items if item.rect is not None]
    if item_ids is not None:
        wanted = set(item_ids)
        selected = [item for item in selected if item.id in wanted]
    selected.sort(key=lambda item: (-item.priority, item.id))

    changed = False
    for item in selected:
        for _ in range(max_scale_steps):
            if sheet.fill_ratio() >= target_fill:
                return changed
            old_scale = item.scale
            new_scale = min(item.max_scale, round(old_scale * 1.08, 6))
            if new_scale <= old_scale + EPS:
                break
            old_rect = item.rect
            cx, cy = old_rect.center
            candidate = item.footprint_at(new_scale, (cx - item.width * new_scale / 2,
                                                        cy - item.height * new_scale / 2))
            if not sheet.usable.contains(candidate):
                break
            item.scale = new_scale
            item.rect = candidate
            if sheet.collisions(gap=gap):
                item.scale = old_scale
                item.rect = old_rect
                break
            changed = True
    return changed


def layout_sheet(sheet: Sheet, gap: float = 250.0, target_fill: float = 0.72) -> PlacementResult:
    """Convenience pipeline: place, then safely enlarge important views."""
    result = sheet.auto_place(gap=gap)
    if result.unplaced:
        return result
    grow_to_fill(sheet, target_fill=target_fill, gap=gap)
    return PlacementResult(
        [item.id for item in sheet.items if item.rect is not None],
        [item.id for item in sheet.items if item.rect is None],
        sheet.collisions(gap=0.0),
        sheet.overflow(),
        sheet.fill_ratio(),
    )


def collision_matrix(items: Iterable[LayoutItem]) -> list[Collision]:
    """Check arbitrary already-placed items without needing a Sheet."""
    placed = [(item.id, item.rect) for item in items if item.rect is not None]
    result: list[Collision] = []
    for index, (first, rect_a) in enumerate(placed):
        for second, rect_b in placed[index + 1:]:
            if rect_a.intersects(rect_b):
                result.append(Collision(first, second, rect_a.intersection_area(rect_b)))
    return result
