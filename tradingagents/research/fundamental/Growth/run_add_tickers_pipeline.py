from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
GROWTH = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(GROWTH) not in sys.path:
    sys.path.insert(0, str(GROWTH))

from add_ticker_to_universe_pipeline import (
    build_pre_llm_inputs,
    build_xbrl_rows,
    component_scores,
    current_quarter,
    ensure_companyfacts,
    ensure_price_cache,
    quarter_range,
    sec_ticker_info,
    tier_labels,
)
from build_pre_llm_fundamental_score import load_price_panels, return_fields, write_csv
from spec_convex_llm_testset import first_semicolon_value
from run_hp_research_llm_pipeline import (
    DEFAULT_COMBINED,
    DEFAULT_COMBINED_ALL,
    DEFAULT_COMBINED_ALL_SUMMARY,
    DEFAULT_COMBINED_SUMMARY,
    DEFAULT_HP_POST,
    DEFAULT_POST_TIER,
    DEFAULT_PRE_LLM,
    DEFAULT_RANK,
    DEFAULT_RANK_SUMMARY,
    _merge_and_rank,
    _recompute_tier0_bucket,
)
from src.config.cache_paths import market_cache_root
from src.features.hp_subtiers import HP_LABELS, add_hp_subtiers
from src.features.repricing_momentum import RM_LABELS, add_repricing_momentum


BASE = ROOT / "Growth" / "earnings_8k_sec_parser"
ADD_DIR = BASE / "add_ticker"


def _run(cmd: list[str], *, dry_run: bool = False) -> None:
    printable = " ".join(cmd)
    print(printable, flush=True)
    if dry_run:
        return
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    subprocess.run(cmd, cwd=ROOT, check=True, env=env)


