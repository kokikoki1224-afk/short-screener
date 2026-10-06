"""ランキング作成・個別コメント生成・通知。"""
import os

import numpy as np
import pandas as pd
import requests

from .config import TOP_N


def rankings(sc: pd.DataFrame) -> dict[str, pd.DataFrame]:
    ok = sc[sc["exclude_reason"] == ""]
    sell = ok[ok["short_delta_pp"] > 0].sort_values(
        ["score", "short_delta_pp"], ascending=False).head(TOP_N)
    buyback = ok[ok["flag_buyback_start"]].assign(
        _r=lambda d: -d["short_delta_rate"]).sort_values("_r", ascending=False).head(TOP_N)
    squeeze = ok[ok["type_squeeze"]].assign(
        _k=lambda d: d["short_pct"] * d["vol_ratio"]).sort_values("_k", ascending=False).head(TOP_N)
    return {"sell": sell.reset_index(drop=True), "buyback": buyback.reset_index(drop=True),
            "squeeze": squeeze.reset_index(drop=True)}


def _holder_streak(hist: pd.DataFrame, code: str, holder: str) -> int:
    """直近の連続増加回数(保存履歴ベース)。"""
    if hist is None or hist.empty:
        return 0
    h = hist[(hist["code"].astype(str) == code) & (hist["holder"] == holder)].sort_values("calc_date")
    d = h["ratio"].astype(float).diff().dropna().tolist()
    n = 0
    for x in reversed(d):
        if x > 0:
            n += 1
        else:
            break
    return n


def comment(r, hist: pd.DataFrame | None = None) -> str:
    lines = []
    holder = (r.main_holders or "").split(" / ")[0]
    streak = _holder_streak(hist, r.code, holder) if holder else 0
    if r.short_delta_pp > 0:
        s = f"{holder or '機関'}など{r.n_up}機関が空売りを増加(合計{r.short_pct:.2f}%、{r.short_delta_pp:+.2f}pp)"
        if streak >= 2:
            s = f"{holder}が{streak}回連続で空売りを増加。" + s
        lines.append(s + "。")
    elif r.short_delta_pp < 0:
        lines.append(f"機関空売り残高が減少(合計{r.short_pct:.2f}%、{r.short_delta_pp:+.2f}pp)。買い戻しの可能性。")
    pos = "下回り" if r.close < r.ma20 else "上回り"
    lines.append(f"株価は20日線を{pos}、5日線は{'20日線の下' if r.ma5 < r.ma20 else '20日線の上'}。"
                 f"当日出来高は20日平均の{r.vol_ratio:.1f}倍(前日比{r.day_chg:+.1%})。")
    if not pd.isna(r.buy_chg_pct):
        upd = "" if r.margin_updated in (True, "True", 1) else "(更新なし・前回値)"
        lines.append(f"信用買い残は前回比{r.buy_chg_pct:+.1%}{upd}。{r.margin_note}")
    kind = ("機関売り+信用買い増加型" if r.type_sell_continue else "買い戻し転換" if r.flag_buyback_turn
            else "買い戻し型" if r.type_buyback else "踏み上げ候補" if r.type_squeeze else "監視")
    lines.append(f"現在は{kind}。")
    return "\n".join(lines)


def to_markdown(date, rk: dict[str, pd.DataFrame], sc: pd.DataFrame, hist=None) -> str:
    def tbl(df, cols, names):
        if df.empty:
            return "(該当なし)\n"
        t = df[cols].copy()
        t.insert(0, "順位", range(1, len(t) + 1))
        t.columns = ["順位"] + names
        return t.round(3).to_markdown(index=False) + "\n"

    base = ["code", "name", "short_delta_pp", "close", "ma5", "ma20", "vol_ratio", "buy_chg_pct", "main_holders"]
    nm = ["コード", "銘柄名", "機関空売り増減(pp)", "株価", "5日線", "20日線", "出来高倍率", "信用買い残増減", "主要空売り機関"]
    md = [f"# 機関空売り・需給スクリーナー {date}\n"]
    md.append("## 1. 機関売り継続ランキング TOP20\n")
    md.append(tbl(rk["sell"], ["code", "name", "score"] + base[2:], ["コード", "銘柄名", "総合点"] + nm[2:]))
    md.append("## 2. 機関買い戻しランキング TOP20 (空売り減少率順)\n")
    md.append(tbl(rk["buyback"], ["code", "name", "short_delta_rate", "flag_buyback_turn"] + base[3:],
                  ["コード", "銘柄名", "空売り減少率", "買い戻し転換"] + nm[3:]))
    md.append("## 3. 踏み上げ候補 TOP20\n")
    md.append(tbl(rk["squeeze"], ["code", "name", "short_pct"] + base[3:],
                  ["コード", "銘柄名", "機関空売り合計%"] + nm[3:]))
    md.append("## 4. 個別コメント\n")
    for key, label in (("sell", "売り継続"), ("buyback", "買い戻し"), ("squeeze", "踏み上げ")):
        for r in rk[key].head(5).itertuples():
            md.append(f"**[{label}] {r.code} {r.name}**\n\n" + comment(r, hist).replace("\n", "  \n") + "\n")
    warn = sc[sc["exclude_reason"] != ""]
    if len(warn):
        md.append(f"## 除外・警告 ({len(warn)}銘柄)\n")
        md.append(warn.groupby("exclude_reason").size().rename("件数").to_frame().to_markdown() + "\n")
    return "\n".join(md)


def notify(date, rk: dict[str, pd.DataFrame]):
    """NOTIFY_WEBHOOK_URL (Slack / Discord Incoming Webhook)。未設定なら何もしない。"""
    url = os.environ.get("NOTIFY_WEBHOOK_URL")
    if not url:
        return
    def top(df, n=5, extra=""):
        return "\n".join(f"{i+1}. {r.code} {r.name}{extra and getattr(r, extra, '') or ''}"
                         for i, r in enumerate(df.head(n).itertuples())) or "(なし)"
    text = (f"【機関空売りスクリーナー {date}】\n■売り継続 TOP5\n{top(rk['sell'])}\n"
            f"■買い戻し TOP5\n{top(rk['buyback'])}\n■踏み上げ候補 TOP5\n{top(rk['squeeze'])}")
    body = {"content": text[:1900]} if "discord" in url else {"text": text}
    requests.post(url, json=body, timeout=30).raise_for_status()
