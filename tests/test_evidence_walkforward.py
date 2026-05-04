import datetime as dt

from tradingagents.evidence.walkforward import build_walkforward_report


def _rows(count: int, start: str = "2020-01-01"):
    start_date = dt.datetime.strptime(start, "%Y-%m-%d").date()
    out = []
    for idx in range(count):
        day = start_date + dt.timedelta(days=idx)
        out.append(
            {
                "date": day.isoformat(),
                "edge_5d_pct": float((idx % 9) - 3),
                "edge_20d_pct": float((idx % 11) - 4),
            }
        )
    return out


def test_walkforward_deterministic_partial_mode():
    rows = _rows(350)
    report_one = build_walkforward_report(rows)
    report_two = build_walkforward_report(rows)

    assert report_one == report_two
    assert report_one["status"] == "PARTIAL_DATA"
    assert report_one["depth_mode"] == "PARTIAL"
    assert report_one["windows_count"] >= 1


def test_walkforward_status_complete_partial_and_insufficient():
    report_insufficient = build_walkforward_report(_rows(200))
    assert report_insufficient["status"] == "INSUFFICIENT_DEPTH"
    assert report_insufficient["windows_count"] == 0

    report_partial = build_walkforward_report(_rows(350))
    assert report_partial["status"] == "PARTIAL_DATA"

    report_complete = build_walkforward_report(_rows(1200))
    assert report_complete["status"] == "COMPLETE"
    assert report_complete["windows_count"] >= 1
