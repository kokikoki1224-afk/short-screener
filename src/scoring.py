"""スコア計算・フラグ判定。DataFrame入出力のみで副作用なし(テスト容易)。"""
import numpy as np
import pandas as pd

from . import config as C


def short_features(today: pd.DataFrame) -> pd.DataFrame:
    """今日の報告(機関単位)→銘柄単位。ratio合計/前回合計/増減/増加機関数など。"""
    g = today.groupby("code")
    f = pd.DataFrame({
        "name": g["name"].first(),
        "short_pct": g["ratio"].sum(),
        "short_prev_pct": g["prev_ratio"].sum(),
        "n_inst": g.size(),
        "n_up": g["delta_pp"].apply(lambda s: int((s > 0).sum())),
        "n_down": g["delta_pp"].apply(lambda s: int((s < 0).sum())),
    })
    f["short_delta_pp"] = f["short_pct"] - f["short_prev_pct"]
    f["short_delta_rate"] = np.where(f["short_prev_pct"] > 0, f["short_delta_pp"] / f["short_prev_pct"], np.nan)
    top = (today.assign(_a=today["delta_pp"].abs()).sort_values("_a", ascending=False)
           .groupby("code").head(3).groupby("code")["holder"].apply(" / ".join))
    f["main_holders"] = top
    return f.reset_index()


def price_features(px: pd.DataFrame) -> pd.DataFrame:
    """銘柄ごとの最新日の指標行。"""
    rows = []
    for code, d in px.sort_values("date").groupby("code"):
        if len(d) < 6:
            continue
        t, y = d.iloc[-1], d.iloc[-2]
        low5 = d["low"].tail(5).min()
        prior_low = d["low"].iloc[-20:-5].min() if len(d) >= 21 else np.nan
        rows.append({
            "code": code, "date": t["date"], "close": t["close"],
            "ma5": t["ma5"], "ma20": t["ma20"], "ma60": t["ma60"],
            "ma20_prev": d["ma20"].iloc[-6],
            "day_chg": t["close"] / y["close"] - 1,
            "chg5": t["close"] / d["close"].iloc[-6] - 1,
            "new_low5": bool(low5 < prior_low) if not np.isnan(prior_low) else False,
            "volume": t["volume"],
            "vol_ratio": t["volume"] / t["vol_ma20"] if t["vol_ma20"] else np.nan,
            "turnover_ma20": t["turnover_ma20"], "n_days": len(d),
            "split_recent": bool((d["split"].tail(60) != 0).any()),
            "max_jump": d["close"].pct_change().abs().tail(60).max(),
        })
    return pd.DataFrame(rows)


def score_trend(r) -> tuple[int, int]:
    conds = [r.close < r.ma5, r.ma5 < r.ma20, r.ma20 < r.ma20_prev, bool(r.new_low5)]
    c = int(sum(bool(x) for x in conds))
    return (2 if c >= 3 else 1 if c == 2 else 0), c


def score_short(r) -> int:
    if not r.short_delta_pp > C.SHORT_UP_PP_1:
        return 0
    s = 2 if r.short_delta_pp >= C.SHORT_UP_PP_2 else 1
    if r.n_up >= C.MULTI_INST_BONUS_N:
        s += 1
    return min(s, 3)


def score_volume(r) -> int:
    v = r.vol_ratio
    if pd.isna(v) or v < C.VOL_MID:
        return 0
    s = 2 if v >= C.VOL_HIGH else 1
    if r.day_chg > 0:  # 下落日の出来高増を重視。上昇日は最大1点
        s = min(s, 1)
    return s


def score_margin(r) -> tuple[int, str]:
    if pd.isna(r.buy_chg_pct):
        return 0, "信用データなし"
    price_down = r.day_chg < 0 or (not pd.isna(r.chg5) and r.chg5 < 0)
    if price_down and r.buy_chg_pct > 0:
        return (2 if r.buy_chg_pct >= C.MARGIN_UP_STRONG else 1), "下落+買い残増(売り圧力継続)"
    if price_down and r.buy_chg_pct < 0:
        return 0, "下落+買い残減(信用整理)"
    return 0, "-"


