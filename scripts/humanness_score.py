#!/usr/bin/env python3
"""
Humanness scorer — measures writing patterns that distinguish human from LLM text.

Usage:
    python scripts/humanness_score.py eval_results/content/orcl_thread_2026-03-06.md
    python scripts/humanness_score.py file1.md file2.md   # compare two files

Signals scored:
  1. Sentence length variance — humans are uneven, LLMs are uniform
  2. Paragraph length variance — humans write lopsided, LLMs balance
  3. Hedge/transition word density — LLMs over-hedge
  4. Em-dash density — LLMs overuse them
  5. Structure words — LLMs organize, humans argue
  6. Consecutive short sentences — humans punch, LLMs don't
  7. Engagement bait — "Thoughts?" = instant LLM tell
  8. First-person voice — opinionated humans say "I", LLMs avoid it
  9. Uncertainty admissions — humans say "I don't know", LLMs never do

Target: 80+ = publishable. 70-79 = needs a pass. <70 = rewrite.
"""

import re
import sys
import statistics

LLM_HEDGE_WORDS = [
    "however", "that said", "it's worth noting", "notably", "importantly",
    "interestingly", "furthermore", "moreover", "additionally", "nevertheless",
    "conversely", "essentially", "fundamentally", "ultimately", "comprehensive",
    "nuanced", "multifaceted", "landscape", "paradigm", "leverage",
    "robust", "streamline", "holistic", "synergy", "deep dive",
    "let's dive", "in conclusion", "to summarize", "in summary",
    "it should be noted", "worth mentioning", "key takeaway",
    "at the end of the day", "the bottom line", "when it comes to",
    "in terms of", "with that being said", "having said that",
    "that being said", "on the other hand", "by the same token",
]

STRUCTURE_WORDS = [
    "first", "second", "third", "finally", "next",
    "here's what", "here is what", "let's look", "let's examine",
    "now let's", "moving on", "turning to", "looking at",
    "on one hand", "on the other", "the flip side",
    "adds another layer", "adds some color", "paints a picture",
    "ties it together", "brings it all together",
]

ENGAGEMENT_BAIT = [
    "thoughts?", "what do you think", "agree or disagree",
    "let me know", "drop a comment", "share your",
    "is it worth", "would you",
]


def _sentences(text):
    parts = re.split(r'[.!?]+', text)
    return [s.strip() for s in parts if s.strip() and len(s.strip()) > 5]


def _paragraphs(text):
    parts = text.strip().split('\n\n')
    return [p.strip() for p in parts if p.strip() and len(p.strip()) > 20
            and not p.strip().startswith('#') and not p.strip().startswith('*')]


def _wc(text):
    return len(text.split())


def _pattern_hits(text, patterns):
    t = text.lower()
    return sum(1 for p in patterns if p in t)


def _short_sentence_runs(sents, threshold=8):
    runs = 0
    current = 0
    for s in sents:
        if _wc(s) <= threshold:
            current += 1
        else:
            if current >= 2:
                runs += 1
            current = 0
    if current >= 2:
        runs += 1
    return runs


def _extract_body(text):
    """Strip markdown frontmatter (title, date, ---) and ## sections like X Post."""
    lines = text.strip().split('\n')
    body_lines = []
    past_header = False
    for line in lines:
        stripped = line.strip()
        # Skip markdown headers and --- separators
        if stripped.startswith('#') or stripped == '---':
            past_header = True
            continue
        # Skip italic date lines
        if stripped.startswith('*') and stripped.endswith('*'):
            continue
        body_lines.append(line)

    body = '\n'.join(body_lines).strip()

    # Remove ## X Post or similar trailing sections
    for marker in ['## X Post', '## Tweet', '## Post']:
        if marker in body:
            body = body[:body.index(marker)].strip()

    return body


