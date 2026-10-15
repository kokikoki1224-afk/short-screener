"""保存先の抽象化。Google Sheets(本番)とローカルCSV(開発/テスト)。"""
import json
import os

import pandas as pd

from .config import DATA_DIR

TABLES = ["stocks", "institutional_short", "margin", "daily_price", "scores", "alerts"]
KEYS = {
    "stocks": ["code"],
    "institutional_short": ["calc_date", "code", "holder"],
    "margin": ["date", "code"],
    "daily_price": ["date", "code"],
    "scores": ["date", "code"],
    "alerts": ["date", "code", "type"],
}


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
        merge(self.read(table), df, table).to_csv(self.root / f"{table}.csv", index=False, encoding="utf-8-sig")


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
        for c in df.columns:
            if c != "code" and "date" not in c and c not in ("name", "holder", "main_holders", "type", "comment"):
                df[c] = pd.to_numeric(df[c], errors="ignore")
        return df

    def upsert(self, table: str, df: pd.DataFrame):
        if df.empty:
            return
        merged = merge(self.read(table), df, table)
        out = merged.astype(object).where(merged.notna(), "")
        ws = self._ws(table)
        ws.clear()
        ws.resize(rows=len(out) + 1, cols=max(len(out.columns), 1))
        ws.update([list(out.columns)] + out.astype(str).values.tolist(), value_input_option="RAW")


def get_store():
    sid, creds = os.environ.get("GOOGLE_SHEET_ID"), os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    return SheetsStore(sid, creds) if sid and creds else LocalStore()
