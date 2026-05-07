from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
from typing import Any, Iterable


ANALYST_NAMES: tuple[str, ...] = ("market", "social", "news", "fundamentals")
SUPPORTED_ANALYST_PROVIDERS: tuple[str, ...] = ("gpt", "claude", "grok_manual")
ANALYST_PROVIDER_MAX_WORKERS: dict[str, int] = {
    "gpt": len(ANALYST_NAMES),
    "claude": 1,
    "grok_manual": len(ANALYST_NAMES),
}

COMMON_ANALYST_PROMPT = """You are a top-tier institutional equity research analyst. Your job is to produce a decision-useful analyst note on {ticker} as of {analysis_date} for an internal investment committee.

Objective:
Produce a differentiated, evidence-driven view for the {analyst} dimension only. Focus on what is material to forward returns over the stated horizon. Prioritize signal over coverage.

Standard:
Write like a buy-side or high-end sell-side analyst. Separate facts from inference. Highlight what is consensus, what is non-consensus, what can change the stock, and what appears priced in versus not priced in.

Evidence hierarchy:
1. Company filings, earnings materials, guidance, and official disclosures
2. Reputable financial news and data providers
3. Market data and consensus context
4. Social or alternative data only where relevant to this analyst lane

Rules:
- Be specific and falsifiable.
- Name the 3-5 variables that matter most.
- Distinguish near-term catalysts from structural drivers.
- State whether the evidence is improving, stable, or deteriorating.
- If evidence is weak or conflicting, say so directly.
- Do not inspect local repository files.
- Do not read project memory.
- Do not discuss tooling, repo instructions, or process.

Output:
Return exactly one JSON object matching the provided schema with one key only:
{{"report_markdown":"..."}}

Inside report_markdown, use exactly these sections:
## Thesis
## What Matters Most
## Evidence
## Risks / Disconfirming Evidence
## Bottom Line
"""

ANALYST_SPECIFIC_PROMPTS: dict[str, str] = {
    "market": """You are the MARKET analyst.

Task:
Assess the stock strictly through market structure, price action, positioning, volatility, liquidity, and technical/regime context. Do not perform fundamental analysis except where needed to explain market behavior.

Focus on:
- Trend across 1 month, 3 months, 6 months, and 12 months
- Relative strength versus sector, peers, and benchmark
- Volatility regime, drawdown character, and abnormal trading behavior
- Volume, liquidity, and positioning clues
- Key technical levels: support, resistance, breakout/breakdown zones
- Whether the setup suggests accumulation, distribution, exhaustion, or transition
- Whether the tape confirms or rejects the prevailing narrative
- What catalyst the market appears to be waiting for

Decision lens:
Answer whether the setup is constructive, neutral, or deteriorating for forward returns. Emphasize asymmetry, not just direction.

Rules:
- Do not just describe price moves; interpret them.
- Avoid indicator spam.
- Identify the one level or regime shift that would invalidate the view.
""",
    "news": """You are the NEWS analyst.

Task:
Assess the stock through recent news flow and catalysts only. Build a market-relevant readout of what happened, why it matters, what is transitory versus durable, and what the market may still be underestimating.

Focus on:
- Material news in the last 7-30 days
- Earnings, guidance, products, M&A, regulation, litigation, macro exposure, management changes, financing, and supply-chain developments
- Which developments are thesis-changing versus noise
- Whether each major item is positive, negative, mixed, or unresolved
- Whether the market reaction appears proportionate or incomplete
- Catalyst timeline: immediate, next quarter, next 12 months
- What consensus likely understands versus where interpretation may still be wrong
- Whether news flow improves or weakens forecast confidence

Decision lens:
Identify the 2-4 news items most relevant to forward returns and explain whether they strengthen, weaken, or complicate the setup.

Rules:
- Rank catalysts by materiality.
- Distinguish one-off headlines from durable earnings-power implications.
- Avoid writing a chronology; synthesize a catalyst map.
""",
    "fundamentals": """You are the FUNDAMENTALS analyst.

Task:
Assess the company's business quality and valuation using a professional equity-research standard. Focus on earnings power, capital allocation, balance sheet resilience, competitive position, and what will drive intrinsic value over the next 1-3 years.

Focus on:
- Revenue growth quality and durability
- Margin structure and margin trajectory
- Free cash flow generation and conversion
- Balance sheet strength, leverage, liquidity, and refinancing risk
- Returns on capital and reinvestment opportunity
- Business quality: moat, switching costs, scale, brand, network effects, cost advantage, or lack thereof
- Management execution and capital allocation discipline
- Valuation frame: expensive, fair, or attractive relative to growth, quality, and risk
- The 3-5 key assumptions that matter most to intrinsic value

Decision lens:
Answer whether the fundamentals are strengthening, stable, or deteriorating, and whether valuation leaves room for upside or embeds too much optimism.

Rules:
- Avoid textbook ratio dumping.
- State the real debate: what bulls believe, what bears believe, and which side has stronger evidence.
- If valuation depends on heroic assumptions, say so directly.
- Separate business quality from stock attractiveness.
""",
}


