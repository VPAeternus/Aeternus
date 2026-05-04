"""
Aeternus Phase Engine — Long/Short Backtester

Strategy: Always in the market. LONG by default.
When a short signal fires on day i, flip SHORT for day i+1's RTH session
(short at open, cover at close), then immediately back to LONG.
Day-by-day flip — no multi-day holds.

P&L math (per share, 1x notional):

  Non-signal day i:
    pnl = close[i] - close[i-1]

  Signal day i+1 (signal fired on day i):
    overnight_long_pnl = open[i+1] - close[i]     # held long overnight
    intraday_short_pnl = open[i+1] - close[i+1]   # short during RTH
    raw_pnl = overnight_long_pnl + intraday_short_pnl
            = 2 * open[i+1] - close[i+1] - close[i]
    cost    = 2 * TRANSACTION_BPS/10000 * open[i+1]  # 2 round-trips at open price
    pnl     = raw_pnl - cost

Compounding:
    daily_return = pnl / prev_close
    equity[i] = equity[i-1] * (1 + daily_return)
"""

from dataclasses import dataclass, field
import numpy as np
import pandas as pd

from . import config as cfg
from . import data_engine
from . import phase_engine


@dataclass
class BacktestResult:
    ticker: str
    start_date: str
    end_date: str
    start_capital: float
    final_equity: float
    total_return_pct: float
    cagr_pct: float
    sharpe: float
    sortino: float
    max_drawdown_pct: float
    max_drawdown_duration_days: int
    total_trades: int            # signal days only
    signal_win_rate_pct: float   # % of signal days profitable
    avg_signal_pnl: float
    benchmark_return_pct: float  # buy-and-hold same ticker
    benchmark_cagr_pct: float
    alpha_pct: float             # strategy CAGR - benchmark CAGR
    equity_curve: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    phase_distribution: dict = field(default_factory=dict)
    signal_breakdown: dict = field(default_factory=dict)


