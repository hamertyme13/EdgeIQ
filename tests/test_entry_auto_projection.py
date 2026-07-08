from analytics.projection import auto_projection


def test_auto_projection_adds_small_edge_from_line():
    projection = auto_projection(line=20.5, trending_count=100_000)

    assert projection > 20.5
    assert projection <= 22.0


def test_auto_projection_handles_zero_line():
    assert auto_projection(line=0, trending_count=100_000) == 0.0
