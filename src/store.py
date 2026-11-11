"""保存先の抽象化。Google Sheets(本番)とローカルCSV(開発/テスト)。

日付つきのテーブルは「追記 + 保持期間を過ぎた行の削除」でシートの肥大化を防ぐ(config.RETENTION_DAYS)。
"""
import datetime as dt
import json
import os

import numpy as np
import pandas as pd

from .config import DATA_DIR, RETENTION_DAYS

TABLES = ["stocks", "institutional_short", "positions", "short_total_history", "margin", "daily_price", "scores", "alerts"]
KEYS = {
    "stocks": ["code"],
    "institutional_short": ["calc_date", "code", "holder"],
    "positions": ["code", "holder"],
    "short_total_history": ["date", "code"],
    "margin": ["date", "code"],
    "daily_price": ["date", "code"],
    "scores": ["date", "code"],
    "alerts": ["date", "code", "type"],
}
# 保持期間で刈るときの日付列(日付なしのテーブルは常に最新値だけ持つので対象外)
DATE_COL = {"institutional_short": "disclosed", "short_total_history": "date", "margin": "date",
            "daily_price": "date", "scores": "date", "alerts": "date"}
CHUNK = 5000  # 1回のAPI呼び出しで送る最大行数


def _norm(df: pd.DataFrame, table: str) -> pd.DataFrame:
    df = df.copy()
    for k in KEYS[table]:
        df[k] = df[k].astype(str).str.slice(0, 10) if "date" in k else df[k].astype(str)
    return df


def merge(old: pd.DataFrame, new: pd.DataFrame, table: str) -> pd.DataFrame:
    new = _norm(new, table)
    if old is None or old.empty:
        return new
    return pd.concat([_norm(old, table), new], ignore_index=True).drop_duplicates(KEYS[table], keep="last")


def keep_dates(dates, table: str) -> set:
    """保持する日付(新しい方から RETENTION_DAYS[table] 個の異なる日付)。期間指定のないテーブルは None。"""
    n = RETENTION_DAYS.get(table)
    if not n:
        return None
    return set(sorted({str(d)[:10] for d in dates})[-n:])


def prune(df: pd.DataFrame, table: str) -> pd.DataFrame:
    col = DATE_COL.get(table)
    if df.empty or col is None or col not in df.columns:
        return df
    keep = keep_dates(df[col], table)
    return df[df[col].astype(str).str.slice(0, 10).isin(keep)] if keep else df


TEXT_COLS = {"code", "name", "holder", "main_holders", "type", "comment", "freq", "margin_freq",
             "margin_note", "exclude_reason"}


def coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Sheetsは全て文字列で返るので、数値に変換できる列だけ変換する(pandas 3対応)。"""
    for c in df.columns:
        if c in TEXT_COLS or "date" in c:
            continue
        conv = pd.to_numeric(df[c].replace("", pd.NA), errors="coerce")
        if conv.notna().sum() == df[c].replace("", pd.NA).notna().sum():  # 全ての非空値が数値のとき
            df[c] = conv
    return df


def _cell(x):
    """Sheetsに送る値。数値は数値のまま送る(文字列にすると並べ替えが辞書順になる)。"""
    if x is None or (isinstance(x, float) and np.isnan(x)) or x is pd.NA or x is pd.NaT:
        return ""
    if isinstance(x, (dt.date, pd.Timestamp)):
        return str(x)[:10]
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (np.integer, int)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        return float(x)
    return str(x)


def _rows(df: pd.DataFrame) -> list:
    return [[_cell(x) for x in r] for r in df.astype(object).values.tolist()]


class LocalStore:
    def __init__(self, root=DATA_DIR):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def read(self, table: str) -> pd.DataFrame:
        p = self.root / f"{table}.csv"
        return pd.read_csv(p, dtype={"code": str}) if p.exists() else pd.DataFrame()

    def upsert(self, table: str, df: pd.DataFrame):
        if df.empty:
            return
        prune(merge(self.read(table), df, table), table).to_csv(
            self.root / f"{table}.csv", index=False, encoding="utf-8-sig")


class SheetsStore:
    def __init__(self, sheet_id: str, creds_json: str):
        import gspread
        try:
            info = json.loads(creds_json)
            assert isinstance(info, dict) and info.get("type") == "service_account"
        except Exception:
            raise SystemExit(
                "GOOGLE_SERVICE_ACCOUNT_JSON がサービスアカウント鍵のJSON全文ではありません "
                f"(文字数={len(creds_json)}, 先頭={creds_json[:1]!r})。鍵ファイルの全文を貼り直してください。")
        self.book = gspread.service_account_from_dict(info).open_by_key(sheet_id)

    def _ws(self, table):
        try:
            return self.book.worksheet(table)
        except Exception:
            return self.book.add_worksheet(table, rows=1000, cols=30)

    def read(self, table: str) -> pd.DataFrame:
        vals = self._ws(table).get_all_values()
        if len(vals) < 2:
            return pd.DataFrame()
        df = pd.DataFrame(vals[1:], columns=vals[0])
        if not set(KEYS[table]) <= set(df.columns):  # 見出し欠損など。空扱いにして次の保存で作り直す
            print(f"warn: シート {table} の形式が想定外のため空として扱います (列={list(df.columns)[:6]})")
            return pd.DataFrame()
        return coerce_numeric(df)

    def upsert(self, table: str, df: pd.DataFrame):
        if df.empty:
            return
        ws = self._ws(table)
        new = _norm(df, table).drop_duplicates(KEYS[table], keep="last")
        header = ws.row_values(1)
        if table in DATE_COL and header == list(new.columns):
            self._append_prune(ws, table, new)
        else:  # 日付なしテーブル / 初回 / 列構成が変わった(移行)ときは全件を作り直す
            self._rebuild(ws, table, new)

    def _append_prune(self, ws, table: str, new: pd.DataFrame):
        keys, dcol = KEYS[table], DATE_COL[table]
        header = ws.row_values(1)
        col = {c: [str(v) for v in ws.col_values(header.index(c) + 1)[1:]] for c in set(keys + [dcol])}
        n = len(col[keys[0]])
        keep = keep_dates(set(col[dcol]) | set(new[dcol].astype(str).str.slice(0, 10)), table)
        new = new[new[dcol].astype(str).str.slice(0, 10).isin(keep)]
        newkeys = set(zip(*[new[k].astype(str).str.slice(0, 10) if "date" in k else new[k].astype(str)
                            for k in keys]))
        drop = []
        for i in range(n):
            k = tuple(col[c][i][:10] if "date" in c else col[c][i] for c in keys)
            if k in newkeys or col[dcol][i][:10] not in keep:
                drop.append(i + 2)  # シート上の行番号(1行目は見出し)
        for a, b in reversed(_ranges(drop)):  # 下から消す(行番号がずれない)
            ws.delete_rows(a, b)
        for i in range(0, len(new), CHUNK):
            ws.append_rows(_rows(new.iloc[i:i + CHUNK]), value_input_option="RAW", insert_data_option="INSERT_ROWS")
        print(f"{table}: +{len(new)}行 / 削除 {len(drop)}行")

    def _rebuild(self, ws, table: str, new: pd.DataFrame):
        merged = prune(merge(self.read(table), new, table), table)
        merged = merged.reindex(columns=list(new.columns))  # 旧い列構成の行は新しい列に揃える(余った列は捨てる)
        ws.clear()
        ws.resize(rows=len(merged) + 1, cols=max(len(merged.columns), 1))
        ws.update(values=[list(merged.columns)], range_name="A1", value_input_option="RAW")
        for i in range(0, len(merged), CHUNK):
            ws.update(values=_rows(merged.iloc[i:i + CHUNK]), range_name=f"A{i + 2}", value_input_option="RAW")
        print(f"{table}: 作り直し {len(merged)}行")


def _ranges(rows: list) -> list:
    """連続する行番号を (開始, 終了) にまとめる。"""
    out = []
    for r in sorted(rows):
        if out and r == out[-1][1] + 1:
            out[-1][1] = r
        else:
            out.append([r, r])
    return [tuple(x) for x in out]


def get_store():
    sid, creds = os.environ.get("GOOGLE_SHEET_ID"), os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    return SheetsStore(sid, creds) if sid and creds else LocalStore()
