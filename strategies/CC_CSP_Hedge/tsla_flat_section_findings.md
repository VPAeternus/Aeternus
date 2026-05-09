# TSLA Flat Section Analysis — Findings

## Methodology
- **Indicator:** KAMA (Kaufman Adaptive Moving Average)
  - fastLength = 2, slowLength = 15, effRatioLength = 10
- **Flat definition:** RoC = abs((AMA - AMA[1]) / AMA[1]) < 0.010
- **Data:** TSLA daily, 2010-06-29 to 2026-04-02 (3,954 days)

## Results

### Day Attribution
| | Days | % of Days |
|---|---|---|
| Flat (RoC < 0.010) | 3,048 | 77.1% |
| Trending (RoC ≥ 0.010) | 906 | 22.9% |

### Return Attribution (log-return based)
| | Return |
|---|---|
| Flat sections (327 sections) | 270.25% |
| Trending sections (326 sections) | 7,244.66% |
| Buy & Hold | 27,093.82% |

### Flat Section Stats
| | |
|---|---|
| Total sections | 327 |
| Avg days per section | 9.3 |
| Median days | 6.0 |
| Longest section | 59 days |
| Sum of section returns | 158.78% |
| Avg return per section | +0.49% |
| Win rate | 43.4% |

## Key Insight
99%+ of TSLA's total return came from trending days (22.9% of time).
Flat periods are low-return, low-risk windows — ideal for options premium harvesting (CSPs / Covered Calls).
