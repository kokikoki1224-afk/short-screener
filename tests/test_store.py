import pandas as pd

from src import config as C
from src import store as ST


class FakeWS:
    """gspread.Worksheet のうち SheetsStore が使う部分だけの偽物。rows[0] が見出し行。"""

    def __init__(self, rows=None):
        self.rows = [list(r) for r in (rows or [])]
        self.calls = []

    def row_values(self, i):
        return [str(x) for x in self.rows[i - 1]] if len(self.rows) >= i else []

    def col_values(self, c):
        return [str(r[c - 1]) for r in self.rows]

    def get_all_values(self):
        return [[str(x) for x in r] for r in self.rows]

    def delete_rows(self, a, b=None):
        self.calls.append(("delete", a, b or a))
        del self.rows[a - 1:(b or a)]

    def append_rows(self, values, **kw):
        self.calls.append(("append", len(values)))
        self.rows += [list(v) for v in values]

    def clear(self):
        self.calls.append(("clear",))
        self.rows = []

    def resize(self, **kw):
        pass

    def update(self, values, range_name="A1", **kw):
        self.calls.append(("update", range_name))
        start = int(range_name[1:]) - 1
        self.rows[start:start + len(values)] = [list(v) for v in values]


def sheets(ws):
    st = ST.SheetsStore.__new__(ST.SheetsStore)
    st._ws = lambda t: ws
    return st


def day(d, n=3):
    return pd.DataFrame({"date": d, "code": [f"{1000 + i}" for i in range(n)], "score": range(n)})


def test_same_day_rerun_does_not_duplicate():
    ws = FakeWS()
    st = sheets(ws)
    st.upsert("scores", day("2026-11-10"))
    st.upsert("scores", day("2026-11-11"))
    st.upsert("scores", day("2026-11-11"))  # 再実行
    assert len(ws.rows) == 1 + 3 + 3
    assert [r[0] for r in ws.rows[1:]].count("2026-11-11") == 3


def test_old_rows_are_deleted_by_retention(monkeypatch):
    monkeypatch.setitem(C.RETENTION_DAYS, "scores", 3)
    ws = FakeWS()
    st = sheets(ws)
    for d in ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]:
        st.upsert("scores", day(d, 2))
    dates = sorted({r[0] for r in ws.rows[1:]})
    assert dates == ["2026-11-04", "2026-11-05", "2026-11-06"]
    assert len(ws.rows) == 1 + 3 * 2


def test_append_does_not_rewrite_existing_rows():
    ws = FakeWS()
    st = sheets(ws)
    st.upsert("scores", day("2026-11-10"))
    ws.calls.clear()
    st.upsert("scores", day("2026-11-11"))
    assert not any(c[0] in ("clear", "update") for c in ws.calls)  # 全件書き戻しをしていない


def test_changed_columns_rebuilds_and_keeps_new_layout():
    old = [["date", "code", "score", "junk"], ["2026-11-10", "1000", 1, "x"]]
    ws = FakeWS(old)
    st = sheets(ws)
    st.upsert("scores", day("2026-11-11", 1))
    assert ws.rows[0] == ["date", "code", "score"]
    assert len(ws.rows) == 3 and ws.rows[1][:3] == ["2026-11-10", "1000", 1]


def test_numbers_are_sent_as_numbers():
    ws = FakeWS()
    sheets(ws).upsert("scores", pd.DataFrame({"date": ["2026-11-10"], "code": ["1301"], "score": [7.5]}))
    assert ws.rows[1] == ["2026-11-10", "1301", 7.5]


def test_local_store_prunes(tmp_path, monkeypatch):
    monkeypatch.setitem(C.RETENTION_DAYS, "scores", 2)
    st = ST.LocalStore(tmp_path)
    for d in ["2026-11-04", "2026-11-05", "2026-11-06"]:
        st.upsert("scores", day(d, 1))
    assert sorted(st.read("scores")["date"]) == ["2026-11-05", "2026-11-06"]


def test_ranges():
    assert ST._ranges([5, 3, 4, 9]) == [(3, 5), (9, 9)]
