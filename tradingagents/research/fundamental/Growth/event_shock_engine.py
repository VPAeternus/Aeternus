from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "Growth" / "earnings_8k_sec_parser" / "manifest.csv"
DEFAULT_OUTPUT = ROOT / "Growth" / "earnings_8k_sec_parser" / "event_shock_scores.csv"

STOPWORDS = {
    "about", "above", "across", "after", "again", "against", "also", "and", "are", "because",
    "been", "being", "between", "billion", "both", "business", "call", "company", "could",
    "date", "ended", "except", "financial", "first", "fiscal", "following", "fourth", "from",
    "future", "gaap", "growth", "have", "including", "million", "non", "other", "press",
    "quarter", "release", "results", "said", "second", "share", "statements", "such", "that",
    "the", "their", "third", "this", "through", "under", "were", "with", "year",
    "assets", "cash", "class", "common", "cost", "costs", "december", "diluted", "earnings",
    "exhibit", "expense", "expenses", "income", "january", "july", "june", "loss", "march",
    "months", "net", "november", "october", "operating", "per", "preliminary", "profit",
    "respectively", "restricted", "september", "stock", "tax", "three", "unaudited",
}

DRIVER_HINTS = {
    "ai", "artificial", "intelligence", "accelerated", "blackwell", "hopper", "rubin",
    "data", "center", "datacenter", "cloud", "hyperscale", "customer", "customers",
    "demand", "orders", "bookings", "backlog", "capacity", "production", "ramp",
    "deployment", "deployments", "power", "energy", "server", "servers", "catv",
    "datacom", "telecom", "optical", "400g", "800g", "1.6t", "memory", "storage",
    "gemini", "tpu", "capex", "infrastructure", "margin", "guidance", "outlook",
    "inventory", "shortfall", "export", "restriction", "china", "shipments",
}

POSITIVE_PATTERNS = {
    "demand": r"\b(strong|robust|record|extraordinary|accelerat\w*|growing|increased?|continued)\b.{0,80}\b(demand|orders?|bookings?|backlog|customers?)\b",
    "record": r"\b(record|highest|milestone|strongest|exceptional)\b.{0,80}\b(revenue|results?|quarter|year|margin)\b",
    "customer": r"\b(new|major|largest|hyperscale|strategic|tier-one)\b.{0,80}\b(customer|customers|design wins?|partnership|orders?)\b",
    "capacity": r"\b(ramp\w*|capacity|production|deployment|expansion|scale)\b.{0,80}\b(up|increase|growth|full speed|higher-volume|accelerat\w*)\b",
    "margin": r"\b(gross margin|operating margin|profitability|cash flow)\b.{0,80}\b(improv\w*|expand\w*|increase\w*|positive)\b",
    "outlook": r"\b(outlook|guidance|expects?|forecast|project\w*)\b.{0,80}\b(growth|increase|strong|accelerat\w*|positive|record)\b",
    "explicit_strength": r"\b(incredibly strong|extraordinary|full-scale production|ramping at full speed|will accelerate|accelerate|well positioned|record)\b",
}

NEGATIVE_PATTERNS = {
    "shortfall": r"\b(shortfall|below expectations|weaker than forecast|missed|lower than expected)\b",
    "weak_demand": r"\b(weak|weaker|soft|declin\w*|challenging)\b.{0,80}\b(demand|market|conditions|orders?|revenue)\b",
    "inventory": r"\b(inventory|reserves?|charges?|write-down|impairment)\b",
    "restriction": r"\b(export control|restriction|license|sanction|tariff)\b",
    "delay": r"\b(delay\w*|supply chain|component shortage|shipment timing|receiving delays)\b",
    "loss": r"\b(net loss|operating loss|negative cash flow|headwinds?|uncertain|macro)\b",
}

