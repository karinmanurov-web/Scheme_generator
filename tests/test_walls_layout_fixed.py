from algo_walls_layout_fixed import _fit_scale


def test_wall_scale_is_large_enough_for_real_fixture_extents():
    # The real wall fixture is roughly 52 x 53 thousand drawing units.
    # A3 must therefore use an engineering denominator much larger than 1.
    assert _fit_scale(51693.879, 53278.437) == 200.0


def test_wall_scale_stays_at_one_for_small_geometry():
    assert _fit_scale(300.0, 200.0) == 1.0