def analyst_artifact_path(
    results_root: Path,
    ticker: str,
    analysis_date: str,
    analyst: str,
    provider: str = "gpt",
) -> Path:
    provider_dir = {
        "gpt": "codex_research",
        "claude": "claude_research",
        "grok_manual": "grok_manual_research",
    }.get(str(provider).strip().lower(), "codex_research")
    return (
        Path(results_root)
        / str(ticker).upper().strip()
        / str(analysis_date).strip()
        / provider_dir
        / f"{str(analyst).strip().lower()}.json"
    )


def build_codex_exec_command(
    work_root: Path,
    model: str,
    reasoning_effort: str,
    schema_path: Path,
    output_path: Path,
    extra_args: Iterable[str] | None = None,
) -> list[str]:
    cmd = [
        "codex",
        "exec",
        "-C",
        str(Path(work_root)),
        "--skip-git-repo-check",
        "--ephemeral",
        "-m",
        str(model),
        "-c",
        f'model_reasoning_effort="{reasoning_effort}"',
        "--output-schema",
        str(Path(schema_path)),
        "-o",
        str(Path(output_path)),
        "-",
    ]
    if extra_args:
        cmd.extend(str(arg) for arg in extra_args)
    return cmd


def _schema_path() -> Path:
    return Path(__file__).parent / "schemas" / "codex_analyst_output.schema.json"


def _strip_markdown_code_fence(text: str) -> str:
    stripped = str(text or "").strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if not lines:
        return stripped
    if lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_report_markdown_from_result_text(result_text: str) -> str:
    candidates = [str(result_text or "").strip()]
    stripped = _strip_markdown_code_fence(result_text)
    if stripped and stripped != candidates[0]:
        candidates.append(stripped)

    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            report_markdown = str(parsed.get("report_markdown", "")).strip()
            if report_markdown:
                return report_markdown
    return ""


def _prompt_path(
    results_root: Path,
    ticker: str,
    analysis_date: str,
    analyst: str,
    provider: str = "gpt",
) -> Path:
    provider_dir = {
        "gpt": "codex_research",
        "claude": "claude_research",
        "grok_manual": "grok_manual_research",
    }.get(str(provider).strip().lower(), "codex_research")
    return (
        Path(results_root)
        / str(ticker).upper().strip()
        / str(analysis_date).strip()
        / provider_dir
        / "prompts"
        / f"{str(analyst).strip().lower()}.txt"
    )