CYCLICALITY_PATTERNS = {
    "pricing_cycle": r"\b(pricing|price|prices|asp|average selling price)\b.{0,100}\b(cycle|decline|increase|pressure|recovery|environment)\b",
    "inventory_cycle": r"\b(inventory|inventories|customer inventory|channel inventory)\b.{0,100}\b(digestion|correction|adjustment|build|reduction|normaliz\w*)\b",
    "supply_demand": r"\b(supply-demand|supply demand|supply|demand)\b.{0,100}\b(balance|imbalance|environment|tight|oversupply|shortage)\b",
    "utilization": r"\b(utilization|fab|wafer|bit growth|dram|nand|memory)\b",
    "commodity": r"\b(commodity|commoditized|cycle|cyclical|downturn|upturn)\b",
}


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def read_csv(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_payload(row: dict[str, str]) -> dict:
    return json.loads((ROOT / row["json_path"]).read_text(encoding="utf-8"))


def semantic_text(row: dict[str, str], payload: dict) -> str:
    path = ROOT / row["json_path"]
    semantic_path = path.parents[1] / "semantic_text" / f"{path.stem}_semantic.txt"
    if semantic_path.exists():
        return semantic_path.read_text(encoding="utf-8")
    return json.dumps(payload, ensure_ascii=False)


def analysis_text(row: dict[str, str], payload: dict) -> str:
    parts = [semantic_text(row, payload)]
    for bucket in payload.get("evidence_buckets", {}).values():
        if isinstance(bucket, list):
            parts.extend(str(item) for item in bucket)
    fin = payload.get("financial_extracts", {})
    qualitative = fin.get("qualitative", {}) if isinstance(fin, dict) else {}
    if isinstance(qualitative, dict):
        parts.extend(str(item) for item in qualitative.values())
    llm = payload.get("llm_extraction", {})
    if isinstance(llm, dict):
        parts.extend(str(item.get("quote", "")) for item in llm.get("evidence", []) if isinstance(item, dict))
    return "\n".join(parts)


def tokens(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", text.lower())
    return [word for word in words if word not in STOPWORDS and not word.isdigit()]


def ngrams(words: list[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    counts.update(word for word in words if word in DRIVER_HINTS)
    for size in [2, 3]:
        for idx in range(len(words) - size + 1):
            gram = " ".join(words[idx : idx + size])
            if any(part in STOPWORDS for part in gram.split()):
                continue
            if not any(part in DRIVER_HINTS for part in gram.split()):
                continue
            counts[gram] += 1
    return counts


def pattern_counts(text: str, patterns: dict[str, str]) -> Counter[str]:
    return Counter({key: len(re.findall(pattern, text, flags=re.I | re.S)) for key, pattern in patterns.items()})


def snippets(text: str, pattern: str, limit: int = 2) -> list[str]:
    output: list[str] = []
    for match in re.finditer(pattern, text, flags=re.I | re.S):
        start = max(0, match.start() - 120)
        end = min(len(text), match.end() + 220)
        value = clean(text[start:end])
        if value and value not in output:
            output.append(value[:420])
        if len(output) >= limit:
            break
    return output


def numeric_metrics(payload: dict) -> dict[str, float | None]:
    fin = payload.get("financial_extracts", {})
    values: dict[str, float | None] = {}
    for key in [
        "quarter_revenue_yoy_pct",
        "quarter_revenue_qoq_pct",
        "guidance_revenue_millions",
        "quarter_revenue_millions",
        "guidance_gross_margin_pct",
    ]:
        value = fin.get(key)
        try:
            values[key] = float(value) if value not in {None, ""} else None
        except (TypeError, ValueError):
            values[key] = None
    if values["guidance_revenue_millions"] and values["quarter_revenue_millions"]:
        values["guidance_vs_current_pct"] = (values["guidance_revenue_millions"] / values["quarter_revenue_millions"] - 1) * 100
    else:
        values["guidance_vs_current_pct"] = None
    return values


def avg_counter(counters: list[Counter[str]]) -> Counter[str]:
    output: Counter[str] = Counter()
    if not counters:
        return output
    keys = set().union(*(counter.keys() for counter in counters))
    for key in keys:
        output[key] = sum(counter.get(key, 0) for counter in counters) / len(counters)
    return output


def baseline_avg(values: list[float | None]) -> float | None:
    nums = [value for value in values if value is not None]
    return sum(nums) / len(nums) if nums else None


def capped(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def score_row(current: dict, prior: list[dict], baseline_window: int, min_history: int) -> dict[str, object]:
    if len(prior) < min_history:
        return {
            "event_shock_score": "",
            "event_shock_bucket": "insufficient_history",
            "event_shock_confidence": 0,
            "baseline_window": len(prior),
            "positive_delta_drivers": "",
            "negative_delta_drivers": "",
            "new_driver_detected": "",
            "fading_driver_detected": "",
            "risk_delta": "",
            "demand_shock_score": "",
            "risk_shock_score": "",
            "cyclicality_penalty": "",
            "cyclicality_delta": "",
            "novelty_score": "",
            "numeric_delta_score": "",
            "evidence_snippets": "",
        }

    current_text = current["text"]
    prior_window = prior[-baseline_window:]
    prior_texts = [item["text"] for item in prior_window]
    current_terms = ngrams(tokens(current_text))
    prior_terms = avg_counter([ngrams(tokens(text)) for text in prior_texts])
    pos_current = pattern_counts(current_text, POSITIVE_PATTERNS)
    neg_current = pattern_counts(current_text, NEGATIVE_PATTERNS)
    cyc_current = pattern_counts(current_text, CYCLICALITY_PATTERNS)
    pos_prior = avg_counter([pattern_counts(text, POSITIVE_PATTERNS) for text in prior_texts])
    neg_prior = avg_counter([pattern_counts(text, NEGATIVE_PATTERNS) for text in prior_texts])
    cyc_prior = avg_counter([pattern_counts(text, CYCLICALITY_PATTERNS) for text in prior_texts])

    positive_delta = sum(pos_current.values()) - sum(pos_prior.values())
    risk_delta = sum(neg_current.values()) - sum(neg_prior.values())
    cyclicality_delta = sum(cyc_current.values()) - sum(cyc_prior.values())

    term_deltas = []
    for term, count in current_terms.items():
        if len(term) < 4 or count < 2:
            continue
        baseline = prior_terms.get(term, 0)
        delta = count - baseline
        if delta > 1.5:
            term_deltas.append((term, delta, count, baseline))
    term_deltas.sort(key=lambda item: item[1], reverse=True)
    new_drivers = [term for term, delta, count, baseline in term_deltas if baseline < 1][:8]
    positive_terms = [term for term, *_ in term_deltas[:8]]

    fading = []
    for term, baseline in prior_terms.items():
        if baseline >= 3 and current_terms.get(term, 0) <= max(1, baseline * 0.35):
            fading.append((term, baseline - current_terms.get(term, 0)))
    fading.sort(key=lambda item: item[1], reverse=True)

    current_metrics = current["metrics"]
    prior_metrics = [item["metrics"] for item in prior_window]
    numeric_delta = 0.0
    for key, scale in [
        ("quarter_revenue_yoy_pct", 15),
        ("quarter_revenue_qoq_pct", 10),
        ("guidance_vs_current_pct", 10),
        ("guidance_gross_margin_pct", 5),
    ]:
        value = current_metrics.get(key)
        base = baseline_avg([metrics.get(key) for metrics in prior_metrics])
        if value is None or base is None:
            continue
        numeric_delta += capped((value - base) / scale, -3, 3)

    novelty_score = capped(sum(delta for _, delta, _, _ in term_deltas[:8]) / 5, 0, 6)
    demand_raw = (positive_delta * 0.75) + max(numeric_delta, 0) + (novelty_score * 0.8)
    risk_raw = (risk_delta * 1.15) + max(-numeric_delta, 0)
    cyclicality_penalty = round(capped(cyclicality_delta * 0.8, 0, 5), 2)
    demand_score = round(capped(demand_raw, 0, 10), 2)
    risk_score = round(capped(risk_raw, 0, 10), 2)
    raw_score = demand_score - risk_score
    shock_score = round(capped(raw_score, -10, 10), 2)
    if demand_score >= 5 and risk_score >= 5:
        bucket = "mixed_high_shock"
    elif demand_score >= 4 and risk_score < 5:
        bucket = "positive_shock"
    elif risk_score >= 4 and demand_score < 5:
        bucket = "negative_shock"
    else:
        bucket = "neutral"

    evidence: list[str] = []
    for pattern in list(POSITIVE_PATTERNS.values()) + list(NEGATIVE_PATTERNS.values()):
        evidence.extend(snippets(current_text, pattern, limit=1))
        if len(evidence) >= 4:
            break

    confidence = 0.55
    confidence += min(0.25, len(prior_window) * 0.05)
    confidence += 0.1 if evidence else 0
    confidence += 0.1 if any(value is not None for value in current_metrics.values()) else 0
    confidence = round(min(confidence, 0.95), 2)

    return {
        "event_shock_score": shock_score,
        "event_shock_bucket": bucket,
        "event_shock_confidence": confidence,
        "baseline_window": len(prior_window),
        "positive_delta_drivers": "; ".join(positive_terms[:8]),
        "negative_delta_drivers": "; ".join([term for term, _ in fading[:8]]),
        "new_driver_detected": "; ".join(new_drivers[:6]),
        "fading_driver_detected": "; ".join([term for term, _ in fading[:6]]),
        "risk_delta": round(risk_delta, 2),
        "demand_shock_score": demand_score,
        "risk_shock_score": risk_score,
        "cyclicality_penalty": cyclicality_penalty,
        "cyclicality_delta": round(cyclicality_delta, 2),
        "novelty_score": round(novelty_score, 2),
        "numeric_delta_score": round(numeric_delta, 2),
        "evidence_snippets": " || ".join(evidence[:4]),
    }


def build_rows(manifest_path: Path, baseline_window: int, min_history: int) -> list[dict[str, object]]:
    manifest_rows = read_csv(manifest_path)
    enriched: list[dict] = []
    for row in manifest_rows:
        payload = load_payload(row)
        text = analysis_text(row, payload)
        enriched.append({
            "row": row,
            "payload": payload,
            "text": text,
            "metrics": numeric_metrics(payload),
        })

    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for item in enriched:
        by_ticker[item["row"]["ticker"]].append(item)
    for items in by_ticker.values():
        items.sort(key=lambda item: item["row"]["filed"])

    output: list[dict[str, object]] = []
    for ticker, items in sorted(by_ticker.items()):
        prior: list[dict] = []
        for item in items:
            row = item["row"]
            shock = score_row(item, prior, baseline_window, min_history)
            output.append({
                "ticker": row["ticker"],
                "filed": row["filed"],
                "tradable_date": row.get("tradable_date", ""),
                "event_shock_score": shock["event_shock_score"],
                "event_shock_bucket": shock["event_shock_bucket"],
                "event_shock_confidence": shock["event_shock_confidence"],
                "baseline_window": shock["baseline_window"],
                "positive_delta_drivers": shock["positive_delta_drivers"],
                "negative_delta_drivers": shock["negative_delta_drivers"],
                "new_driver_detected": shock["new_driver_detected"],
                "fading_driver_detected": shock["fading_driver_detected"],
                "risk_delta": shock["risk_delta"],
                "demand_shock_score": shock["demand_shock_score"],
                "risk_shock_score": shock["risk_shock_score"],
                "cyclicality_penalty": shock["cyclicality_penalty"],
                "cyclicality_delta": shock["cyclicality_delta"],
                "novelty_score": shock["novelty_score"],
                "numeric_delta_score": shock["numeric_delta_score"],
                "evidence_snippets": shock["evidence_snippets"],
                "return_10d_pct": row.get("return_10d_pct", ""),
                "return_20d_pct": row.get("return_20d_pct", ""),
                "return_30d_pct": row.get("return_30d_pct", ""),
                "return_60d_pct": row.get("return_60d_pct", ""),
                "return_90d_pct": row.get("return_90d_pct", ""),
                "quality_ok": row.get("quality_ok", ""),
                "json_path": row.get("json_path", ""),
            })
            prior.append(item)
    return sorted(output, key=lambda row: (row["ticker"], row["filed"]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ticker-relative 8-K event shock engine")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--baseline-window", type=int, default=4)
    parser.add_argument("--min-history", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = build_rows(args.manifest, args.baseline_window, args.min_history)
    write_csv(args.output, rows)
    counts = Counter(row["event_shock_bucket"] for row in rows)
    print(f"wrote {len(rows)} rows to {args.output}")
    print(dict(counts))


if __name__ == "__main__":
    main()
