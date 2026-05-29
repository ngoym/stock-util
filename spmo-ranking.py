"""
Simplified SPMO-style momentum strategy

Methodology:
1. Use S&P 500 universe
2. Compute 12-month momentum excluding most recent month
3. Volatility-adjust momentum score
4. Rank stocks
5. Select top 100
6. Weight by momentum score * market cap proxy
7. Rebalance monthly

DISCLAIMER:
This is an educational approximation of the S&P 500 Momentum Index.
The official index methodology is proprietary and more complex.
"""

import pdb

import yfinance as yf
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

LOOKBACK_DAYS = 252          # ~12 months
SKIP_RECENT_DAYS = 21        # skip most recent month
VOL_LOOKBACK = 252
TOP_N = 100

# Example subset of S&P 500 for demo purposes.
# Replace with full S&P 500 universe if desired.

def get_sp500_tickers() -> list[str]:
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    table = pd.read_html(response.text)[0]
    tickers = table["Symbol"].astype(str).str.replace(".", "-", regex=False).tolist()
    return sorted(set(tickers))

# ------------------------------------------------------------
# DOWNLOAD DATA
# ------------------------------------------------------------

SP500_TICKERS = get_sp500_tickers()

end_date = "2026-01-01" #datetime.today().strftime("%Y-%m-%d")
START_DATE = (datetime.today() - timedelta(days=365*2)).strftime("%Y-%m-%d")  # 2 years back

print("Downloading price data...")

raw_prices = yf.download(
    SP500_TICKERS,
    start=START_DATE,
    end=end_date,
    auto_adjust=True,
    progress=False
)

if isinstance(raw_prices.columns, pd.MultiIndex):
    level0 = raw_prices.columns.get_level_values(0)
    level1 = raw_prices.columns.get_level_values(1)

    if "Close" in level0:
        prices = raw_prices.xs("Close", axis=1, level=0)
    elif "Close" in level1:
        prices = raw_prices.xs("Close", axis=1, level=1)
    else:
        raise ValueError("Downloaded data does not contain a Close price level")
else:
    # Single-ticker downloads can return OHLCV columns in a flat DataFrame.
    if "Close" in raw_prices.columns:
        ticker_name = SP500_TICKERS[0] if len(SP500_TICKERS) == 1 else "Close"
        prices = raw_prices[["Close"]].rename(columns={"Close": ticker_name})
    else:
        prices = raw_prices.copy()

if isinstance(prices, pd.Series):
    ticker_name = prices.name if prices.name is not None else "ticker"
    prices = prices.to_frame(name=ticker_name)
prices = prices.dropna(axis=1, how="all")

# ------------------------------------------------------------
# MOMENTUM CALCULATION
# ------------------------------------------------------------

def compute_momentum_score(price_df):
    """
    Momentum score:
        trailing 12m return excluding most recent month
        divided by annualized volatility
    """

    # Return from t-12m to t-1m
    momentum_return = (
        price_df.shift(SKIP_RECENT_DAYS) /
        price_df.shift(LOOKBACK_DAYS)
    ) - 1

    # Daily returns
    daily_returns = price_df.pct_change()

    # Annualized volatility
    volatility = (
        daily_returns
        .rolling(VOL_LOOKBACK)
        .std()
        * np.sqrt(252)
    )

    # Volatility-adjusted momentum
    score = momentum_return / volatility

    return score

scores = compute_momentum_score(prices)

# ------------------------------------------------------------
# PORTFOLIO CONSTRUCTION
# ------------------------------------------------------------

latest_scores = scores.iloc[-1].dropna()

# Rank descending
ranked = latest_scores.sort_values(ascending=False)

# Select top N
top_stocks = ranked.head(TOP_N)

# ------------------------------------------------------------
# WEIGHTING
# ------------------------------------------------------------

# Approximation:
# use positive momentum score as weighting basis

positive_scores = top_stocks.clip(lower=0)

weights = positive_scores / positive_scores.sum()

portfolio = pd.DataFrame({
    "ticker": weights.index,
    "momentum_score": top_stocks.values,
    "weight": weights.values
})

portfolio = portfolio.sort_values(
    by="weight",
    ascending=False
)

# ------------------------------------------------------------
# OUTPUT
# ------------------------------------------------------------

pd.set_option("display.float_format", "{:.4f}".format)

print("\nTop Momentum Holdings\n")
print(portfolio.head(20))

print("\nWeight Sum:", portfolio["weight"].sum())