def exclusion_reason(r, excl: dict) -> str:
    if any(k in str(r.name) for k in ("受益証券", "ＥＴＦ", "ETF", "ＥＴＮ", "投資証券")):
        return "ETF/ETN/REIT(対象外)"
    if r.code in excl:
        return f"特殊要因: {excl[r.code]}"
    if r.n_days < C.MIN_HISTORY_DAYS:
        return "上場直後(履歴不足)"
    if r.volume == 0:
        return "売買停止の疑い(出来高0)"
    if r.split_recent or (r.max_jump or 0) > C.SPLIT_JUMP:
        return "分割・併合の疑い"
    if pd.isna(r.turnover_ma20) or r.turnover_ma20 < C.MIN_TURNOVER_20D:
        return "20日平均売買代金が小さい"
    return ""


def build_scores(shorts: pd.DataFrame, px: pd.DataFrame, margin: pd.DataFrame, excl: dict | None = None) -> pd.DataFrame:
    excl = excl or {}
    df = short_features(shorts).merge(price_features(px), on="code", how="inner")
    m = margin[["code", "buy", "buy_chg", "sell", "freq", "updated"]].rename(
        columns={"buy": "margin_buy", "buy_chg": "margin_buy_chg", "sell": "margin_sell",
                 "freq": "margin_freq", "updated": "margin_updated"})
    for c in ("margin_buy", "margin_buy_chg", "margin_sell"):
        m[c] = pd.to_numeric(m[c], errors="coerce")
    df = df.merge(m.drop_duplicates("code"), on="code", how="left")
    prev_buy = df["margin_buy"] - df["margin_buy_chg"]
    df["buy_chg_pct"] = np.where(prev_buy > 0, df["margin_buy_chg"] / prev_buy, np.nan)
    df["margin_ratio"] = np.where(df["margin_sell"] > 0, df["margin_buy"] / df["margin_sell"], np.nan)

    out = []
    for r in df.itertuples():
        s1, (s2, tcount) = score_short(r), score_trend(r)
        s3, (s4, mnote) = score_volume(r), score_margin(r)
        vol = 0 if pd.isna(r.vol_ratio) else r.vol_ratio
        down_trend = s2 >= 1 and r.close < r.ma20
        margin_up = not pd.isna(r.buy_chg_pct) and r.buy_chg_pct > 0
        margin_high = not pd.isna(r.margin_ratio) and r.margin_ratio >= C.MARGIN_HIGH_RATIO
        buyback_start = bool(r.short_delta_pp < 0)
        out.append({
            "date": r.date, "code": r.code, "name": r.name,
            "score": s1 + s2 + s3 + s4, "s_short": s1, "s_trend": s2, "s_volume": s3, "s_margin": s4,
            "trend_conds": tcount, "margin_note": mnote,
            "flag_buyback_start": buyback_start,
            "flag_buyback_turn": bool(buyback_start and r.day_chg > 0 and vol >= C.BUYBACK_VOL),
            "type_sell_continue": bool(r.short_delta_pp > 0 and down_trend and vol >= C.VOL_MID and (margin_up or margin_high)),
            "type_buyback": bool(buyback_start and r.day_chg > 0 and vol >= C.VOL_MID),
            "type_squeeze": bool(r.short_pct >= C.SQUEEZE_SHORT_PCT and r.day_chg > 0 and vol >= C.SQUEEZE_VOL
                                 and r.close > r.ma5 and r.close > r.ma20),
            "exclude_reason": exclusion_reason(r, excl),
        })
    keep = ["code", "short_pct", "short_prev_pct", "short_delta_pp", "short_delta_rate", "n_inst", "n_up",
            "main_holders", "close", "ma5", "ma20", "ma60", "day_chg", "chg5", "vol_ratio",
            "margin_buy", "margin_buy_chg", "buy_chg_pct", "margin_ratio", "margin_freq", "margin_updated"]
    return pd.DataFrame(out).merge(df[keep], on="code")


def add_history_changes(scores: pd.DataFrame, short_hist: pd.DataFrame) -> pd.DataFrame:
    """保存済み履歴から 1/3/5/20/60 回前の報告比の合計空売り残高変化(pp)を付与。"""
    scores = scores.copy()
    for n in C.LOOKBACKS:
        scores[f"short_chg_{n}d"] = np.nan
    if short_hist is None or short_hist.empty:
        return scores
    h = short_hist.copy()
    h["code"] = h["code"].astype(str)
    tot = h.groupby(["calc_date", "code"])["ratio"].sum().unstack("code").sort_index().ffill()
    for n in C.LOOKBACKS:
        if len(tot) > n:
            scores[f"short_chg_{n}d"] = scores["code"].map(tot.iloc[-1] - tot.iloc[-1 - n])
    return scores
