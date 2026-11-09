"""JPX 空売り残高報告 (Short_Positions.xls) と 日々公表信用残 (mtdaily.xlsx)。"""
import io
import re
import datetime as dt

import pandas as pd
import requests

from .config import JPX_BASE, UA, WEEKLY_MARGIN_URL

SHORT_INDEX = JPX_BASE + "/markets/public/short-selling/index.html"
MARGIN_INDEX = JPX_BASE + "/markets/statistics-equities/margin/index.html"


def _get(url: str) -> bytes:
    r = requests.get(url, headers=UA, timeout=60)
    r.raise_for_status()
    return r.content


def list_short_reports(include_archives: bool = False) -> dict[dt.date, str]:
    """公表日→xlsのURL。include_archives=True なら月次アーカイブ(約1年分)も含める。"""
    pages = [SHORT_INDEX]
    out = {}
    i = 1
    while True:
        if pages:
            url = pages.pop(0)
        elif include_archives:
            url = f"{JPX_BASE}/markets/public/short-selling/00-archives-{i:02d}.html"
            i += 1
        else:
            break
        r = requests.get(url, headers=UA, timeout=60)
        if r.status_code == 404:
            break
        r.raise_for_status()
        for path, ymd in re.findall(r'href="([^"]*?(\d{8})_Short_Positions\.xls)"', r.text):
            out[dt.datetime.strptime(ymd, "%Y%m%d").date()] = JPX_BASE + path
    return out


def fetch_short_positions(disclosed: dt.date, fallback: bool = False) -> pd.DataFrame:
    """公表日 disclosed のレポートを取得。ratioは%、prev_ratioは直近報告時の%。
    fallback=True なら、未公表のとき disclosed 以前で最新の公表分を使う。"""
    urls = list_short_reports()
    if disclosed not in urls:
        earlier = [d for d in urls if d <= disclosed]
        if not (fallback and earlier):
            raise LookupError(f"JPX空売りレポート未公表: {disclosed} (公開中: {sorted(urls)[-3:]})")
        print(f"{disclosed} 分は未公表。最新の公表分 {max(earlier)} を使います。")
        disclosed = max(earlier)
    return parse_short_positions(_get(urls[disclosed]), disclosed)


def _holder_key(raw: pd.DataFrame) -> pd.Series:
    """機関名 + (投資一任の)委託者 + 信託財産。同じ機関名でも口座が違えば別ポジションとして区別する。"""
    def col(i):
        return raw.iloc[:, i].where(raw.iloc[:, i].notna(), "").astype(str).str.strip()
    key = col(4)
    key = key + col(6).map(lambda x: f" [委託者:{x}]" if x else "")
    return key + col(8).map(lambda x: f" [{x}]" if x else "")


def parse_short_positions(content: bytes, disclosed: dt.date) -> pd.DataFrame:
    raw = pd.read_excel(io.BytesIO(content), header=None).dropna(how="all", axis=1)
    raw = raw.iloc[8:]  # 0-5: タイトル, 6-7: 日英ヘッダ
    df = pd.DataFrame({
        "calc_date": pd.to_datetime(raw.iloc[:, 0], errors="coerce"),
        "code": raw.iloc[:, 1].astype(str).str.strip(),
        "name": raw.iloc[:, 2].astype(str).str.replace("　", " ").str.replace(" 普通株式", "").str.strip(),
        "holder": _holder_key(raw),
        "ratio": pd.to_numeric(raw.iloc[:, 9], errors="coerce") * 100,
        "shares": pd.to_numeric(raw.iloc[:, 10], errors="coerce"),
        "prev_date": pd.to_datetime(raw.iloc[:, 12], errors="coerce"),
        "prev_ratio": pd.to_numeric(raw.iloc[:, 13], errors="coerce") * 100,
    })
    df = df.dropna(subset=["calc_date", "ratio"])
    df["disclosed"] = disclosed
    df["calc_date"] = df["calc_date"].dt.date
    df["prev_date"] = df["prev_date"].dt.date
    # 発行済株式数の推定 = 残高株数 / 割合
    df["shares_out"] = (df["shares"] / (df["ratio"] / 100)).round()
    df["prev_ratio"] = df["prev_ratio"].fillna(0.0)  # 新規報告は前回0%
    df["delta_pp"] = df["ratio"] - df["prev_ratio"]
    return df.reset_index(drop=True)


# ---------------------------------------------------------------- 信用残
def fetch_daily_margin() -> pd.DataFrame:
    """日々公表銘柄の信用残(最新営業日)。code(4桁), date, sell, buy, sell_chg, buy_chg, freq"""
    html = _get(MARGIN_INDEX).decode("utf-8", "ignore")
    m = re.search(r'href="([^"]*?(\d{8})_mtdaily\.xlsx)"', html)
    if not m:
        return _empty_margin()
    date = dt.datetime.strptime(m.group(2), "%Y%m%d").date()
    raw = pd.read_excel(io.BytesIO(_get(JPX_BASE + m.group(1))), header=None)
    raw = raw.dropna(how="all", axis=1)
    # 列: 3=銘柄名 6=コード(5桁) 8=売残 9=売前日比 11=買残 12=買前日比
    body = raw[raw.iloc[:, 6].astype(str).str.fullmatch(r"\d{4}[0-9A-Z]?")]
    df = pd.DataFrame({
        "code": body.iloc[:, 6].astype(str).str[:4],
        "date": date,
        "sell": pd.to_numeric(body.iloc[:, 8], errors="coerce"),
        "sell_chg": pd.to_numeric(body.iloc[:, 9], errors="coerce"),
        "buy": pd.to_numeric(body.iloc[:, 11], errors="coerce"),
        "buy_chg": pd.to_numeric(body.iloc[:, 12], errors="coerce"),
        "freq": "daily",
    })
    return df.dropna(subset=["buy"]).reset_index(drop=True)


def fetch_weekly_margin() -> pd.DataFrame:
    """週次の銘柄別信用残。WEEKLY_MARGIN_URL(CSV/Excel; code,date,sell,buy)を差し込む。未設定なら空。"""
    if not WEEKLY_MARGIN_URL:
        return _empty_margin()
    c = _get(WEEKLY_MARGIN_URL)
    df = pd.read_excel(io.BytesIO(c)) if WEEKLY_MARGIN_URL.endswith(("xls", "xlsx")) \
        else pd.read_csv(io.BytesIO(c))
    df["code"] = df["code"].astype(str).str[:4]
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.sort_values(["code", "date"])
    df["buy_chg"] = df.groupby("code")["buy"].diff()
    df["sell_chg"] = df.groupby("code")["sell"].diff()
    df["freq"] = "weekly"
    return df[["code", "date", "sell", "sell_chg", "buy", "buy_chg", "freq"]]


def _empty_margin() -> pd.DataFrame:
    return pd.DataFrame(columns=["code", "date", "sell", "sell_chg", "buy", "buy_chg", "freq"])