def run_single_analyst(
    repo_root: Path,
    results_root: Path,
    ticker: str,
    analysis_date: str,
    analyst: str,
    prompt_text: str,
    model: str = "gpt-5.4",
    reasoning_effort: str = "xhigh",
    timeout_seconds: int = 180,
) -> Path:
    artifact_path = analyst_artifact_path(
        results_root=results_root,
        ticker=ticker,
        analysis_date=analysis_date,
        analyst=analyst,
        provider="gpt",
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)

    prompt_path = _prompt_path(
        results_root=results_root,
        ticker=ticker,
        analysis_date=analysis_date,
        analyst=analyst,
        provider="gpt",
    )
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt_text)

    raw_output_path = artifact_path.with_name(f"{artifact_path.stem}.raw.json")
    started_at = dt.datetime.now(dt.timezone.utc)

    error = None
    exit_code = 0
    try:
        with tempfile.TemporaryDirectory(prefix=f"codex-{analyst}-") as temp_dir:
            cmd = build_codex_exec_command(
                work_root=Path(temp_dir),
                model=model,
                reasoning_effort=reasoning_effort,
                schema_path=_schema_path(),
                output_path=raw_output_path,
            )
            result = subprocess.run(
                cmd,
                input=prompt_text,
                capture_output=True,
                text=True,
                timeout=int(timeout_seconds),
            )
        exit_code = int(result.returncode)
        if exit_code != 0:
            error = str(result.stderr or "").strip() or f"codex exec exited with {exit_code}"
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        exit_code = 1
        error = str(exc)

    report_markdown = ""
    if raw_output_path.is_file():
        raw_text = raw_output_path.read_text().strip()
        if raw_text:
            try:
                parsed = json.loads(raw_text)
            except json.JSONDecodeError:
                report_markdown = raw_text
            else:
                if isinstance(parsed, dict):
                    report_markdown = str(parsed.get("report_markdown", "")).strip()
                else:
                    report_markdown = str(parsed).strip()

    completed_at = dt.datetime.now(dt.timezone.utc)
    payload = {
        "ticker": str(ticker).upper().strip(),
        "as_of_date": str(analysis_date).strip(),
        "analyst": str(analyst).strip().lower(),
        "status": "SUCCESS" if exit_code == 0 and report_markdown else "FAILED",
        "model": str(model),
        "reasoning_effort": str(reasoning_effort),
        "report_markdown": report_markdown,
        "sources": [],
        "metadata": {
            "prompt_path": str(prompt_path),
            "raw_output_path": str(raw_output_path),
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_seconds": (completed_at - started_at).total_seconds(),
            "exit_code": exit_code,
            "error": error,
        },
    }
    artifact_path.write_text(json.dumps(payload, indent=2))
    return artifact_path


def run_single_analyst_claude(
    repo_root: Path,
    results_root: Path,
    ticker: str,
    analysis_date: str,
    analyst: str,
    prompt_text: str,
    model: str = "claude-sonnet-4-6",
    fallback_model: str | None = None,
    timeout_seconds: int = 180,
    retry_count: int = 1,
) -> Path:
    artifact_path = analyst_artifact_path(
        results_root=results_root,
        ticker=ticker,
        analysis_date=analysis_date,
        analyst=analyst,
        provider="claude",
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path = _prompt_path(
        results_root=results_root,
        ticker=ticker,
        analysis_date=analysis_date,
        analyst=analyst,
        provider="claude",
    )
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt_text)

    raw_output_path = artifact_path.with_name(f"{artifact_path.stem}.raw.json")
    started_at = dt.datetime.now(dt.timezone.utc)
    error = None
    exit_code = 0
    report_markdown = ""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    used_model = str(model)
    for attempt in range(int(retry_count) + 1):
        used_model = str(fallback_model or model) if attempt > 0 else str(model)
        cmd = [
            "claude",
            "-p",
            "--model",
            used_model,
            "--tools",
            "",
            "--permission-mode",
            "bypassPermissions",
            "--output-format",
            "json",
            "--no-session-persistence",
        ]
        proc: subprocess.Popen[str] | None = None
        error = None
        exit_code = 0
        report_markdown = ""
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                start_new_session=True,
            )
            stdout, stderr = proc.communicate(prompt_text, timeout=int(timeout_seconds))
            exit_code = int(proc.returncode)
            stdout = str(stdout or "").strip()
            raw_output_path.write_text(stdout)
            if exit_code != 0:
                error = str(stderr or "").strip() or f"claude -p exited with {exit_code}"
            elif stdout:
                payload = json.loads(stdout)
                if payload.get("is_error"):
                    error = str(payload.get("result") or "unknown error")
                    exit_code = 1
                else:
                    result_text = str(payload.get("result", "")).strip()
                    report_markdown = _extract_report_markdown_from_result_text(result_text)
                    if not report_markdown:
                        error = "Claude analyst output missing report_markdown"
                        exit_code = 1
            else:
                error = "claude -p returned no output"
                exit_code = 1
        except subprocess.TimeoutExpired:
            exit_code = 1
            error = f"claude -p timed out after {int(timeout_seconds)}s"
            if proc is not None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    stdout, _stderr = proc.communicate(timeout=5)
                except Exception:
                    stdout = ""
                stdout = str(stdout or "").strip()
                if stdout:
                    raw_output_path.write_text(stdout)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            exit_code = 1
            error = str(exc)

        if exit_code == 0 and report_markdown:
            break
        if attempt < int(retry_count):
            continue

    completed_at = dt.datetime.now(dt.timezone.utc)
    payload = {
        "ticker": str(ticker).upper().strip(),
        "as_of_date": str(analysis_date).strip(),
        "analyst": str(analyst).strip().lower(),
        "status": "SUCCESS" if exit_code == 0 and report_markdown else "FAILED",
        "model": used_model,
        "reasoning_effort": "n/a",
        "report_markdown": report_markdown,
        "sources": [],
        "metadata": {
            "prompt_path": str(prompt_path),
            "raw_output_path": str(raw_output_path),
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_seconds": (completed_at - started_at).total_seconds(),
            "exit_code": exit_code,
            "error": error,
            "provider": "claude",
            "retry_count": int(retry_count),
            "used_model": used_model,
        },
    }
    artifact_path.write_text(json.dumps(payload, indent=2))
    return artifact_path


