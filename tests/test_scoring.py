import datetime as dt
from types import SimpleNamespace as NS

import numpy as np
import pandas as pd

from src import scoring as S
from src.prices import add_indicators


def _px(code, closes, vols, lows=None):
    n = len(closes)
    dates = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(n)]
    df = pd.DataFrame({"code": code, "date": dates, "open": closes, "high": closes,
                       "low": lows or closes, "close": closes, "volume": vols, "split": 0.0})
    return add_indicators(df)


def _short(code, rows):
    return pd.DataFrame([{"code": code, "name": "テスト", "holder": h, "ratio": r, "prev_ratio": p,
                          "delta_pp": r - p, "shares_out": 1e7} for h, r, p in rows])


def _margin(code, buy, chg):
    return pd.DataFrame([{"code": code, "buy": buy, "buy_chg": chg, "sell": 100.0, "freq": "daily", "updated": True}])


def test_sell_continue():
    closes = list(np.linspace(1000, 700, 80))
    vols = [1_000_000] * 79 + [2_500_000]
    sc = S.build_scores(_short("1111", [("MS", 1.0, 0.5), ("GS", 0.6, 0.4)]),
                        _px("1111", closes, vols), _margin("1111", 1100, 100))
    r = sc.iloc[0]
    assert r.s_short == 3 and r.s_volume == 2 and r.s_margin == 2
    assert r.type_sell_continue and not r.flag_buyback_start and r.exclude_reason == ""


def test_buyback_turn_not_added_to_score():
    closes = list(np.linspace(700, 1000, 79)) + [1050]
    vols = [1_000_000] * 79 + [1_800_000]
    sc = S.build_scores(_short("2222", [("MS", 0.5, 1.0)]), _px("2222", closes, vols), _margin("2222", 900, -50))
    r = sc.iloc[0]
    assert r.flag_buyback_start and r.flag_buyback_turn and r.s_short == 0


def test_margin_down_is_not_pressure():
    r = NS(day_chg=-0.02, chg5=-0.05, buy_chg_pct=-0.1)
    assert S.score_margin(r)[0] == 0


def test_new_listing_excluded():
    sc = S.build_scores(_short("3333", [("MS", 1.0, 0.5)]), _px("3333", [100.0] * 30, [10] * 30),
                        _margin("3333", 10, 1))
    assert "上場直後" in sc.iloc[0].exclude_reason
