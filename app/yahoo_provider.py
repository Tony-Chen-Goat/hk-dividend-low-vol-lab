from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterable

import pandas as pd


HK_SYMBOL = re.compile(r"^(\d{1,5})(?:\.HK)?$", re.IGNORECASE)


def normalize_hk_symbol(value: object) -> str:
    text = str(value).strip().upper()
    match = HK_SYMBOL.fullmatch(text)
    if not match:
        raise ValueError(f"无效港股代码: {value!r}")
    number = int(match.group(1))
    if number <= 0 or number > 99999:
        raise ValueError(f"无效港股代码: {value!r}")
    return f"{number:04d}.HK" if number <= 9999 else f"{number:05d}.HK"


@dataclass
class FetchFailure:
    symbol: str
    reason: str


@dataclass
class FetchResult:
    prices: pd.DataFrame
    dividends: pd.DataFrame
    corporate_actions: pd.DataFrame
    securities: pd.DataFrame
    failures: list[FetchFailure]


def retry_call(func: Callable, attempts: int = 3, base_delay: float = 0.5):
    error = None
    for index in range(attempts):
        try:
            return func()
        except Exception as exc:  # network/provider boundary
            error = exc
            if index + 1 < attempts:
                time.sleep(base_delay * (2**index))
    raise error


def transform_price_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["symbol", "trade_date", "open", "high", "low", "close", "adjusted_close", "volume", "traded_value", "source"])
    data = frame.copy()
    if isinstance(data.columns, pd.MultiIndex):
        if symbol in data.columns.get_level_values(-1):
            data = data.xs(symbol, axis=1, level=-1)
        elif symbol in data.columns.get_level_values(0):
            data = data.xs(symbol, axis=1, level=0)
    data = data.reset_index()
    normalized = {str(column).lower().replace(" ", "_"): column for column in data.columns}
    date_col = normalized.get("date") or normalized.get("datetime")
    if date_col is None:
        raise ValueError("Yahoo 价格数据缺少日期列")
    rename = {}
    for wanted, aliases in {
        "open": ["open"], "high": ["high"], "low": ["low"], "close": ["close"],
        "adjusted_close": ["adj_close", "adjusted_close"], "volume": ["volume"],
    }.items():
        found = next((normalized[a] for a in aliases if a in normalized), None)
        if found is not None:
            rename[found] = wanted
    data = data.rename(columns=rename)
    if "adjusted_close" not in data:
        data["adjusted_close"] = data.get("close")
    for column in ["open", "high", "low", "close", "adjusted_close", "volume"]:
        if column not in data:
            data[column] = pd.NA
    result = data[[date_col, "open", "high", "low", "close", "adjusted_close", "volume"]].copy()
    result = result.rename(columns={date_col: "trade_date"})
    result["trade_date"] = pd.to_datetime(result["trade_date"], utc=True).dt.tz_localize(None).dt.normalize()
    result.insert(0, "symbol", symbol)
    result["traded_value"] = result["close"] * result["volume"]
    result["source"] = "Yahoo Finance via yfinance"
    return result.dropna(subset=["trade_date"]).drop_duplicates(["symbol", "trade_date"], keep="last")


