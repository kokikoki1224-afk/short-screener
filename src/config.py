"""閾値・定数。スコアの調整はここだけで完結させる。"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"          # ローカル保存先(Sheets未設定時)
OUT_DIR = ROOT / "out"            # 日次レポート出力先
EXCLUDE_CSV = ROOT / "exclude.csv"  # TOB/MBO/上場廃止などの手動除外 (code,reason)

JPX_BASE = "https://www.jpx.co.jp"
UA = {"User-Agent": "Mozilla/5.0 (short-screener)"}

# 週次(通常銘柄)の信用残を取りたい場合、CSV/Excel URLをここへ。
# 必須列: code, date, sell, buy  (README参照)
WEEKLY_MARGIN_URL = os.environ.get("WEEKLY_MARGIN_URL", "")

# --- 除外条件 ---
MIN_TURNOVER_20D = 1e8        # 20日平均売買代金 1億円未満は除外(警告)
MIN_HISTORY_DAYS = 60         # 60日線が計算できない上場直後は除外
SPLIT_JUMP = 0.35             # 1日で±35%超は分割・併合の疑い

# --- スコア ---
SHORT_UP_PP_1 = 0.0           # 増加>0 で1点
SHORT_UP_PP_2 = 0.20          # 増加>=0.20pp(発行済比)で2点
MULTI_INST_BONUS_N = 2        # 2機関以上が同時に売り増しで+1
VOL_MID, VOL_HIGH = 1.0, 1.5
MARGIN_UP_STRONG = 0.05       # 信用買い残 +5%以上で強
MARGIN_HIGH_RATIO = 5.0       # 信用倍率5倍以上を「高水準」
SQUEEZE_SHORT_PCT = 1.0       # 機関空売り合計1.0%以上を「高水準」
SQUEEZE_VOL = 2.0             # 出来高急増 2倍
BUYBACK_VOL = 1.2             # 買い戻し転換の出来高増加

TOP_N = 20
LOOKBACKS = (1, 3, 5, 20, 60)
PRICE_RETENTION_DAYS = 120    # daily_price に保存する日数
