# Current PIT Master Invalid Notice

The current generated PIT master files must not be used for historical score validation:

- `/Users/aeternusholdings/Documents/Aeternus/outputs/fundamental_backtest/pit_master/fundamental_pit_master.csv`
- `/Users/aeternusholdings/Documents/Aeternus/outputs/fundamental_backtest/pit_master/fundamental_pit_master_clean.csv`

Why:

- financial values are not PIT-safe.
- old quarters can reuse latest/current SEC CompanyFacts values.
- some financial values may be patched after scoring.

Allowed use:

- audit evidence only.
- comparison input for validating the repaired PIT pipeline.

Do not use these files for historical validation, Top 10 / Plus 5 / shadow performance review, or production-quality walkforward scoring.
