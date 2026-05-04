import sqlite3

from tradingagents.dealflow.ic_weight_writeback import write_signal_weight_adjustments


def _seed_ic_rows(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE signal_family_ic (
            source_date TEXT,
            signal_family TEXT,
            ic REAL,
            t_stat REAL,
            n INT,
            UNIQUE(source_date, signal_family)
        )
        """
    )
    rows = [
        ("2026-02-01", "price_momentum", 0.18, 2.0, 40),
        ("2026-02-02", "price_momentum", 0.12, 1.8, 35),
        ("2026-02-03", "price_momentum", 0.10, 1.7, 32),
        ("2026-02-01", "macro_regime_fit", -0.10, -1.5, 28),
        ("2026-02-02", "macro_regime_fit", -0.08, -1.2, 24),
        ("2026-02-03", "macro_regime_fit", -0.06, -1.0, 22),
    ]
    conn.executemany("INSERT INTO signal_family_ic VALUES (?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


def test_write_signal_weight_adjustments_writes_bounded_deltas(tmp_path):
    db_path = tmp_path / "hindsight.db"
    output_path = tmp_path / "ic_signal_weights.json"
    _seed_ic_rows(db_path)

    result = write_signal_weight_adjustments(db_path=db_path, output_path=output_path)

    assert result["status"] == "UPDATED"
    assert output_path.exists()
    payload = result["payload"]
    assert payload["adjustments"]["price_momentum"] > 0
    assert payload["adjustments"]["macro_regime_fit"] < 0
    assert abs(payload["adjustments"]["price_momentum"]) <= 4.0


def test_write_signal_weight_adjustments_skips_when_insufficient_data(tmp_path):
    db_path = tmp_path / "hindsight.db"
    output_path = tmp_path / "ic_signal_weights.json"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE signal_family_ic (
            source_date TEXT,
            signal_family TEXT,
            ic REAL,
            t_stat REAL,
            n INT,
            UNIQUE(source_date, signal_family)
        )
        """
    )
    conn.execute("INSERT INTO signal_family_ic VALUES (?,?,?,?,?)", ("2026-02-01", "price_momentum", 0.2, 2.0, 10))
    conn.commit()
    conn.close()

    result = write_signal_weight_adjustments(db_path=db_path, output_path=output_path)

    assert result["status"] == "SKIPPED_INSUFFICIENT_DATA"
    assert not output_path.exists()