class PhaseBacktest:
    """Long/short backtester for the Wyckoff Adaptive Phase Engine."""

    def __init__(self, ticker: str, start_date: str = "2005-01-01",
                 capital: float = 100_000, transaction_bps: float = 10,
                 include_metals_leader: bool = True):
        self.ticker = ticker.upper()
        self.start_date = start_date
        self.capital = capital
        self.transaction_bps = transaction_bps
        self.include_metals_leader = include_metals_leader

    def run(self) -> BacktestResult:
        """Run the full long/short backtest."""

        # 1. Load data
        df = data_engine.load(self.ticker, self.start_date)
        phases = phase_engine.classify_phases(df)

        # Pre-load metals leader if needed
        leader_df = None
        leader_phases = None
        leader_date_idx = None

        if self.ticker in cfg.METALS_TICKERS and self.include_metals_leader:
            leader_df = data_engine.load(cfg.METALS_LEADER, self.start_date)
            leader_phases = phase_engine.classify_phases(leader_df)
            leader_date_idx = {
                row['date']: idx for idx, row in leader_df.iterrows()
            }

        n = len(df)
        if n < 2:
            return self._empty_result()

        # 2. Build signal map: which days had a signal fire?
        #    signal[i] = True means a signal fired on day i,
        #    so day i+1 is a SHORT day.
        signal_fired = [False] * n
        signal_names = [""] * n

        for i in range(n - 1):  # can't act on last day's signal
            if self.ticker in cfg.METALS_TICKERS:
                if leader_df is None or leader_date_idx is None:
                    continue
                date = df.iloc[i]['date']
                if date not in leader_date_idx:
                    continue
                li = leader_date_idx[date]
                sig = ""
                if phase_engine.is_metals_md_flush(leader_df, leader_phases, li):
                    sig = "metals_md_flush"
                elif phase_engine.is_metals_mu_spike(leader_df, leader_phases, li):
                    sig = "metals_mu_spike"
            else:
                sig = phase_engine.should_short_rth(
                    df, phases, i, self.ticker
                )

            if sig:
                signal_fired[i] = True
                signal_names[i] = sig

        # 3. Day-by-day P&L loop
        close = df['close'].values
        open_ = df['open'].values
        dates = df['date'].values

        equity = self.capital
        peak = equity
        max_dd = 0.0
        dd_start = 0
        max_dd_duration = 0
        current_dd_start = None

        equity_curve = []
        trade_list = []

        # Benchmark: buy-and-hold
        bench_start = close[0]

        # Track signal stats
        signal_wins = 0
        signal_total = 0
        signal_pnl_sum = 0.0
        signal_breakdown = {}  # {signal_name: {count, total_pnl, wins}}

        # Daily returns for Sharpe/Sortino
        daily_returns = []

        for i in range(1, n):
            prev_close = close[i - 1]

            if signal_fired[i - 1]:
                # Signal fired yesterday → today is a SHORT day
                # overnight_long_pnl = open[i] - close[i-1]
                # intraday_short_pnl = open[i] - close[i]
                # raw_pnl = 2*open[i] - close[i] - close[i-1]
                raw_pnl = 2.0 * open_[i] - close[i] - prev_close
                cost = 2.0 * (self.transaction_bps / 10000.0) * open_[i]
                pnl = raw_pnl - cost

                daily_return = pnl / prev_close

                # Track trade
                signal_total += 1
                signal_pnl_sum += pnl
                sig_name = signal_names[i - 1]

                if pnl > 0:
                    signal_wins += 1

                if sig_name not in signal_breakdown:
                    signal_breakdown[sig_name] = {
                        "count": 0, "total_pnl": 0.0, "wins": 0
                    }
                signal_breakdown[sig_name]["count"] += 1
                signal_breakdown[sig_name]["total_pnl"] += pnl
                if pnl > 0:
                    signal_breakdown[sig_name]["wins"] += 1

                trade_list.append({
                    "date": str(dates[i])[:10],
                    "signal": sig_name,
                    "open": round(float(open_[i]), 4),
                    "close": round(float(close[i]), 4),
                    "pnl": round(pnl, 4),
                    "cost": round(cost, 4),
                })
            else:
                # Normal long day: pnl = close[i] - close[i-1]
                pnl = close[i] - prev_close
                daily_return = pnl / prev_close

            daily_returns.append(daily_return)
            equity *= (1 + daily_return)

            # Drawdown tracking
            if equity > peak:
                peak = equity
                current_dd_start = None
            dd_pct = (peak - equity) / peak * 100
            if dd_pct > max_dd:
                max_dd = dd_pct
            if dd_pct > 0:
                if current_dd_start is None:
                    current_dd_start = i
                dd_dur = i - current_dd_start
                if dd_dur > max_dd_duration:
                    max_dd_duration = dd_dur
            else:
                current_dd_start = None

            # Benchmark equity
            bench_equity = self.capital * (close[i] / bench_start)

            equity_curve.append({
                "date": str(dates[i])[:10],
                "equity": round(equity, 2),
                "benchmark_equity": round(bench_equity, 2),
                "drawdown_pct": round(dd_pct, 2),
            })

        # 4. Compute summary metrics
        total_return = (equity / self.capital - 1) * 100
        bench_return = (close[-1] / bench_start - 1) * 100

        # CAGR
        start_dt = pd.to_datetime(dates[0])
        end_dt = pd.to_datetime(dates[-1])
        years = (end_dt - start_dt).days / 365.25
        if years > 0 and equity > 0:
            cagr = (equity / self.capital) ** (1 / years) - 1
            cagr_pct = cagr * 100
        else:
            cagr_pct = 0.0

        if years > 0 and close[-1] > 0:
            bench_cagr = (close[-1] / bench_start) ** (1 / years) - 1
            bench_cagr_pct = bench_cagr * 100
        else:
            bench_cagr_pct = 0.0

        # Sharpe (annualized, 252 trading days)
        dr = np.array(daily_returns)
        if len(dr) > 1 and np.std(dr) > 0:
            sharpe = np.mean(dr) / np.std(dr) * np.sqrt(252)
        else:
            sharpe = 0.0

        # Sortino (downside deviation)
        downside = dr[dr < 0]
        if len(downside) > 0 and np.std(downside) > 0:
            sortino = np.mean(dr) / np.std(downside) * np.sqrt(252)
        else:
            sortino = 0.0

        # Phase distribution
        phase_dist = phase_engine.phase_summary(phases)

        # Signal breakdown: add win_rate
        for k, v in signal_breakdown.items():
            v["win_rate"] = round(v["wins"] / v["count"] * 100, 1) if v["count"] > 0 else 0.0
            v["total_pnl"] = round(v["total_pnl"], 2)

        return BacktestResult(
            ticker=self.ticker,
            start_date=str(dates[0])[:10],
            end_date=str(dates[-1])[:10],
            start_capital=self.capital,
            final_equity=round(equity, 2),
            total_return_pct=round(total_return, 2),
            cagr_pct=round(cagr_pct, 2),
            sharpe=round(sharpe, 2),
            sortino=round(sortino, 2),
            max_drawdown_pct=round(max_dd, 2),
            max_drawdown_duration_days=max_dd_duration,
            total_trades=signal_total,
            signal_win_rate_pct=round(signal_wins / signal_total * 100, 1) if signal_total > 0 else 0.0,
            avg_signal_pnl=round(signal_pnl_sum / signal_total, 4) if signal_total > 0 else 0.0,
            benchmark_return_pct=round(bench_return, 2),
            benchmark_cagr_pct=round(bench_cagr_pct, 2),
            alpha_pct=round(cagr_pct - bench_cagr_pct, 2),
            equity_curve=equity_curve,
            trades=trade_list,
            phase_distribution=phase_dist,
            signal_breakdown=signal_breakdown,
        )

    def _empty_result(self) -> BacktestResult:
        return BacktestResult(
            ticker=self.ticker,
            start_date=self.start_date,
            end_date=self.start_date,
            start_capital=self.capital,
            final_equity=self.capital,
            total_return_pct=0.0,
            cagr_pct=0.0,
            sharpe=0.0,
            sortino=0.0,
            max_drawdown_pct=0.0,
            max_drawdown_duration_days=0,
            total_trades=0,
            signal_win_rate_pct=0.0,
            avg_signal_pnl=0.0,
            benchmark_return_pct=0.0,
            benchmark_cagr_pct=0.0,
            alpha_pct=0.0,
        )


