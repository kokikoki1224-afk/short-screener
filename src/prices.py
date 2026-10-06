"""日足OHLCV (yfinance, <code>.T) と 5/20/60日移動平均。"""
import pandas as pd
import yfinance as yf

BATCH = 100


def fetch_prices(codes: list[str], period: str = "1y") -> pd.DataFrame:
    frames = []
    for i in range(0, len(codes), BATCH):
        chunk = codes[i:i + BATCH]
        tickers = [c + ".T" for c in chunk]
        raw = yf.download(tickers, period=period, group_by="ticker", auto_adjust=False,
                          actions=True, progress=False, threads=True)
        for c, t in zip(chunk, tickers):
            try:
                d = raw[t]
            except KeyError:
                continue
            d = d.dropna(subset=["Close"]).copy()
            if d.empty:
                continue
            d["code"] = c
            frames.append(d.reset_index())
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True).rename(columns={
        "Date": "date", "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume", "Stock Splits": "split"})
    df["date"] = pd.to_datetime(df["date"]).dt.date
    if "split" not in df:
        df["split"] = 0.0
    df["split"] = df["split"].fillna(0)
    return add_indicators(df[["code", "date", "open", "high", "low", "close", "volume", "split"]])


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["code", "date"]).copy()
    g = df.groupby("code")
    for n in (5, 20, 60):
        df[f"ma{n}"] = g["close"].transform(lambda s, n=n: s.rolling(n).mean())
    df["vol_ma20"] = g["volume"].transform(lambda s: s.rolling(20).mean())
    df["turnover"] = df["close"] * df["volume"]
    df["turnover_ma20"] = df.groupby("code")["turnover"].transform(lambda s: s.rolling(20).mean())
    return df
