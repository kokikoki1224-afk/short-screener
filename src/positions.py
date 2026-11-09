"""機関ごとの最新ポジション(状態)管理と、銘柄ごとの合計。

JPXの日次ファイルには「その日に報告した機関」しか載らない。
銘柄の機関空売り合計は、(銘柄, 機関)ごとの最新ポジションを足して求める。
"""
import pandas as pd

THRESHOLD = 0.5  # %。JPXは0.5%以上のポジションだけ開示する。これ未満に下がった機関は合計に入れない
COLS = ["code", "holder", "ratio", "calc_date", "name"]


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    df = df[COLS].copy()
    df["code"] = df["code"].astype(str)
    df["calc_date"] = df["calc_date"].astype(str).str.slice(0, 10)
    df["ratio"] = pd.to_numeric(df["ratio"], errors="coerce")
    return df.dropna(subset=["ratio"])


def apply_reports(pos: pd.DataFrame | None, reports: pd.DataFrame) -> pd.DataFrame:
    """報告を最新ポジションへ反映(同じ機関は新しい calc_date を優先)。同じ報告を再適用しても結果は変わらない。"""
    parts = [_norm(reports)] if pos is None or pos.empty else [_norm(pos), _norm(reports)]
    allp = pd.concat(parts, ignore_index=True).sort_values("calc_date", kind="stable")
    return allp.drop_duplicates(["code", "holder"], keep="last").reset_index(drop=True)


def totals(pos: pd.DataFrame) -> pd.DataFrame:
    """銘柄ごとの 合計% / 保有機関数 / 上位3機関。index=code。"""
    p = pos[pos["ratio"] >= THRESHOLD].sort_values("ratio", ascending=False)
    if p.empty:
        return pd.DataFrame(columns=["short_pct", "n_inst", "main_holders"], index=pd.Index([], name="code"))
    label = p["holder"] + " " + p["ratio"].map("{:.2f}%".format)
    g = p.assign(_l=label).groupby("code")
    return pd.DataFrame({
        "short_pct": g["ratio"].sum(),
        "n_inst": g.size(),
        "main_holders": g["_l"].apply(lambda s: " / ".join(s.head(3))),
    })


def before_state(pos_after: pd.DataFrame, today: pd.DataFrame) -> pd.DataFrame:
    """当日報告の機関だけ、報告内の「前回割合」に戻した状態(=更新前)。再実行しても同じ結果になる。"""
    t = today.sort_values("calc_date", kind="stable")
    start = t.groupby(["code", "holder"])["prev_ratio"].first().fillna(0.0).rename("start").reset_index()
    b = pos_after.merge(start, on=["code", "holder"], how="left")
    b["ratio"] = b["start"].where(b["start"].notna(), b["ratio"])
    return b.drop(columns="start")
