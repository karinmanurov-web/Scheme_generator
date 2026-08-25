from layout_engine import LayoutItem, Rect, Sheet, collision_matrix, layout_sheet


def test_rect_collision_and_containment():
    a = Rect(0, 0, 100, 100)
    b = Rect(50, 50, 150, 150)
    c = Rect(100, 100, 200, 200)
    assert a.intersects(b)
    assert not a.intersects(c)
    assert Rect(0, 0, 200, 200).contains(b)
    assert a.intersection_area(b) == 2500


def test_sheet_places_items_without_collision():
    sheet = Sheet("A1", width=10000, height=7000, margin=500)
    sheet.reserve("stamp", Rect(7000, 500, 9500, 1800), role="stamp")
    sheet.add(LayoutItem("main", "main_view", 5000, 3000, priority=100, max_scale=1.2))
    sheet.add(LayoutItem("table", "table", 1800, 1200, priority=90, max_scale=1.1))
    sheet.add(LayoutItem("notes", "notes", 2200, 800, priority=70, max_scale=1.0))

    result = layout_sheet(sheet, gap=150, target_fill=0.45)

    assert not result.unplaced
    assert not result.collisions
    assert not result.overflow
    assert result.fill_ratio > 0
    assert all(item.rect is not None for item in sheet.items)
    assert all(not item.rect.intersects(Rect(7000, 500, 9500, 1800), gap=150)
               for item in sheet.items)


def test_layout_shrinks_when_initial_size_does_not_fit():
    sheet = Sheet("A3", width=1000, height=800, margin=50)
    item = sheet.add(LayoutItem("large", "main_view", 1200, 900, min_scale=0.4, scale=1.0))

    result = layout_sheet(sheet, gap=20)

    assert not result.unplaced
    assert item.scale < 1.0
    assert item.rect is not None
    assert sheet.usable.contains(item.rect)
    assert not sheet.collisions()


def test_collision_matrix_is_independent_of_sheet():
    a = LayoutItem("a", "view", 100, 100, rect=Rect(0, 0, 100, 100))
    b = LayoutItem("b", "table", 100, 100, rect=Rect(80, 20, 180, 120))
    c = LayoutItem("c", "notes", 50, 50, rect=Rect(300, 300, 350, 350))
    collisions = collision_matrix([a, b, c])
    assert [(x.first, x.second) for x in collisions] == [("a", "b")]