def score_text(text, label=""):
    sents = _sentences(text)
    paras = _paragraphs(text)
    wc = _wc(text)

    if wc < 50:
        print(f"  Skipping '{label}' — only {wc} words (need 50+)")
        return 0

    sent_lengths = [_wc(s) for s in sents]
    para_lengths = [_wc(p) for p in paras]

    sent_cv = (statistics.stdev(sent_lengths) / statistics.mean(sent_lengths)) if len(sent_lengths) > 2 else 0
    para_cv = (statistics.stdev(para_lengths) / statistics.mean(para_lengths)) if len(para_lengths) > 2 else 0

    hedge_hits = _pattern_hits(text, LLM_HEDGE_WORDS)
    hedge_density = (hedge_hits / wc) * 100

    em_dashes = text.count('\u2014') + text.count(' - ')
    em_density = (em_dashes / wc) * 100

    structure_hits = _pattern_hits(text, STRUCTURE_WORDS)
    structure_density = (structure_hits / wc) * 100

    short_runs = _short_sentence_runs(sents)

    bait_hits = _pattern_hits(text, ENGAGEMENT_BAIT)

    i_count = len(re.findall(r'\bI\b', text))
    i_density = (i_count / wc) * 100

    admissions = len(re.findall(
        r"I don't know|I'm not sure|I could be wrong|no idea|beats me|hard to say",
        text, re.I))

    scores = {}
    scores['sent_variance'] = min(sent_cv / 0.6 * 20, 20)
    scores['para_variance'] = min(para_cv / 0.5 * 15, 15)
    scores['low_hedging'] = max(15 - hedge_density * 15, 0)

    if em_density < 0.3:
        scores['em_dash'] = 8
    elif em_density <= 1.0:
        scores['em_dash'] = 10
    elif em_density <= 1.5:
        scores['em_dash'] = 6
    else:
        scores['em_dash'] = max(10 - (em_density - 1.0) * 5, 0)

    scores['low_structure'] = max(10 - structure_density * 20, 0)
    scores['short_punches'] = min(short_runs * 5, 10)
    scores['no_bait'] = 5 if bait_hits == 0 else 0
    scores['voice'] = min(i_density / 0.8 * 10, 10)
    scores['admissions'] = min(admissions * 2.5, 5)

    total = sum(scores.values())

    print(f"\n{'=' * 60}")
    print(f"  {label or 'INPUT'}")
    print(f"  {wc} words | {len(sents)} sentences | {len(paras)} paragraphs")
    print(f"{'=' * 60}")
    print()
    print(f"  Sentence length variance (CV):   {sent_cv:.2f}  [{scores['sent_variance']:.1f}/20]")
    print(f"    lengths: {sent_lengths[:8]}{'...' if len(sent_lengths) > 8 else ''}")
    print(f"  Paragraph length variance (CV):  {para_cv:.2f}  [{scores['para_variance']:.1f}/15]")
    print(f"    lengths: {para_lengths}")
    print(f"  Hedge word density:              {hedge_density:.2f}/100w ({hedge_hits} hits)  [{scores['low_hedging']:.1f}/15]")
    print(f"  Em-dash density:                 {em_density:.2f}/100w ({em_dashes})  [{scores['em_dash']:.1f}/10]")
    print(f"  Structure word density:          {structure_density:.2f}/100w ({structure_hits} hits)  [{scores['low_structure']:.1f}/10]")
    print(f"  Short sentence runs:             {short_runs}  [{scores['short_punches']:.1f}/10]")
    print(f"  Engagement bait:                 {bait_hits}  [{scores['no_bait']:.1f}/5]")
    print(f"  First-person density:            {i_density:.2f}/100w ({i_count})  [{scores['voice']:.1f}/10]")
    print(f"  Uncertainty admissions:          {admissions}  [{scores['admissions']:.1f}/5]")
    print()

    if total >= 80:
        verdict = "PUBLISHABLE"
    elif total >= 70:
        verdict = "NEEDS A PASS"
    else:
        verdict = "REWRITE"

    print(f"  HUMANNESS SCORE:                 {total:.1f} / 100  [{verdict}]")
    print()

    return total


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/humanness_score.py <file> [file2]")
        sys.exit(1)

    results = []
    for path in sys.argv[1:]:
        with open(path) as f:
            raw = f.read()
        body = _extract_body(raw)
        label = path.split('/')[-1]
        s = score_text(body, label)
        results.append((label, s))

    if len(results) > 1:
        print(f"\n{'=' * 60}")
        print(f"  COMPARISON")
        print(f"{'=' * 60}")
        for label, s in results:
            print(f"  {label}: {s:.1f}/100")
        best = max(results, key=lambda x: x[1])
        worst = min(results, key=lambda x: x[1])
        print(f"  Delta: {best[1] - worst[1]:+.1f} ({best[0]} over {worst[0]})")
        print()


if __name__ == '__main__':
    main()
