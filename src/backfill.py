"""JPXの過去ファイル(約1年分)を再生して、機関別の最新ポジションと日別の合計履歴を作る。

  python -m src.backfill      # 強制的に作り直す
日次実行(main)は、positions が空のとき自動でこれを呼ぶ。
"""
import time

import pandas as pd

from . import config as C
from . import jpx
from . import positions as P
from .store import get_store


def _download(url: str, tries: int = 3) -> bytes:
    for i in range(tries):
        try:
            return jpx._get(url)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def run(store, hist_days: int = 70) -> pd.DataFrame:
    urls = jpx.list_short_reports(include_archives=True)
    days = sorted(urls)
    print(f"backfill: {len(days)} files ({days[0]} -> {days[-1]})")
    pos, rows = None, []
    for i, d in enumerate(days):
        rep = jpx.parse_short_positions(_download(urls[d]), d)
        pos = P.apply_reports(pos, rep)
        if i >= len(days) - hist_days:
            t = P.totals(pos)
            rows.append(pd.DataFrame({"date": str(d), "code": t.index, "short_pct": t["short_pct"].values}))
    store.upsert("positions", pos)
    store.upsert("short_total_history", pd.concat(rows, ignore_index=True))
    print(f"backfill: positions={len(pos)} history_days={len(rows)}")
    return pos


if __name__ == "__main__":
    run(get_store())