def build_analyst_prompt(ticker: str, analysis_date: str, analyst: str) -> str:
    analyst_name = str(analyst).strip().lower()
    specific = ANALYST_SPECIFIC_PROMPTS.get(analyst_name)
    if specific is None:
        raise ValueError(f"Unsupported analyst: {analyst}")
    return (
        COMMON_ANALYST_PROMPT.format(
            ticker=str(ticker).upper().strip(),
            analysis_date=str(analysis_date).strip(),
            analyst=analyst_name,
        ).strip()
        + "\n\n"
        + specific.strip()
    )


def _load_artifact_payload(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def get_manual_bundle_readiness(
    results_root: Path,
    ticker: str,
    analysis_date: str,
    provider: str,
) -> dict[str, Any]:
    if provider not in {"grok_manual"}:
        raise ValueError(f"Unsupported manual provider: {provider}")
    required = list(ANALYST_NAMES)
    completed = []
    missing = []
    artifacts = {}
    for analyst in required:
        path = analyst_artifact_path(
            results_root=results_root,
            ticker=ticker,
            analysis_date=analysis_date,
            analyst=analyst,
            provider=provider,
        )
        payload = _load_artifact_payload(path) if path.is_file() else {}
        if payload.get("status") == "SUCCESS" and str(payload.get("report_markdown", "")).strip():
            completed.append(analyst)
            artifacts[analyst] = str(path)
        else:
            missing.append(analyst)
    return {
        "provider": provider,
        "ticker": str(ticker).upper().strip(),
        "analysis_date": str(analysis_date).strip(),
        "ready": len(missing) == 0,
        "required_analysts": required,
        "completed_analysts": completed,
        "missing_analysts": missing,
        "artifacts": artifacts,
    }


def ingest_manual_analyst(
    results_root: Path,
    ticker: str,
    analysis_date: str,
    analyst: str,
    provider: str,
    raw_json: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    analyst_name = str(analyst).strip().lower()
    if analyst_name not in ANALYST_NAMES:
        raise ValueError(f"Unsupported analyst: {analyst}")
    provider_name = str(provider).strip().lower()
    if provider_name != "grok_manual":
        raise ValueError(f"Unsupported manual provider: {provider}")
    parsed = json.loads(raw_json)
    report_markdown = str(parsed.get("report_markdown", "")).strip()
    if not report_markdown:
        raise ValueError("Manual analyst JSON must contain non-empty report_markdown")
    artifact_path = analyst_artifact_path(
        results_root=results_root,
        ticker=ticker,
        analysis_date=analysis_date,
        analyst=analyst_name,
        provider=provider_name,
    )
    prompt_path = _prompt_path(
        results_root=results_root,
        ticker=ticker,
        analysis_date=analysis_date,
        analyst=analyst_name,
        provider=provider_name,
    )
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_text = build_analyst_prompt(ticker, analysis_date, analyst_name)
    prompt_path.write_text(prompt_text)
    payload = {
        "ticker": str(ticker).upper().strip(),
        "as_of_date": str(analysis_date).strip(),
        "analyst": analyst_name,
        "status": "SUCCESS",
        "model": provider_name,
        "reasoning_effort": "manual",
        "report_markdown": report_markdown,
        "sources": [],
        "metadata": {
            "prompt_path": str(prompt_path),
            "provider": provider_name,
            "manual_ingest": True,
        },
    }
    if not dry_run:
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(json.dumps(payload, indent=2))
    return {
        "artifact_path": str(artifact_path),
        "prompt_path": str(prompt_path),
        "ticker": str(ticker).upper().strip(),
        "analysis_date": str(analysis_date).strip(),
        "analyst": analyst_name,
        "provider": provider_name,
        "dry_run": bool(dry_run),
    }


def run_ticker_bundle(
    repo_root: Path,
    results_root: Path,
    ticker: str,
    analysis_date: str,
    provider: str = "gpt",
    model: str = "gpt-5.4",
    fallback_model: str | None = None,
    reasoning_effort: str = "xhigh",
    timeout_seconds: int = 180,
    retry_count: int = 0,
) -> dict[str, Any]:
    provider_name = str(provider).strip().lower()
    if provider_name not in SUPPORTED_ANALYST_PROVIDERS:
        raise ValueError(f"Unsupported analyst provider: {provider}")
    if provider_name == "grok_manual":
        readiness = get_manual_bundle_readiness(results_root, ticker, analysis_date, provider_name)
        return {
            "ticker": str(ticker).upper().strip(),
            "analysis_date": str(analysis_date).strip(),
            "provider": provider_name,
            "complete": bool(readiness.get("ready")),
            "artifacts": dict(readiness.get("artifacts", {})),
            "failures": [
                {"analyst": analyst, "error": "missing manual artifact"}
                for analyst in readiness.get("missing_analysts", [])
            ],
        }

    futures = {}
    artifacts: dict[str, str] = {}
    failures: list[dict[str, str]] = []

    max_workers = ANALYST_PROVIDER_MAX_WORKERS.get(provider_name, len(ANALYST_NAMES))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for analyst in ANALYST_NAMES:
            prompt_text = build_analyst_prompt(ticker, analysis_date, analyst)
            if provider_name == "gpt":
                future = executor.submit(
                    run_single_analyst,
                    repo_root=repo_root,
                    results_root=results_root,
                    ticker=ticker,
                    analysis_date=analysis_date,
                    analyst=analyst,
                    prompt_text=prompt_text,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    timeout_seconds=timeout_seconds,
                )
            else:
                future = executor.submit(
                    run_single_analyst_claude,
                    repo_root=repo_root,
                    results_root=results_root,
                    ticker=ticker,
                    analysis_date=analysis_date,
                    analyst=analyst,
                    prompt_text=prompt_text,
                    model=model,
                    fallback_model=fallback_model,
                    timeout_seconds=timeout_seconds,
                    retry_count=retry_count,
                )
            futures[future] = analyst

        for future in as_completed(futures):
            analyst = futures[future]
            try:
                artifact_path = Path(future.result())
            except Exception as exc:
                failures.append({"analyst": analyst, "error": str(exc)})
                continue

            payload = _load_artifact_payload(artifact_path)
            if payload.get("status") == "SUCCESS" and str(payload.get("report_markdown", "")).strip():
                artifacts[analyst] = str(artifact_path)
            else:
                failures.append(
                    {
                        "analyst": analyst,
                        "error": str(payload.get("metadata", {}).get("error") or "invalid artifact"),
                    }
                )

    return {
        "ticker": str(ticker).upper().strip(),
        "analysis_date": str(analysis_date).strip(),
        "provider": provider_name,
        "complete": len(artifacts) == len(ANALYST_NAMES),
        "artifacts": artifacts,
        "failures": failures,
    }


def load_ticker_bundle_reports(bundle: dict[str, Any]) -> dict[str, str]:
    reports = {}
    field_map = {
        "market": "market_report",
        "news": "news_report",
        "fundamentals": "fundamentals_report",
    }
    for analyst, state_key in field_map.items():
        artifact_path = bundle.get("artifacts", {}).get(analyst)
        if not artifact_path:
            continue
        payload = _load_artifact_payload(Path(artifact_path))
        report = str(payload.get("report_markdown", "")).strip()
        if report:
            reports[state_key] = report
    return reports
