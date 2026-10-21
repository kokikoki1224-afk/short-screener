"""日次パイプライン。  python -m src.main [--date YYYY-MM-DD] [--no-notify]"""
import argparse
import datetime as dt
import sys

import pandas as pd

from . import config as C
from . import dashboard, jpx, prices, report, scoring
from .calendar_jp import is_business_day
from .store import get_store

JST = dt.timezone(dt.timedelta(hours=9))


def load_exclusions() -> dict:
    if not C.EXCLUDE_CSV.exists():
        return {}
    d = pd.read_csv(C.EXCLUDE_CSV, dtype=str).fillna("")
    return dict(zip(d["code"], d["reason"]))


def carry_forward_margin(store, fresh: pd.DataFrame, today: dt.date) -> pd.DataFrame:
    """更新のない銘柄は前回値をコピーして updated=False と明示。"""
    fresh = fresh.copy()
    fresh["updated"] = True
    old = store.read("margin")
    if old.empty:
        return fresh
    old["code"] = old["code"].astype(str)
    last = old.sort_values("date").groupby("code").tail(1)
    last = last[~last["code"].isin(fresh["code"])].copy()
    last["date"] = str(today)
    last["updated"] = False
    return pd.concat([fresh, last[fresh.columns]], ignore_index=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="公表日(既定: 今日JST)")
    ap.add_argument("--no-notify", action="store_true")
    a = ap.parse_args(argv)
    today = dt.date.fromisoformat(a.date) if a.date else dt.datetime.now(JST).date()

    if not is_business_day(today):                                   # 1. 営業日判定
        print(f"{today} は休場日。終了。")
        return 0
    store = get_store()

    shorts = jpx.fetch_short_positions(today, fallback=not a.date)                        # 2. JPX空売り
    today = shorts["disclosed"].iloc[0]  # 以降の保存・出力は実際に使った公表日で揃える
    print(f"short: {len(shorts)} rows / {shorts['code'].nunique()} stocks")
    codes = sorted(shorts["code"].unique())
    px = prices.fetch_prices(codes)                                  # 3. 株価・出来高
    print(f"prices: {px['code'].nunique()} stocks")
    margin = pd.concat([jpx.fetch_weekly_margin(), jpx.fetch_daily_margin()])  # 4. 信用残
    margin["date"] = margin["date"].astype(str)
    margin = margin.sort_values("date").groupby("code").tail(1)      # 日次があれば日次を優先
    margin = carry_forward_margin(store, margin[margin["code"].isin(codes)], today)

    hist = store.read("institutional_short")                         # 5. 前回比較(履歴)
    sc = scoring.build_scores(shorts, px, margin, load_exclusions())  # 6. スコア
    cur = shorts[["calc_date", "code", "holder", "ratio"]].assign(calc_date=lambda d: d["calc_date"].astype(str))
    full_hist = pd.concat([hist[cur.columns] if not hist.empty else hist, cur]).drop_duplicates(
        ["calc_date", "code", "holder"], keep="last")
    sc = scoring.add_history_changes(sc, full_hist)
    rk = report.rankings(sc)                                         # 7. ランキング

    md = report.to_markdown(today, rk, sc, hist)
    C.OUT_DIR.mkdir(exist_ok=True)
    (C.OUT_DIR / f"report_{today}.md").write_text(md, encoding="utf-8")
    dashboard.build(today, sc, rk, hist, C.OUT_DIR / "site" / "index.html")
    sc.to_csv(C.OUT_DIR / f"scores_{today}.csv", index=False, encoding="utf-8-sig")

    # 8. 保存
    store.upsert("stocks", shorts.groupby("code").agg(
        name=("name", "first"), shares_out=("shares_out", "median")).reset_index())
    store.upsert("institutional_short", shorts[
        ["calc_date", "code", "holder", "ratio", "shares", "prev_date", "prev_ratio", "delta_pp", "disclosed"]])
    store.upsert("margin", margin)
    keep = px[px["date"] >= px["date"].max() - dt.timedelta(days=C.PRICE_RETENTION_DAYS)]
    store.upsert("daily_price", keep.drop(columns=["split", "turnover"]))
    store.upsert("scores", sc.assign(date=str(today)))
    alerts = []
    for r in sc.itertuples():
        for t, f in (("買い戻し開始", r.flag_buyback_start), ("買い戻し転換", r.flag_buyback_turn),
                     ("売り継続型", r.type_sell_continue), ("踏み上げ候補", r.type_squeeze)):
            if f and not r.exclude_reason:
                alerts.append({"date": str(today), "code": r.code, "type": t, "name": r.name,
                               "comment": report.comment(r, hist)})
        if r.exclude_reason:
            alerts.append({"date": str(today), "code": r.code, "type": "除外/警告", "name": r.name,
                           "comment": r.exclude_reason})
    store.upsert("alerts", pd.DataFrame(alerts))

    if not a.no_notify:                                              # 9. 通知
        report.notify(today, rk)
    print(f"done. sell={len(rk['sell'])} buyback={len(rk['buyback'])} squeeze={len(rk['squeeze'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
