from datetime import date
import csv

from tradingagents.research.fundamental.src.panel.normalize import normalize_complete_panel_rows
from tradingagents.research.fundamental.src.panel.exporter import build_complete_panel


def _facts_with_different_financials():
    return {
        "AAA": {
            "facts": {
                "us-gaap": {
                    "Revenues": {"units": {"USD": [{"filed": "2026-05-01", "end": "2026-03-31", "val": 999}]}},
                    "NetIncomeLoss": {"units": {"USD": [{"filed": "2026-05-01", "end": "2026-03-31", "val": 888}]}},
                    "Assets": {"units": {"USD": [{"filed": "2026-05-01", "end": "2026-03-31", "val": 777}]}},
                    "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [{"filed": "2026-05-01", "end": "2026-03-31", "val": 666}]}},
                    "NetCashProvidedByUsedInInvestingActivities": {"units": {"USD": [{"filed": "2026-05-01", "end": "2026-03-31", "val": 555}]}},
                    "NetCashProvidedByUsedInFinancingActivities": {"units": {"USD": [{"filed": "2026-05-01", "end": "2026-03-31", "val": 444}]}},
                }
            },
            "entityName": "AAA Inc",
            "cik": "1",
        }
    }


def _facts_with_future_only_financials():
    facts = _facts_with_different_financials()
    for concept in facts["AAA"]["facts"]["us-gaap"].values():
        for values in concept["units"].values():
            for item in values:
                item["filed"] = "2026-06-01"
                item["val"] = 999
    return facts


def test_normalize_does_not_rewrite_scored_financial_values():
    rows = [
        {
            "ticker": "AAA",
            "quarter": "2026Q2",
            "entry_open_date": "2026-05-12",
            "pre_llm_fundamental_score": "5",
            "revenue_value": "100",
            "net_income_value": "10",
            "assets_value": "500",
            "operating_cash_flow_value": "20",
            "investing_cash_flow_value": "-5",
            "financing_cash_flow_value": "-2",
        }
    ]

    out, summary = normalize_complete_panel_rows(
        rows,
        source_name="daily_final_scores",
        facts_by_ticker=_facts_with_different_financials(),
        as_of=date(2026, 5, 12),
    )

    row = out[0]
    assert row["revenue_value"] == "100"
    assert row["net_income_value"] == "10"
    assert row["assets_value"] == "500"
    assert row["operating_cash_flow_value"] == "20"
    assert row["investing_cash_flow_value"] == "-5"
    assert row["financing_cash_flow_value"] == "-2"
    assert row["score_recompute_required_flag"] == "1"
    assert row["score_recompute_reason"] == "financial_values_changed_after_scoring"
    assert summary["financial_values"]["rows_with_score_recompute_required"] == 1


def test_scored_rows_do_not_use_relaxed_future_facts_for_panel_comparison():
    rows = [
        {
            "ticker": "AAA",
            "quarter": "2026Q2",
            "entry_open_date": "2026-05-12",
            "pre_llm_fundamental_score": "5",
            "revenue_value": "100",
            "net_income_value": "10",
            "assets_value": "500",
            "operating_cash_flow_value": "20",
            "investing_cash_flow_value": "-5",
            "financing_cash_flow_value": "-2",
        }
    ]

    out, summary = normalize_complete_panel_rows(
        rows,
        source_name="daily_final_scores",
        facts_by_ticker=_facts_with_future_only_financials(),
        as_of=date(2026, 5, 12),
        allow_relaxed_filed_date=True,
    )

    assert out[0]["score_recompute_required_flag"] == "0"
    assert summary["financial_values"]["rows_with_relaxed_filed_date"] == 0


def test_complete_panel_validation_fails_post_score_financial_rewrite(tmp_path):
    run_root = tmp_path / "run"
    run_root.mkdir()
    final_scores = run_root / "fundamental_final_scores_2026Q2.csv"
    rows = [
        {
            "ticker": "AAA",
            "quarter": "2026Q2",
            "entry_open_date": "2026-05-12",
            "pre_llm_fundamental_score": "5",
            "revenue_value": "100",
            "net_income_value": "10",
            "assets_value": "500",
            "operating_cash_flow_value": "20",
            "investing_cash_flow_value": "-5",
            "financing_cash_flow_value": "-2",
        }
    ]
    with final_scores.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    result = build_complete_panel(
        run_root=run_root,
        output_root=tmp_path / "panel",
        quarter="2026Q2",
        as_of="2026-05-12",
        facts_by_ticker=_facts_with_different_financials(),
    )

    assert result["validation"]["passed"] is False
    assert any(error["code"] == "post_score_financial_rewrite" for error in result["validation"]["errors"])