def _read(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _quarter_sort(value: Any) -> int:
    text = str(value or "").strip()
    try:
        year, quarter = text.split("Q", maxsplit=1)
        return int(year) * 10 + int(quarter)
    except (TypeError, ValueError):
        return 0


def _parse_tickers(value: str) -> list[str]:
    tickers = []
    for item in value.replace("\n", ",").split(","):
        ticker = item.strip().upper()
        if ticker and ticker not in tickers:
            tickers.append(ticker)
    return tickers


def _write_universe(path: Path, rows: list[dict[str, str]]) -> None:
    write_csv(path, [{"ticker": row["ticker"], "cik": row["cik"]} for row in rows])


def _append_pre_llm(master_path: Path, add_rows: list[dict[str, Any]]) -> pd.DataFrame:
    master = _read(master_path)
    new = pd.DataFrame(add_rows)
    if master.empty and not new.empty:
        raise SystemExit(f"empty_master_pre_llm_refusing_overwrite:{master_path}")
    if master.empty:
        combined = new
    elif new.empty:
        combined = master
    else:
        cols = list(dict.fromkeys([*master.columns, *new.columns]))
        combined = pd.concat(
            [master.reindex(columns=cols, fill_value=""), new.reindex(columns=cols, fill_value="")],
            ignore_index=True,
        )
    if combined.empty:
        return combined
    combined["ticker"] = combined["ticker"].astype(str).str.upper().str.strip()
    combined["quarter_sort"] = combined["quarter"].map(_quarter_sort)
    combined = combined.sort_values(["ticker", "quarter_sort"]).drop_duplicates(["quarter", "ticker"], keep="last")
    return _recompute_pre_llm_derived(combined)


def _label_flags(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col, label in HP_LABELS.items():
        out[col] = out[col].map(lambda value: label if bool(value) else "")
    for col, label in RM_LABELS.items():
        out[col] = out[col].map(lambda value: label if bool(value) else "")
    for col in [
        "hp1_LLM_best",
        "hp2_LLM_best",
        "hp2_watch_LLM_best",
        "hp3_theme_confirmed",
        "hp4_LLM_supported",
        "hp_LLM_best",
    ]:
        if col in out.columns:
            out[col] = out[col].map(lambda value: int(bool(value)))
    return out


def _recompute_pre_llm_derived(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["quarter_sort"] = out["quarter"].map(_quarter_sort)
    out = out.sort_values(["ticker", "quarter_sort"]).reset_index(drop=True)
    for col in ["entry_open", "pre_llm_fundamental_score"]:
        out[col] = _to_numeric(out[col]) if col in out.columns else pd.NA
    out["prior_entry_open"] = out.groupby("ticker")["entry_open"].shift(1)
    out["entry_qoq_pct"] = ((out["entry_open"] / out["prior_entry_open"]) - 1) * 100
    out.loc[out["prior_entry_open"].isna() | out["prior_entry_open"].eq(0), "entry_qoq_pct"] = pd.NA
    out["prior_pre_llm_fundamental_score"] = out.groupby("ticker")["pre_llm_fundamental_score"].shift(1)
    out["score_change"] = out["pre_llm_fundamental_score"] - out["prior_pre_llm_fundamental_score"]

    hp = add_hp_subtiers(out.copy())
    rm = add_repricing_momentum(hp.copy())
    labeled = _label_flags(rm)
    for col in [
        *HP_LABELS,
        *RM_LABELS,
        "prior_entry_open",
        "prior_entry_qoq_pct",
        "market_repricing_score",
        "force_llm_extraction",
        "repricing_started",
        "repricing_confirmed",
        "positive_repricing_status",
        "theme_ai_data_center",
        "theme_ai_optical_networking",
        "theme_semiconductor_materials",
        "theme_compound_semiconductor",
        "theme_photonics",
        "theme_critical_materials",
        "theme_driver_summary",
        "theme_semicap_datacenter_confirmed",
        "theme_score",
        "theme_confidence",
        "hp1_LLM_best",
        "hp2_LLM_best",
        "hp2_watch_LLM_best",
        "hp3_theme_confirmed",
        "hp4_LLM_supported",
        "hp_LLM_best",
        "hp_structure_score",
    ]:
        if col in labeled.columns:
            out[col] = labeled[col]
    out = _recompute_tier0_bucket(out)

    false_series = pd.Series([False] * len(out), index=out.index)
    tier0 = (
        out.get("tier_0_bucket", pd.Series([""] * len(out), index=out.index)).astype(str).str.strip().ne("")
        | out.get("tier_bucket", pd.Series([""] * len(out), index=out.index)).astype(str).str.strip().ne("")
    )
    tier1 = out["tier_1_bucket"].astype(str).str.strip().ne("") if "tier_1_bucket" in out.columns else false_series
    tier2 = out["tier_2_bucket"].astype(str).str.strip().ne("") if "tier_2_bucket" in out.columns else false_series
    tier3 = out["tier_3_bucket"].astype(str).str.strip().ne("") if "tier_3_bucket" in out.columns else false_series
    tier4 = out["tier_4_bucket"].astype(str).str.strip().ne("") if "tier_4_bucket" in out.columns else false_series
    hp_prod = out["hp_production_extension"].astype(str).str.strip().ne("") if "hp_production_extension" in out.columns else false_series
    hp_research = out["hp_research_extension"].astype(str).str.strip().ne("") if "hp_research_extension" in out.columns else false_series
    rm_research = out["repricing_momentum_extension"].astype(str).str.strip().ne("") if "repricing_momentum_extension" in out.columns else false_series
    repricing_started = pd.to_numeric(out.get("repricing_started", false_series), errors="coerce").fillna(0).astype(int).eq(1)
    repricing_confirmed = pd.to_numeric(out.get("repricing_confirmed", false_series), errors="coerce").fillna(0).astype(int).eq(1)
    out["force_llm_extraction"] = (
        tier1 | tier2 | tier3 | tier4 | hp_prod | hp_research | rm_research | repricing_started | repricing_confirmed
    ).map(lambda value: 1 if bool(value) else 0)
    out["extended_candidate_universe"] = (tier0 | hp_prod).map(lambda value: "Extended candidate universe" if value else "")
    out["extended_research_universe"] = (tier0 | hp_research).map(lambda value: "Extended research universe" if value else "")

    def _fmt_float(value, digits: int = 2):
        numeric = pd.to_numeric(value, errors="coerce")
        return "" if pd.isna(numeric) else round(float(numeric), digits)

    out["entry_qoq_pct"] = out["entry_qoq_pct"].map(lambda value: _fmt_float(value, 2))
    if "prior_entry_open" in out.columns:
        out["prior_entry_open"] = out["prior_entry_open"].map(lambda value: _fmt_float(value, 6))
    if "prior_entry_qoq_pct" in out.columns:
        out["prior_entry_qoq_pct"] = out["prior_entry_qoq_pct"].map(lambda value: _fmt_float(value, 2))
    out["score_change"] = out["score_change"].map(
        lambda value: ""
        if pd.isna(pd.to_numeric(value, errors="coerce"))
        else int(float(value))
        if float(value).is_integer()
        else round(float(value), 2)
    )
    out = out.drop(columns=["quarter_sort", "prior_entry_open", "prior_pre_llm_fundamental_score"], errors="ignore")
    return out


def _write_pre_master(df: pd.DataFrame, path: Path) -> None:
    preferred = [
        "quarter",
        "ticker",
        "revenue_bucket",
        "profitability_score",
        "operating_cash_flow_score",
        "fcf_proxy_score",
        "financing_dependence_score",
        "asset_efficiency_score",
        "pre_llm_fundamental_score",
        "score_change",
        "pre_llm_fundamental_bucket",
        "tradable_date",
        "entry_open",
        "prior_entry_open",
        "entry_qoq_pct",
        "prior_entry_qoq_pct",
        "return_10d_pct",
        "return_20d_pct",
        "return_30d_pct",
        "return_60d_pct",
        "return_90d_pct",
        "pre_llm_fundamental_missing_fields",
        "tier_bucket",
        "hp0_high_price_broad",
        "hp1_quality_pullback",
        "hp2_dislocation_momentum_priority",
        "hp2_dislocation_momentum_watch",
        "hp3_large_quality_theme_exception",
        "hp4_score_reacceleration_watch",
        "rm1_low_price_dislocation_momentum",
        "rm2_weak_acceleration",
        "rm3_mid_price_dislocation_momentum",
        "rm4_persistent_repricing_wave",
        "repricing_momentum_priority",
        "repricing_momentum_extension",
        "market_repricing_score",
        "force_llm_extraction",
        "repricing_started",
        "repricing_confirmed",
        "positive_repricing_status",
        "theme_ai_data_center",
        "theme_ai_optical_networking",
        "theme_semiconductor_materials",
        "theme_compound_semiconductor",
        "theme_photonics",
        "theme_critical_materials",
        "theme_driver_summary",
        "theme_semicap_datacenter_confirmed",
        "theme_score",
        "theme_confidence",
        "extended_candidate_universe",
        "extended_research_universe",
        "tier_1_bucket",
        "tier_2_bucket",
        "tier_3_bucket",
        "tier_4_bucket",
        "tier_0_bucket",
        "hp_production_extension",
        "hp_research_extension",
        "hp1_LLM_best",
        "hp2_LLM_best",
        "hp2_watch_LLM_best",
        "hp3_theme_confirmed",
        "hp4_LLM_supported",
        "hp_LLM_best",
        "hp_structure_score",
    ]
    cols = list(dict.fromkeys([*preferred, *df.columns]))
    df.reindex(columns=cols, fill_value="").to_csv(path, index=False)


def _run_quarter_fetch(quarter: str, universe: Path, work_dir: Path, args: argparse.Namespace) -> tuple[Path, Path]:
    audit = work_dir / f"sec_quarter_cache_audit_add_tickers_{quarter}.csv"
    fetch = work_dir / f"sec_quarter_cache_fetch_report_add_tickers_{quarter}.csv"
    _run(
        [
            str(ROOT / ".venv" / "bin" / "python"),
            "Growth/sec_quarter_cache_manager.py",
            "--quarter",
            quarter,
            "--universe",
            str(universe),
            "--audit-output",
            str(audit),
            "--fetch-report",
            str(fetch),
            "--sleep",
            str(args.sleep),
            "--retries",
            "3",
            "--checkpoint-every",
            str(args.checkpoint_every),
            "--metadata-source",
            "hybrid",
            "--issuer-mode",
            "auto",
            "--ticker-timeout-seconds",
            str(args.ticker_timeout_seconds),
            "--resume-existing",
        ],
        dry_run=args.dry_run,
    )
    return audit, fetch


def _build_pre_rows(tickers: set[str], quarters: list[str], work_dir: Path) -> list[dict[str, Any]]:
    all_rows: list[dict[str, Any]] = []
    prices = load_price_panels()
    for quarter in quarters:
        audit = work_dir / f"sec_quarter_cache_audit_add_tickers_{quarter}.csv"
        if not audit.exists():
            continue
        for ticker in sorted(tickers):
            universe, events, _, ready_count = build_pre_llm_inputs(ticker, quarter, audit, work_dir)
            if ready_count == 0:
                continue
            xbrl_path = work_dir / f"xbrl_universal_features_through_ocf_{ticker}_{quarter}.csv"
            xbrl_rows = build_xbrl_rows(universe, quarter, xbrl_path)
            event_rows = pd.read_csv(events, dtype=str, keep_default_na=False).to_dict("records")
            event_date = first_semicolon_value(event_rows[0].get("event_dates", "")) if event_rows else ""
            rows: list[dict[str, Any]] = []
            for row in xbrl_rows:
                returns = return_fields(prices.get(ticker), event_date)
                score = component_scores(row)
                out = {
                    "quarter": row.get("quarter", ""),
                    "ticker": ticker,
                    "revenue_bucket": row.get("revenue_bucket", ""),
                    **score,
                    "tradable_date": returns.get("tradable_date", ""),
                    "entry_open": returns.get("entry_open", ""),
                    "return_10d_pct": returns.get("return_10d_pct", ""),
                    "return_20d_pct": returns.get("return_20d_pct", ""),
                    "return_30d_pct": returns.get("return_30d_pct", ""),
                    "return_60d_pct": returns.get("return_60d_pct", ""),
                    "return_90d_pct": returns.get("return_90d_pct", ""),
                }
                out = {**out, **tier_labels(out)}
                rows.append(out)
            score_path = work_dir / f"pre_llm_fundamental_score_{ticker}_{quarter}.csv"
            write_csv(score_path, rows)
            all_rows.extend(rows)
    return all_rows


def _run_llm_for_added(args: argparse.Namespace, batch_dir: Path, tickers: list[str]) -> None:
    if not args.run_llm:
        return
    prefix = batch_dir / f"llm_hp_research_{args.model.replace('.', '')}_{args.reasoning_effort}"
    _run(
        [
            str(ROOT / ".venv" / "bin" / "python"),
            "Growth/run_hp_research_llm_pipeline.py",
            "--output-prefix",
            str(prefix),
            "--tickers",
            ",".join(tickers),
            "--model",
            args.model,
            "--reasoning-effort",
            args.reasoning_effort,
            "--batch-size",
            str(args.batch_size),
        ],
        dry_run=args.dry_run,
    )


def _write_report(
    path: Path,
    requested: list[str],
    resolved: list[dict[str, str]],
    failures: dict[str, str],
    master: pd.DataFrame,
    add_rows: list[dict[str, Any]],
) -> None:
    add_df = pd.DataFrame(add_rows)
    rows = []
    for ticker in requested:
        ticker_rows = master[master["ticker"].astype(str).str.upper().eq(ticker)] if not master.empty else pd.DataFrame()
        new_rows = add_df[add_df["ticker"].astype(str).str.upper().eq(ticker)] if not add_df.empty else pd.DataFrame()
        info = next((row for row in resolved if row["ticker"] == ticker), {})
        rows.append(
            {
                "ticker": ticker,
                "cik": info.get("cik", ""),
                "status": "failed" if ticker in failures else "ok",
                "failure_reason": failures.get(ticker, ""),
                "new_pre_llm_rows": len(new_rows),
                "total_rows_in_master": len(ticker_rows),
                "tier0_rows": int(ticker_rows.get("tier_bucket", pd.Series(dtype=str)).astype(str).str.strip().ne("").sum()) if not ticker_rows.empty else 0,
                "hp_production_rows": int(ticker_rows.get("hp_production_extension", pd.Series(dtype=str)).astype(str).str.strip().ne("").sum()) if not ticker_rows.empty else 0,
                "hp_research_rows": int(ticker_rows.get("hp_research_extension", pd.Series(dtype=str)).astype(str).str.strip().ne("").sum()) if not ticker_rows.empty else 0,
            }
        )
    write_csv(path, rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add one or more tickers to the live walkforward universe")
    parser.add_argument("--tickers", required=True, help="Comma-separated tickers")
    parser.add_argument("--start-quarter", default="2021Q4")
    parser.add_argument("--end-quarter", default="latest")
    parser.add_argument("--master-pre-llm", type=Path, default=DEFAULT_PRE_LLM)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--sleep", type=float, default=0.1)
    parser.add_argument("--checkpoint-every", type=int, default=10)
    parser.add_argument("--ticker-timeout-seconds", type=int, default=180)
    parser.add_argument("--price-period", default="max")
    parser.add_argument("--force-facts", action="store_true")
    parser.add_argument("--force-prices", action="store_true")
    parser.add_argument("--refresh-sec-map", action="store_true")
    parser.add_argument("--run-llm", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tickers = _parse_tickers(args.tickers)
    if not tickers:
        raise SystemExit("missing_tickers")
    end = current_quarter() if args.end_quarter == "latest" else args.end_quarter
    quarters = quarter_range(args.start_quarter, end)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_dir = ADD_DIR / f"batch_{stamp}"
    batch_dir.mkdir(parents=True, exist_ok=True)

    resolved: list[dict[str, str]] = []
    failures: dict[str, str] = {}
    for ticker in tickers:
        try:
            info = sec_ticker_info(ticker, refresh=args.refresh_sec_map)
            cik = str(info["cik"])
            if not args.dry_run:
                ensure_companyfacts(ticker, cik, force=args.force_facts)
                ensure_price_cache(ticker, force=args.force_prices, period=args.price_period)
            else:
                print(f"DRY_RUN ticker={ticker} cik={cik} price={market_cache_root(f'prices_single_name_{ticker}.parquet')}")
            resolved.append({"ticker": ticker, "cik": cik, "company_title": str(info.get("company_title", ""))})
        except BaseException as exc:
            failures[ticker] = str(exc)
            print(f"skip_ticker={ticker} reason={exc}")

    universe = batch_dir / "universe.csv"
    _write_universe(universe, resolved)
    if resolved:
        for quarter in quarters:
            _run_quarter_fetch(quarter, universe, batch_dir, args)

    add_rows = [] if args.dry_run else _build_pre_rows({row["ticker"] for row in resolved}, quarters, batch_dir)
    add_pre_path = batch_dir / f"pre_llm_added_tickers_{args.start_quarter}_{end}.csv"
    if add_rows:
        write_csv(add_pre_path, add_rows)
        master = _append_pre_llm(args.master_pre_llm, add_rows)
        _write_pre_master(master, args.master_pre_llm)
        _merge_and_rank(
            pre_llm=args.master_pre_llm,
            post_tier=DEFAULT_POST_TIER,
            hp_post=DEFAULT_HP_POST,
            combined_path=DEFAULT_COMBINED,
            combined_summary=DEFAULT_COMBINED_SUMMARY,
            rank_path=DEFAULT_RANK,
            rank_summary=DEFAULT_RANK_SUMMARY,
            combined_all=DEFAULT_COMBINED_ALL,
            combined_all_summary=DEFAULT_COMBINED_ALL_SUMMARY,
        )
    else:
        master = _read(args.master_pre_llm)

    report = batch_dir / "add_tickers_report.csv"
    _write_report(report, tickers, resolved, failures, master, add_rows)
    _run_llm_for_added(args, batch_dir, [row["ticker"] for row in resolved])

    print(
        "add_tickers_done "
        f"requested={len(tickers)} resolved={len(resolved)} failed={len(failures)} "
        f"new_pre_llm_rows={len(add_rows)} report={report}"
    )


if __name__ == "__main__":
    main()