def run_portfolio_backtest(tickers=None, start_date: str = "2005-01-01",
                           capital: float = 100_000,
                           equal_weight: bool = True) -> dict:
    """
    Run backtest across all tickers, equal-weight allocation.

    Returns: {per_ticker: {ticker: BacktestResult}, portfolio: BacktestResult}
    """
    if tickers is None:
        from .scanner import DEFAULT_UNIVERSE
        tickers = DEFAULT_UNIVERSE

    n_tickers = len(tickers)
    per_ticker_capital = capital / n_tickers if equal_weight else capital

    per_ticker = {}
    for ticker in tickers:
        try:
            bt = PhaseBacktest(
                ticker=ticker,
                start_date=start_date,
                capital=per_ticker_capital,
            )
            per_ticker[ticker] = bt.run()
        except Exception as e:
            print(f"  WARNING: {ticker} backtest failed: {e}")

    # Aggregate portfolio metrics
    if not per_ticker:
        return {"per_ticker": {}, "portfolio": None}

    # Aggregate equity curves by date
    all_dates = set()
    for result in per_ticker.values():
        for pt in result.equity_curve:
            all_dates.add(pt["date"])
    all_dates = sorted(all_dates)

    # Build date → equity lookup per ticker
    ticker_equity = {}
    for ticker, result in per_ticker.items():
        eq_map = {pt["date"]: pt["equity"] for pt in result.equity_curve}
        ticker_equity[ticker] = eq_map

    # Portfolio equity = sum of all ticker equities
    portfolio_curve = []
    bench_start_total = sum(r.start_capital for r in per_ticker.values())

    for date in all_dates:
        total_eq = 0.0
        total_bench = 0.0
        for ticker, result in per_ticker.items():
            eq_map = ticker_equity[ticker]
            bench_map = {pt["date"]: pt["benchmark_equity"] for pt in result.equity_curve}
            if date in eq_map:
                total_eq += eq_map[date]
            if date in bench_map:
                total_bench += bench_map[date]

        dd_pct = 0.0
        portfolio_curve.append({
            "date": date,
            "equity": round(total_eq, 2),
            "benchmark_equity": round(total_bench, 2),
            "drawdown_pct": round(dd_pct, 2),
        })

    # Compute portfolio-level drawdown
    peak = 0.0
    max_dd = 0.0
    max_dd_duration = 0
    current_dd_start = None

    for idx, pt in enumerate(portfolio_curve):
        eq = pt["equity"]
        if eq > peak:
            peak = eq
            current_dd_start = None
        if peak > 0:
            dd = (peak - eq) / peak * 100
            pt["drawdown_pct"] = round(dd, 2)
            if dd > max_dd:
                max_dd = dd
            if dd > 0:
                if current_dd_start is None:
                    current_dd_start = idx
                dur = idx - current_dd_start
                if dur > max_dd_duration:
                    max_dd_duration = dur
            else:
                current_dd_start = None

    # Portfolio summary
    final_eq = portfolio_curve[-1]["equity"] if portfolio_curve else capital
    final_bench = portfolio_curve[-1]["benchmark_equity"] if portfolio_curve else capital
    total_return = (final_eq / capital - 1) * 100
    bench_return = (final_bench / capital - 1) * 100

    start_dt = pd.to_datetime(all_dates[0]) if all_dates else pd.to_datetime(start_date)
    end_dt = pd.to_datetime(all_dates[-1]) if all_dates else pd.to_datetime(start_date)
    years = (end_dt - start_dt).days / 365.25

    if years > 0 and final_eq > 0:
        cagr_pct = ((final_eq / capital) ** (1 / years) - 1) * 100
    else:
        cagr_pct = 0.0

    if years > 0 and final_bench > 0:
        bench_cagr_pct = ((final_bench / capital) ** (1 / years) - 1) * 100
    else:
        bench_cagr_pct = 0.0

    # Daily returns from portfolio equity curve for Sharpe/Sortino
    daily_returns = []
    for j in range(1, len(portfolio_curve)):
        prev = portfolio_curve[j - 1]["equity"]
        cur = portfolio_curve[j]["equity"]
        if prev > 0:
            daily_returns.append(cur / prev - 1)

    dr = np.array(daily_returns)
    if len(dr) > 1 and np.std(dr) > 0:
        sharpe = float(np.mean(dr) / np.std(dr) * np.sqrt(252))
    else:
        sharpe = 0.0

    downside = dr[dr < 0]
    if len(downside) > 0 and np.std(downside) > 0:
        sortino = float(np.mean(dr) / np.std(downside) * np.sqrt(252))
    else:
        sortino = 0.0

    total_trades = sum(r.total_trades for r in per_ticker.values())
    total_signal_pnl = sum(r.avg_signal_pnl * r.total_trades for r in per_ticker.values())
    total_signal_wins = sum(
        r.signal_win_rate_pct / 100 * r.total_trades for r in per_ticker.values()
    )

    portfolio_result = BacktestResult(
        ticker="PORTFOLIO",
        start_date=all_dates[0] if all_dates else start_date,
        end_date=all_dates[-1] if all_dates else start_date,
        start_capital=capital,
        final_equity=round(final_eq, 2),
        total_return_pct=round(total_return, 2),
        cagr_pct=round(cagr_pct, 2),
        sharpe=round(sharpe, 2),
        sortino=round(sortino, 2),
        max_drawdown_pct=round(max_dd, 2),
        max_drawdown_duration_days=max_dd_duration,
        total_trades=total_trades,
        signal_win_rate_pct=round(total_signal_wins / total_trades * 100, 1) if total_trades > 0 else 0.0,
        avg_signal_pnl=round(total_signal_pnl / total_trades, 4) if total_trades > 0 else 0.0,
        benchmark_return_pct=round(bench_return, 2),
        benchmark_cagr_pct=round(bench_cagr_pct, 2),
        alpha_pct=round(cagr_pct - bench_cagr_pct, 2),
        equity_curve=portfolio_curve,
    )

    return {"per_ticker": per_ticker, "portfolio": portfolio_result}
