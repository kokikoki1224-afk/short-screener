# 機関空売り・需給スクリーナー

JPX空売り残高報告 × 株価/出来高 × 信用残 から、売り継続・買い戻し・踏み上げ候補を毎営業日抽出する。

```
pip install -r requirements.txt
python -m src.main --date 2026-10-06 --no-notify   # data/ にCSV保存、out/ にレポート
pytest
```

## データソース(実機で確認済み)
| 項目 | 取得元 | 状態 |
|---|---|---|
| 機関空売り | JPX `…/short-selling/…/YYYYMMDD_Short_Positions.xls`(前回割合列つき→差分は報告自体から計算) | 実装・動作確認済 |
| 株価/出来高 | yfinance `<code>.T`(対象=当日の空売り報告に出た銘柄) | 実装・動作確認済 |
| 信用残(日々公表銘柄) | JPX `…/margin/…/YYYYMMDD_mtdaily.xlsx` | 実装・動作確認済 |
| 信用残(通常・週次) | **JPXに銘柄別のExcel/CSVが見つからず未実装** | `WEEKLY_MARGIN_URL` にCSV(列 code,date,sell,buy)を指定すれば取り込む差込口のみ |

信用残が無い銘柄は ④=0点・「信用データなし」と表示。更新のない銘柄は前回値を複製し `updated=False`。

## 保存 (Google Sheets)
シート `stocks / institutional_short / margin / daily_price / scores / alerts` を自動作成。
Secrets: `GOOGLE_SHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON`(サービスアカウントにシートの編集権限を付与), 任意で `NOTIFY_WEBHOOK_URL`(Slack/Discord)。
未設定ならローカル `data/*.csv`。1/3/5/20/60回前比は `scores.short_chg_Nd` に出力(履歴が溜まるほど有効)。

## 実行
`.github/workflows/daily.yml`: 平日 17:30 JST。休場日は `calendar_jp.py` で判定して終了。手動実行は日付指定可。

## 調整・除外
閾値は `src/config.py`。TOB/MBO/上場廃止は `exclude.csv`(`code,reason`)に追記。
自動除外: ETF/ETN、20日平均売買代金<1億円、履歴60日未満、出来高0、分割疑い(±35%超/split記録)。

## 注意
- 初回は履歴が無いので、「増減」は報告内の前回割合との差。履歴蓄積後に多日比較が効く。
- Sheetsは毎回全件読み書きする単純実装。数か月で重くなれば期間を絞る。
- 日付・営業日の実行は公表後(JPXは約16時)に動かすこと。
