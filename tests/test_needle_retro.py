def test_compute_needle_retro_is_retired():
    from tradingagents.dealflow.needle_retro import compute_needle_retro

    report = compute_needle_retro(last=5)

    assert report["status"] == "retired"
    assert report["cycles_completed"] == 0
    assert report["opportunities"] == []
