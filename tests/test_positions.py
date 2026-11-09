import pandas as pd

from src import positions as P
from src import scoring as S


def rep(date, rows, code="1111"):
    return pd.DataFrame([{"code": code, "name": "テスト", "holder": h, "ratio": r, "prev_ratio": p,
                          "calc_date": date} for h, r, p in rows])


def test_total_includes_holders_not_reporting_today():
    """当日報告したのが1機関だけでも、合計は全機関の最新値の和(今回の不具合)。"""
    d1 = rep("2026-03-18", [("A", 1.0, 0.0), ("B", 0.8, 0.0)])
    pos = P.apply_reports(None, d1)
    assert P.totals(pos).loc["1111", "short_pct"] == 1.8
    d2 = rep("2026-03-19", [("A", 1.2, 1.0)])          # Aだけが報告
    pos = P.apply_reports(pos, d2)
    assert abs(P.totals(pos).loc["1111", "short_pct"] - 2.0) < 1e-9
    f = S.short_features(d2, pos).set_index("code").loc["1111"]
    assert abs(f.short_pct - 2.0) < 1e-9 and abs(f.short_delta_pp - 0.2) < 1e-9 and f.n_inst == 2


def test_below_threshold_drops_out_and_is_buyback():
    pos = P.apply_reports(None, rep("2026-03-18", [("A", 1.2, 0.0), ("B", 0.8, 0.0)]))
    d = rep("2026-03-19", [("B", 0.45, 0.8)])           # Bが0.5%未満へ
    pos = P.apply_reports(pos, d)
    f = S.short_features(d, pos).set_index("code").loc["1111"]
    assert abs(f.short_pct - 1.2) < 1e-9 and abs(f.short_delta_pp + 0.8) < 1e-9 and f.n_down == 1


def test_idempotent_rerun():
    d = rep("2026-03-19", [("A", 1.2, 1.0)])
    pos = P.apply_reports(None, rep("2026-03-18", [("A", 1.0, 0.0), ("B", 0.8, 0.0)]))
    once = P.apply_reports(pos, d)
    twice = P.apply_reports(once, d)
    f1 = S.short_features(d, once).set_index("code").loc["1111"]
    f2 = S.short_features(d, twice).set_index("code").loc["1111"]
    assert f1.short_pct == f2.short_pct and abs(f1.short_delta_pp - f2.short_delta_pp) < 1e-12


def test_fully_closed_stock_is_kept_for_buyback():
    pos = P.apply_reports(None, rep("2026-03-18", [("A", 0.9, 0.0)]))
    d = rep("2026-03-19", [("A", 0.3, 0.9)])
    pos = P.apply_reports(pos, d)
    f = S.short_features(d, pos).set_index("code").loc["1111"]
    assert f.short_pct == 0 and f.short_delta_pp < 0
