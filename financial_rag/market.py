"""Optional delayed market context. Never supplied to filing answers or evaluation."""

import csv
import io
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from .logging_config import event

CACHE = {}
LOCK = threading.Lock()


def download(url):
    with urlopen(
        Request(url, headers={"User-Agent": "FinancialResearch/1.0"}), timeout=12
    ) as response:
        return response.read().decode()


def history(ticker):
    ticker = ticker.upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", ticker):
        raise ValueError("Invalid ticker")
    with LOCK:
        saved = CACHE.get(ticker)
        if saved and time.monotonic() - saved[0] < 900:
            event("market.cache_hit", level=logging.DEBUG, ticker=ticker)
            return saved[1]
    try:
        data = json.loads(
            download(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=3mo"
            )
        )["chart"]["result"][0]
        rows = [
            {"date": datetime.fromtimestamp(t, timezone.utc).date().isoformat(), "close": c}
            for t, c in zip(data["timestamp"], data["indicators"]["quote"][0]["close"])
            if c is not None
        ]
        if not rows:
            raise ValueError("Primary provider returned no observations")
        currency = data["meta"].get("currency")
        source = "Yahoo Finance (unofficial chart endpoint)"
    except Exception as error:
        event(
            "market.primary_failed",
            level=logging.WARNING,
            ticker=ticker,
            error_type=type(error).__name__,
        )
        try:
            records = list(
                csv.DictReader(
                    io.StringIO(download(f"https://stooq.com/q/d/l/?s={ticker.lower()}.us&i=d"))
                )
            )[-90:]
            rows = [{"date": r["Date"], "close": float(r["Close"])} for r in records]
            currency = "USD"
            source = "Stooq"
        except Exception as error:
            event(
                "market.unavailable",
                level=logging.WARNING,
                ticker=ticker,
                error_type=type(error).__name__,
            )
            return {
                "available": False,
                "ticker": ticker,
                "message": "Market provider unavailable. Filing research remains available.",
            }
    if not rows:
        return {
            "available": False,
            "ticker": ticker,
            "message": "No market observations available.",
        }
    result = {
        "available": True,
        "ticker": ticker,
        "source": source,
        "currency": currency,
        "delayed": True,
        "as_of": rows[-1]["date"],
        "rows": rows,
        "cache_seconds": 900,
    }
    with LOCK:
        CACHE[ticker] = (time.monotonic(), result)
    event(
        "market.completed",
        ticker=ticker,
        source=source,
        observations=len(rows),
        as_of=rows[-1]["date"],
    )
    return result
