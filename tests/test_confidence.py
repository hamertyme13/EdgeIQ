from analytics.prop_metrics import calculate_directional_edge


def test_directional_edge_is_symmetric_for_over_and_under():
    assert calculate_directional_edge(20.5, 22.0, "Over") == 1.5
    assert calculate_directional_edge(20.5, 19.0, "Under") == 1.5