def fetch_yahoo_data(
    symbols: Iterable[object], start: date, end: date, *, batch_size: int = 12,
    attempts: int = 3, progress: Callable[[int, int, str], None] | None = None,
) -> FetchResult:
    import yfinance as yf

    normalized: list[tuple[str, str]] = []
    failures: list[FetchFailure] = []
    for raw in symbols:
        try:
            normalized.append((str(raw), normalize_hk_symbol(raw)))
        except ValueError as exc:
            failures.append(FetchFailure(str(raw), str(exc)))
    prices: list[pd.DataFrame] = []
    dividends: list[pd.DataFrame] = []
    corporate_actions: list[pd.DataFrame] = []
    securities: list[dict] = []
    total = len(normalized)
    for offset in range(0, total, batch_size):
        batch = normalized[offset : offset + batch_size]
        tickers = [item[1] for item in batch]
        try:
            downloaded = retry_call(
                lambda: yf.download(tickers, start=start, end=end, auto_adjust=False, actions=False, progress=False, group_by="ticker", threads=False),
                attempts=attempts,
            )
        except Exception as exc:
            downloaded = pd.DataFrame()
            for _, symbol in batch:
                failures.append(FetchFailure(symbol, f"批量价格请求失败: {exc}"))
        for index, (raw, symbol) in enumerate(batch, start=offset + 1):
            if progress:
                progress(index, total, symbol)
            try:
                price = transform_price_frame(downloaded, symbol)
                if price.empty:
                    raise ValueError("Yahoo 未返回价格记录")
                prices.append(price)
                ticker = yf.Ticker(symbol)
                actions = retry_call(lambda: ticker.actions, attempts=attempts)
                if actions is not None and not actions.empty and "Dividends" in actions:
                    div = actions.loc[actions["Dividends"].fillna(0) != 0, ["Dividends"]].reset_index()
                    date_column = div.columns[0]
                    div = div.rename(columns={date_column: "ex_date", "Dividends": "dividend_per_share"})
                    div["ex_date"] = pd.to_datetime(div["ex_date"], utc=True).dt.tz_localize(None).dt.normalize()
                    div.insert(0, "symbol", symbol)
                    div["payment_date"] = pd.NaT
                    div["currency"] = "HKD"
                    div["source"] = "Yahoo Finance via yfinance"
                    dividends.append(div)
                if actions is not None and not actions.empty and "Stock Splits" in actions:
                    splits = actions.loc[actions["Stock Splits"].fillna(0) != 0, ["Stock Splits"]].reset_index()
                    if not splits.empty:
                        date_column = splits.columns[0]
                        splits = splits.rename(columns={date_column: "action_date", "Stock Splits": "value"})
                        splits["action_date"] = pd.to_datetime(splits["action_date"], utc=True).dt.tz_localize(None).dt.normalize()
                        splits.insert(0, "symbol", symbol)
                        splits["action_type"] = "stock_split"
                        splits["source"] = "Yahoo Finance via yfinance"
                        corporate_actions.append(splits)
                try:
                    info = retry_call(lambda: ticker.get_info(), attempts=attempts) or {}
                except Exception:
                    info = {}
                if not isinstance(info, dict):
                    info = {}
                securities.append({
                    "symbol": symbol, "raw_symbol": raw, "name": info.get("longName") or info.get("shortName"),
                    "sector": info.get("sector"), "listing_date": None,
                })
            except Exception as exc:
                failures.append(FetchFailure(symbol, str(exc)))
    return FetchResult(
        prices=pd.concat(prices, ignore_index=True) if prices else pd.DataFrame(),
        dividends=pd.concat(dividends, ignore_index=True) if dividends else pd.DataFrame(),
        corporate_actions=pd.concat(corporate_actions, ignore_index=True) if corporate_actions else pd.DataFrame(),
        securities=pd.DataFrame(securities), failures=failures,
    )


def fetch_benchmark_prices(symbols: Iterable[str], start: date, end: date, attempts: int = 3) -> tuple[pd.DataFrame, list[FetchFailure]]:
    """Fetch already-validated Yahoo index symbols without applying HK equity normalization."""
    import yfinance as yf

    symbols = list(symbols)
    try:
        downloaded = retry_call(
            lambda: yf.download(symbols, start=start, end=end, auto_adjust=False, actions=False, progress=False, group_by="ticker", threads=False),
            attempts=attempts,
        )
    except Exception as exc:
        return pd.DataFrame(), [FetchFailure(symbol, str(exc)) for symbol in symbols]
    frames, failures = [], []
    for symbol in symbols:
        try:
            frame = transform_price_frame(downloaded, symbol)
            if frame.empty:
                raise ValueError("Yahoo 未返回基准价格")
            frames.append(frame)
        except Exception as exc:
            failures.append(FetchFailure(symbol, str(exc)))
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(), failures)
