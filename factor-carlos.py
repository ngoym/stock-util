
import os
import pickle
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import yfinance as yf

DATA_DIR = "data_layers"
START_DATE = "2013-01-01"
END_DATE = "2026-03-24"
TOP_N = 20
REBALANCE_FREQ = "3ME"
RANK_TOLERANCE_PCT = 0.10
ESTIMATE_ENTRY_TOP_PCT = 0.10
ESTIMATE_EXIT_TOP_PCT = 0.20
CORE_RANK_EXIT_THRESHOLD = 0.90
SLIPPAGE = 0.02
LOAD_CACHE = False
STARTING_CAPITAL = 1000.0
TRANSACTION_COST_PER_TRADE = 1.0
MULTIFACTOR_MIN_HOLD_REBALANCES = 1
MULTIFACTOR_WINNER_LOOKBACK_DAYS = 182
MULTIFACTOR_HARD_DROP_RANK_PCT = 0.10


@dataclass
class StrategyConfig:
    name: str
    score_columns: list[str]


def get_sp500_tickers() -> list[str]:
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    table = pd.read_html(response.text)[0]
    tickers = table["Symbol"].astype(str).str.replace(".", "-", regex=False).tolist()
    return sorted(set(tickers))

def get_sp400_tickers() -> list[str]:
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    table = pd.read_html(response.text)[0]
    tickers = table["Symbol"].astype(str).str.replace(".", "-", regex=False).tolist()
    return sorted(set(tickers))

def get_sp600_tickers() -> list[str]:
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    table = pd.read_html(response.text)[0]
    tickers = table["Symbol"].astype(str).str.replace(".", "-", regex=False).tolist()
    return sorted(set(tickers))

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def save_pickle(obj, file_name: str) -> None:
    with open(os.path.join(DATA_DIR, file_name), "wb") as file:
        pickle.dump(obj, file)


def load_pickle(file_name: str):
    with open(os.path.join(DATA_DIR, file_name), "rb") as file:
        return pickle.load(file)


def to_timestamp_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out.columns = pd.to_datetime(out.columns, errors="coerce")
    out = out.loc[:, out.columns.notna()]
    out = out.sort_index(axis=1)
    return out


def nearest_on_or_before(index_values: pd.DatetimeIndex, target: pd.Timestamp):
    if len(index_values) == 0:
        return None
    pos = index_values.searchsorted(target, side="right") - 1
    if pos < 0:
        return None
    return index_values[pos]


def latest_value(table: pd.DataFrame, as_of: pd.Timestamp, candidates: list[str]) -> float:
    if table is None or table.empty:
        return np.nan
    cols = table.columns[table.columns <= as_of]
    if len(cols) == 0:
        return np.nan
    latest_col = cols.max()
    for row in candidates:
        if row in table.index:
            value = table.loc[row, latest_col]
            if pd.notna(value):
                return float(value)
    return np.nan


def point_in_time_value(table: pd.DataFrame, as_of: pd.Timestamp, candidates: list[str], lag_quarters: int = 0) -> float:
    if table is None or table.empty:
        return np.nan

    cols = table.columns[table.columns <= as_of]
    if len(cols) <= lag_quarters:
        return np.nan

    cols = cols.sort_values()
    target_col = cols[-(lag_quarters + 1)]
    for row in candidates:
        if row in table.index:
            value = table.loc[row, target_col]
            if pd.notna(value):
                return float(value)
    return np.nan


def ttm_value(table: pd.DataFrame, as_of: pd.Timestamp, candidates: list[str], lag_quarters: int = 0) -> float:
    if table is None or table.empty:
        return np.nan
    cols = table.columns[table.columns <= as_of]
    if len(cols) < 4 + lag_quarters:
        return np.nan
    cols = cols.sort_values()
    use_cols = cols[-(4 + lag_quarters) : -lag_quarters if lag_quarters > 0 else None]
    if len(use_cols) != 4:
        return np.nan
    for row in candidates:
        if row in table.index:
            values = table.loc[row, use_cols]
            if values.notna().sum() == 4:
                return float(values.sum())
    return np.nan


def total_debt_value(table: pd.DataFrame, as_of: pd.Timestamp, lag_quarters: int = 0) -> float:
    direct = point_in_time_value(
        table,
        as_of,
        [
            "Total Debt",
            "Total Debt And Capital Lease Obligation",
            "Total Debt and Capital Lease Obligation",
        ],
        lag_quarters=lag_quarters,
    )
    if pd.notna(direct):
        return direct

    current_debt = point_in_time_value(
        table,
        as_of,
        [
            "Current Debt",
            "Current Debt And Capital Lease Obligation",
            "Current Debt and Capital Lease Obligation",
        ],
        lag_quarters=lag_quarters,
    )
    long_debt = point_in_time_value(
        table,
        as_of,
        [
            "Long Term Debt",
            "Long Term Debt And Capital Lease Obligation",
            "Long Term Debt and Capital Lease Obligation",
        ],
        lag_quarters=lag_quarters,
    )

    if pd.isna(current_debt) and pd.isna(long_debt):
        return np.nan

    return float((0.0 if pd.isna(current_debt) else current_debt) + (0.0 if pd.isna(long_debt) else long_debt))


def safe_div(num, den):
    if den is None or pd.isna(den) or den == 0:
        return np.nan
    if num is None or pd.isna(num):
        return np.nan
    return num / den


def average_pair(first: float, second: float) -> float:
    if pd.isna(first) or pd.isna(second):
        return np.nan
    return float((first + second) / 2.0)


def to_float_or_nan(value) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return np.nan
    return out if pd.notna(out) else np.nan


def infer_tax_rate(info: dict) -> float:
    country = str((info or {}).get("country", "")).strip().upper()
    if "CANADA" in country:
        return 0.265
    if "IRELAND" in country or country == "IRL":
        return 0.125
    # P123 example defaults to 21% for USA.
    return 0.21


def compute_return_bars(series: pd.Series, as_of: pd.Timestamp, bars: int, offset_bars: int = 0) -> float:
    if series is None or series.empty or bars <= 0 or offset_bars < 0:
        return np.nan

    end_date = nearest_on_or_before(series.index, as_of)
    if end_date is None:
        return np.nan

    end_pos = int(series.index.get_indexer([end_date])[0]) - int(offset_bars)
    if end_pos < 0:
        return np.nan

    start_pos = end_pos - int(bars)
    if start_pos < 0:
        return np.nan

    start_price = series.iloc[start_pos]
    end_price = series.iloc[end_pos]
    return safe_div(end_price - start_price, start_price)


def extract_current_fy_up_revision_4w(earnings_trend: pd.DataFrame, info: dict) -> float:
    if isinstance(earnings_trend, pd.DataFrame) and not earnings_trend.empty:
        trend = earnings_trend.copy()
        col_map = {str(col).lower(): col for col in trend.columns}
        current_col = col_map.get("current")
        prev_col = col_map.get("30daysago") or col_map.get("4weeksago")

        if current_col is not None and prev_col is not None:
            row = None
            for idx_name in ["0y", "0Y", "+0y", "cur", "current"]:
                if idx_name in trend.index:
                    row = trend.loc[idx_name]
                    break
            if row is None and len(trend.index) > 0:
                annual_like = trend.index.astype(str).str.contains("0y|fy|year|cur", case=False, regex=True)
                if annual_like.any():
                    row = trend.loc[annual_like].iloc[0]

            if row is not None:
                cur = to_float_or_nan(row[current_col])
                prev = to_float_or_nan(row[prev_col])
                if pd.notna(cur) and pd.notna(prev):
                    if prev == 0:
                        return float(cur - prev)
                    return safe_div(cur - prev, abs(prev))

    # Fallback proxy when revisions data is missing.
    for key in ["earningsQuarterlyGrowth", "earningsGrowth"]:
        val = to_float_or_nan((info or {}).get(key, np.nan))
        if pd.notna(val):
            return val
    return np.nan


def extract_insider_shares_purchased(insider_transactions: pd.DataFrame) -> float:
    if not isinstance(insider_transactions, pd.DataFrame) or insider_transactions.empty:
        return np.nan

    col_map = {str(col).lower(): col for col in insider_transactions.columns}

    shares_col = None
    for name in ["shares", "share", "sharestraded", "shares traded"]:
        if name in col_map:
            shares_col = col_map[name]
            break
    if shares_col is None:
        for lower_name, real_name in col_map.items():
            if "share" in lower_name:
                shares_col = real_name
                break
    if shares_col is None:
        return np.nan

    shares = pd.to_numeric(insider_transactions[shares_col], errors="coerce")

    txn_col = None
    for name in ["transaction", "text", "type"]:
        if name in col_map:
            txn_col = col_map[name]
            break

    if txn_col is not None:
        txn_txt = insider_transactions[txn_col].astype(str)
        buy_mask = txn_txt.str.contains("buy|purchase|acquir", case=False, regex=True, na=False)
        purchased = shares.where(buy_mask, 0.0)
    else:
        purchased = shares

    purchased = purchased.fillna(0.0)
    purchased = purchased.where(purchased > 0, 0.0)
    # P123 presents this as millions of shares.
    return float(purchased.sum() / 1_000_000.0)


def compute_return(series: pd.Series, as_of: pd.Timestamp, lookback_days: int, skip_recent_days: int = 0) -> float:
    if series is None or series.empty:
        return np.nan
    end_target = as_of - pd.Timedelta(days=skip_recent_days)
    start_target = end_target - pd.Timedelta(days=lookback_days)
    end_date = nearest_on_or_before(series.index, end_target)
    start_date = nearest_on_or_before(series.index, start_target)
    if end_date is None or start_date is None:
        return np.nan
    start_price = series.loc[start_date]
    end_price = series.loc[end_date]
    return safe_div(end_price - start_price, start_price)


def rolling_sharpe(series: pd.Series, as_of: pd.Timestamp, lookback_days: int) -> float:
    if series is None or series.empty:
        return np.nan
    start_target = as_of - pd.Timedelta(days=lookback_days)
    start_date = nearest_on_or_before(series.index, start_target)
    end_date = nearest_on_or_before(series.index, as_of)
    if start_date is None or end_date is None:
        return np.nan
    window = series.loc[start_date:end_date].pct_change().dropna()
    if len(window) < 40:
        return np.nan
    vol = window.std(ddof=0)
    if pd.isna(vol) or vol == 0:
        return np.nan
    return float((window.mean() / vol) * np.sqrt(252))


def cross_section_rank(df: pd.DataFrame, column: str, higher_is_better: bool = True) -> pd.Series:
    values = df[column]
    if not higher_is_better:
        values = -values
    return values.rank(method="average", pct=True)


def equal_weight_composite(df: pd.DataFrame, columns: list[str]) -> pd.Series:
    ranked = [cross_section_rank(df, col, higher_is_better=True) for col in columns]
    rank_df = pd.concat(ranked, axis=1)
    return rank_df.mean(axis=1, skipna=True)


def weighted_rank_composite(df: pd.DataFrame, components: list[tuple[str, float, bool]]) -> pd.Series:
    if df.empty:
        return pd.Series(index=df.index, dtype=float)

    rank_data = {}
    weights = {}
    for col, weight, higher_is_better in components:
        if col not in df.columns:
            continue
        rank_data[col] = cross_section_rank(df, col, higher_is_better=higher_is_better)
        weights[col] = float(weight)

    if not rank_data:
        return pd.Series(np.nan, index=df.index, dtype=float)

    rank_df = pd.DataFrame(rank_data, index=df.index)
    weight_s = pd.Series(weights)
    weighted = rank_df.mul(weight_s, axis=1)
    denom = rank_df.notna().mul(weight_s, axis=1).sum(axis=1)
    score = weighted.sum(axis=1, skipna=True)
    return score / denom.where(denom > 0, np.nan)


def get_price_matrix(tickers: list[str]) -> pd.DataFrame:
    raw = yf.download(
        tickers=tickers,
        start=START_DATE,
        end=(pd.to_datetime(END_DATE) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
        auto_adjust=True,
        progress=True,
        threads=True,
    )

    if raw.empty:
        return pd.DataFrame(index=pd.DatetimeIndex([], name="Date"), columns=tickers)

    if isinstance(raw.columns, pd.MultiIndex):
        price_field = "Close" if "Close" in raw.columns.get_level_values(0) else "Adj Close"
        close = raw.xs(price_field, axis=1, level=0, drop_level=True)

        if isinstance(close, pd.Series):
            series_name = tickers[0] if len(tickers) == 1 else (close.name or "price")
            close = close.rename(series_name).to_frame()
        elif len(tickers) == 1 and close.shape[1] != 1:
            close = close.iloc[:, [0]].rename(columns={close.columns[0]: tickers[0]})
    else:
        if "Close" in raw.columns:
            close = raw[["Close"]]
        elif "Adj Close" in raw.columns:
            close = raw[["Adj Close"]]
        elif raw.shape[1] == 1:
            close = raw.iloc[:, [0]]
        else:
            raise ValueError("Could not determine close-price column from download output.")
        close = close.rename(columns={close.columns[0]: tickers[0]})

    close = close.sort_index()
    close = close.dropna(how="all", axis=0)
    return close


def download_or_load_data(load_cache: bool):
    ensure_dir(DATA_DIR)

    if load_cache:
        required = [
            "tickers.pkl",
            "prices.pkl",
            "fundamentals.pkl",
            "spx.pkl",
        ]
        if all(os.path.exists(os.path.join(DATA_DIR, x)) for x in required):
            return {
                "tickers": load_pickle("tickers.pkl"),
                "prices": load_pickle("prices.pkl"),
                "fundamentals": load_pickle("fundamentals.pkl"),
                "spx": load_pickle("spx.pkl"),
            }
    tickers = []
    tickers += get_sp500_tickers()
    tickers += get_sp400_tickers()
    tickers += get_sp600_tickers()
    prices = get_price_matrix(tickers)

    fundamentals = {}
    for i, ticker in enumerate(tickers, start=1):
        try:
            stock = yf.Ticker(ticker)
            info = stock.info if stock.info else {}
            fin = to_timestamp_columns(stock.quarterly_financials)
            bs = to_timestamp_columns(stock.quarterly_balance_sheet)
            cf = to_timestamp_columns(stock.quarterly_cashflow)
            try:
                earnings_trend = stock.earnings_trend
            except Exception:
                earnings_trend = pd.DataFrame()
            try:
                insider_transactions = stock.insider_transactions
            except Exception:
                insider_transactions = pd.DataFrame()
            try:
                earnings_history = stock.earnings_history
            except Exception:
                earnings_history = pd.DataFrame()
            if not isinstance(earnings_trend, pd.DataFrame):
                earnings_trend = pd.DataFrame()
            if not isinstance(insider_transactions, pd.DataFrame):
                insider_transactions = pd.DataFrame()
            if not isinstance(earnings_history, pd.DataFrame):
                earnings_history = pd.DataFrame()

            fundamentals[ticker] = {
                "info": info,
                "fin": fin,
                "bs": bs,
                "cf": cf,
                "earnings_trend": earnings_trend,
                "insider_transactions": insider_transactions,
                "earnings_history": earnings_history,
            }
        except Exception as error:
            print(f"[{i}/{len(tickers)}] {ticker} fundamentals failed: {error}")
            fundamentals[ticker] = {
                "info": {},
                "fin": pd.DataFrame(),
                "bs": pd.DataFrame(),
                "cf": pd.DataFrame(),
                "earnings_trend": pd.DataFrame(),
                "insider_transactions": pd.DataFrame(),
                "earnings_history": pd.DataFrame(),
            }
        if i % 50 == 0:
            print(f"Fetched fundamentals: {i}/{len(tickers)}")

    spx = yf.download(
        "^GSPC",
        start=START_DATE,
        end=(pd.to_datetime(END_DATE) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
        auto_adjust=True,
        progress=False,
    )
    if isinstance(spx.columns, pd.MultiIndex):
        spx_close = spx.xs("Close", axis=1, level=0, drop_level=True)
        if isinstance(spx_close, pd.Series):
            spx = spx_close.rename("spx_close").to_frame()
        else:
            spx = spx_close.iloc[:, [0]].rename(columns={spx_close.columns[0]: "spx_close"})
    else:
        spx = spx[["Close"]].rename(columns={"Close": "spx_close"})

    save_pickle(tickers, "tickers.pkl")
    save_pickle(prices, "prices.pkl")
    save_pickle(fundamentals, "fundamentals.pkl")
    save_pickle(spx, "spx.pkl")

    return {"tickers": tickers, "prices": prices, "fundamentals": fundamentals, "spx": spx}


def extract_eps_surprise_q1(earnings_history: pd.DataFrame) -> float:
    """Return most-recent-quarter EPS surprise % (actual vs estimate).
    Matches P123 Surprise%Q1 — positive means beat."""
    if not isinstance(earnings_history, pd.DataFrame) or earnings_history.empty:
        return np.nan
    col_map = {str(col).lower().replace(" ", ""): col for col in earnings_history.columns}
    eps_actual_col = col_map.get("epsactual") or col_map.get("actual")
    eps_est_col = col_map.get("epsestimate") or col_map.get("estimate")
    if eps_actual_col is None or eps_est_col is None:
        return np.nan
    df = earnings_history.copy()
    df["_actual"] = pd.to_numeric(df[eps_actual_col], errors="coerce")
    df["_est"] = pd.to_numeric(df[eps_est_col], errors="coerce")
    df = df.dropna(subset=["_actual", "_est"])
    if df.empty:
        return np.nan
    latest = df.iloc[-1]
    est = float(latest["_est"])
    actual = float(latest["_actual"])
    if est == 0:
        return float(actual - est)
    return safe_div(actual - est, abs(est))


def compute_snapshot(as_of: pd.Timestamp, prices: pd.DataFrame, fundamentals: dict) -> pd.DataFrame:
    rows = []
    for ticker in prices.columns:
        px_series = prices[ticker].dropna()
        trade_date = nearest_on_or_before(px_series.index, as_of)
        if trade_date is None:
            continue

        px = float(px_series.loc[trade_date])
        f = fundamentals.get(
            ticker,
            {
                "info": {},
                "fin": pd.DataFrame(),
                "bs": pd.DataFrame(),
                "cf": pd.DataFrame(),
                "earnings_trend": pd.DataFrame(),
                "insider_transactions": pd.DataFrame(),
            },
        )
        info, fin, bs, cf = f["info"], f["fin"], f["bs"], f["cf"]
        earnings_trend = f.get("earnings_trend", pd.DataFrame())
        insider_transactions = f.get("insider_transactions", pd.DataFrame())
        earnings_history = f.get("earnings_history", pd.DataFrame())

        shares = info.get("sharesOutstanding", np.nan)
        marketcap = safe_div(px * shares, 1) if pd.notna(shares) else info.get("marketCap", np.nan)
        enterprise_value = info.get("enterpriseValue", np.nan)

        net_income_ttm = ttm_value(fin, as_of, ["Net Income", "Net Income Common Stockholders"])
        revenue_ttm = ttm_value(fin, as_of, ["Total Revenue", "Revenue"])
        ebitda_ttm = ttm_value(fin, as_of, ["EBITDA"])
        equity = point_in_time_value(
            bs,
            as_of,
            ["Total Stockholder Equity", "Total Stockholders Equity", "Total Equity", "Stockholders Equity"],
            lag_quarters=0,
        )
        equity_lag4 = point_in_time_value(
            bs,
            as_of,
            ["Total Stockholder Equity", "Total Stockholders Equity", "Total Equity", "Stockholders Equity"],
            lag_quarters=4,
        )

        operating_cf_ttm = ttm_value(cf, as_of, ["Operating Cash Flow", "Total Cash From Operating Activities"])
        capex_ttm = ttm_value(cf, as_of, ["Capital Expenditure", "Capital Expenditures"])
        fcf_ttm = np.nan
        if pd.notna(operating_cf_ttm) and pd.notna(capex_ttm):
            fcf_ttm = operating_cf_ttm + capex_ttm

        net_inc_cf_stmt_ttm = ttm_value(
            cf,
            as_of,
            ["Net Income", "Net Income From Continuing Operations"],
        )
        get_dep_and_amort_ttm = ttm_value(
            cf,
            as_of,
            [
                "Depreciation And Amortization",
                "Depreciation & Amortization",
                "Depreciation Amortization Depletion",
                "Depreciation",
            ],
        )

        revenue_ttm_lag4 = ttm_value(fin, as_of, ["Total Revenue", "Revenue"], lag_quarters=4)
        net_income_ttm_lag4 = ttm_value(fin, as_of, ["Net Income", "Net Income Common Stockholders"], lag_quarters=4)
        opcf_ttm_lag4 = ttm_value(cf, as_of, ["Operating Cash Flow", "Total Cash From Operating Activities"], lag_quarters=4)

        total_assets = point_in_time_value(bs, as_of, ["Total Assets"], lag_quarters=0)
        total_assets_lag4 = point_in_time_value(bs, as_of, ["Total Assets"], lag_quarters=4)
        total_assets_lag8 = point_in_time_value(bs, as_of, ["Total Assets"], lag_quarters=8)
        current_assets = point_in_time_value(bs, as_of, ["Current Assets", "Total Current Assets"], lag_quarters=0)
        current_assets_lag4 = point_in_time_value(bs, as_of, ["Current Assets", "Total Current Assets"], lag_quarters=4)
        current_liabilities = point_in_time_value(
            bs,
            as_of,
            ["Current Liabilities", "Total Current Liabilities"],
            lag_quarters=0,
        )
        current_liabilities_lag4 = point_in_time_value(
            bs,
            as_of,
            ["Current Liabilities", "Total Current Liabilities"],
            lag_quarters=4,
        )
        retained_earnings = point_in_time_value(bs, as_of, ["Retained Earnings"], lag_quarters=0)
        total_liabilities = point_in_time_value(
            bs,
            as_of,
            [
                "Total Liabilities Net Minority Interest",
                "Total Liabilities",
                "Total Liab",
            ],
            lag_quarters=0,
        )

        net_ppe = point_in_time_value(
            bs,
            as_of,
            [
                "Net PPE",
                "Property Plant Equipment Net",
                "Property, Plant & Equipment Net",
                "Property Plant Equipment",
            ],
            lag_quarters=0,
        )
        net_ppe_lag4 = point_in_time_value(
            bs,
            as_of,
            [
                "Net PPE",
                "Property Plant Equipment Net",
                "Property, Plant & Equipment Net",
                "Property Plant Equipment",
            ],
            lag_quarters=4,
        )

        receivables = point_in_time_value(
            bs,
            as_of,
            ["Accounts Receivable", "Accounts Receivable Net", "Net Receivables"],
            lag_quarters=0,
        )
        receivables_lag4 = point_in_time_value(
            bs,
            as_of,
            ["Accounts Receivable", "Accounts Receivable Net", "Net Receivables"],
            lag_quarters=4,
        )

        cogs_ttm = ttm_value(fin, as_of, ["Cost Of Revenue", "Cost of Revenue"])
        cogs_ttm_lag4 = ttm_value(fin, as_of, ["Cost Of Revenue", "Cost of Revenue"], lag_quarters=4)
        sga_ttm = ttm_value(
            fin,
            as_of,
            [
                "Selling General And Administration",
                "Selling General Administrative",
                "Selling And Marketing Expense",
                "General And Administrative Expense",
            ],
        )
        sga_ttm_lag4 = ttm_value(
            fin,
            as_of,
            [
                "Selling General And Administration",
                "Selling General Administrative",
                "Selling And Marketing Expense",
                "General And Administrative Expense",
            ],
            lag_quarters=4,
        )

        dep_amort_ttm_lag4 = ttm_value(
            cf,
            as_of,
            [
                "Depreciation And Amortization",
                "Depreciation & Amortization",
                "Depreciation Amortization Depletion",
                "Depreciation",
            ],
            lag_quarters=4,
        )

        total_debt = total_debt_value(bs, as_of, lag_quarters=0)
        total_debt_lag4 = total_debt_value(bs, as_of, lag_quarters=4)
        ebit_ttm = ttm_value(fin, as_of, ["EBIT", "Operating Income"])
        operating_income_ttm = ttm_value(fin, as_of, ["Operating Income", "EBIT"])
        interest_expense_ttm = ttm_value(
            fin,
            as_of,
            ["Interest Expense", "Interest Expense Non Operating", "Net Non Operating Interest Income Expense"],
        )
        if pd.notna(interest_expense_ttm):
            interest_expense_ttm = abs(interest_expense_ttm)

        shares_q = point_in_time_value(
            bs,
            as_of,
            ["Ordinary Shares Number", "Share Issued", "Common Stock Shares Outstanding", "Shares Outstanding"],
            lag_quarters=0,
        )
        shares_pyq = point_in_time_value(
            bs,
            as_of,
            ["Ordinary Shares Number", "Share Issued", "Common Stock Shares Outstanding", "Shares Outstanding"],
            lag_quarters=4,
        )

        avg_assets_ttm = average_pair(total_assets, total_assets_lag4)
        avg_assets_ptm = average_pair(total_assets_lag4, total_assets_lag8)
        avg_equity_ttm = average_pair(equity, equity_lag4)

        total_capital = np.nan
        if pd.notna(total_debt) and pd.notna(equity):
            total_capital = total_debt + equity
        total_capital_lag4 = np.nan
        if pd.notna(total_debt_lag4) and pd.notna(equity_lag4):
            total_capital_lag4 = total_debt_lag4 + equity_lag4
        avg_total_capital_ttm = average_pair(total_capital, total_capital_lag4)

        tax_rate = infer_tax_rate(info)
        interest_after_tax = 0.0 if pd.isna(interest_expense_ttm) else (interest_expense_ttm * (1.0 - tax_rate))
        roi_numerator_ttm = net_income_ttm + interest_after_tax if pd.notna(net_income_ttm) else np.nan

        roa_pct_ttm = 100.0 * safe_div(net_income_ttm, avg_assets_ttm)
        roa_pct_ptm = 100.0 * safe_div(net_income_ttm_lag4, avg_assets_ptm)
        roe_pct_ttm = 100.0 * safe_div(net_income_ttm, avg_equity_ttm)
        roi_pct_ttm = 100.0 * safe_div(roi_numerator_ttm, avg_total_capital_ttm)

        working_capital = (
            current_assets - current_liabilities if pd.notna(current_assets) and pd.notna(current_liabilities) else np.nan
        )
        altman_x1 = safe_div(working_capital, total_assets)
        altman_x2 = safe_div(retained_earnings, total_assets)
        altman_x3 = safe_div(ebit_ttm, total_assets)
        altman_x4 = safe_div(marketcap, total_liabilities)
        altman_x5 = safe_div(revenue_ttm, total_assets)
        altman_x4_rev = safe_div(total_liabilities, marketcap)
        altman_z_orig = np.nan
        if pd.notna(altman_x1) and pd.notna(altman_x2) and pd.notna(altman_x3) and pd.notna(altman_x4) and pd.notna(altman_x5):
            altman_z_orig = 1.2 * altman_x1 + 1.4 * altman_x2 + 3.3 * altman_x3 + 0.6 * altman_x4 + 1.0 * altman_x5

        mscore_dsri = safe_div(
            safe_div(receivables, revenue_ttm),
            safe_div(receivables_lag4, revenue_ttm_lag4),
        )

        gross_margin = safe_div(revenue_ttm - cogs_ttm, revenue_ttm)
        gross_margin_lag4 = safe_div(revenue_ttm_lag4 - cogs_ttm_lag4, revenue_ttm_lag4)
        gmgn_pct_ttm = 100.0 * gross_margin if pd.notna(gross_margin) else np.nan
        gmgn_pct_ptm = 100.0 * gross_margin_lag4 if pd.notna(gross_margin_lag4) else np.nan
        mscore_gmi = safe_div(gross_margin_lag4, gross_margin)

        asset_quality = 1.0 - safe_div((current_assets + net_ppe), total_assets)
        asset_quality_lag4 = 1.0 - safe_div((current_assets_lag4 + net_ppe_lag4), total_assets_lag4)
        mscore_aqi = safe_div(asset_quality, asset_quality_lag4)

        dep_rate = safe_div(get_dep_and_amort_ttm, get_dep_and_amort_ttm + net_ppe)
        dep_rate_lag4 = safe_div(dep_amort_ttm_lag4, dep_amort_ttm_lag4 + net_ppe_lag4)
        mscore_depi = safe_div(dep_rate_lag4, dep_rate)
        mscore_depami = mscore_depi

        mscore_sgi = safe_div(revenue_ttm, revenue_ttm_lag4)
        mscore_sgai = safe_div(
            safe_div(sga_ttm, revenue_ttm),
            safe_div(sga_ttm_lag4, revenue_ttm_lag4),
        )

        mscore_lvgi = safe_div(
            safe_div(total_debt, total_assets),
            safe_div(total_debt_lag4, total_assets_lag4),
        )
        mscore_tata = safe_div(operating_income_ttm - operating_cf_ttm, total_assets)

        beneish_m_score = np.nan
        m_components = [
            mscore_dsri,
            mscore_gmi,
            mscore_aqi,
            mscore_sgi,
            mscore_depi,
            mscore_sgai,
            mscore_tata,
            mscore_lvgi,
        ]
        if all(pd.notna(value) for value in m_components):
            beneish_m_score = (
                -4.84
                + (0.92 * mscore_dsri)
                + (0.528 * mscore_gmi)
                + (0.404 * mscore_aqi)
                + (0.892 * mscore_sgi)
                + (0.115 * mscore_depi)
                - (0.172 * mscore_sgai)
                + (4.679 * mscore_tata)
                - (0.327 * mscore_lvgi)
            )

        current_ratio_q = safe_div(current_assets, current_liabilities)
        current_ratio_pyq = safe_div(current_assets_lag4, current_liabilities_lag4)
        debt_to_assets_q = safe_div(total_debt, total_assets)
        debt_to_assets_pyq = safe_div(total_debt_lag4, total_assets_lag4)
        asset_turn_ttm = safe_div(revenue_ttm, avg_assets_ttm)
        asset_turn_ptm = safe_div(revenue_ttm_lag4, avg_assets_ptm)

        piot_f_score = 0
        piot_f_score += int(pd.notna(roa_pct_ttm) and roa_pct_ttm > 0)
        piot_f_score += int(pd.notna(operating_cf_ttm) and operating_cf_ttm > 0)
        piot_f_score += int(pd.notna(roa_pct_ttm) and pd.notna(roa_pct_ptm) and roa_pct_ttm > roa_pct_ptm)
        piot_f_score += int(pd.notna(operating_cf_ttm) and pd.notna(net_inc_cf_stmt_ttm) and operating_cf_ttm > net_inc_cf_stmt_ttm)
        piot_f_score += int(pd.notna(debt_to_assets_q) and pd.notna(debt_to_assets_pyq) and debt_to_assets_q < debt_to_assets_pyq)
        piot_f_score += int(pd.notna(current_ratio_q) and pd.notna(current_ratio_pyq) and current_ratio_q > current_ratio_pyq)
        piot_f_score += int(pd.notna(shares_q) and pd.notna(shares_pyq) and shares_q <= shares_pyq)
        piot_f_score += int(pd.notna(gmgn_pct_ttm) and pd.notna(gmgn_pct_ptm) and gmgn_pct_ttm > gmgn_pct_ptm)
        piot_f_score += int(pd.notna(asset_turn_ttm) and pd.notna(asset_turn_ptm) and asset_turn_ttm > asset_turn_ptm)

        ev2ebitda_ttm = safe_div(enterprise_value, ebitda_ttm)
        ev2sales_ttm = safe_div(enterprise_value, revenue_ttm)

        pr13w = compute_return_bars(px_series, trade_date, bars=65)
        pr26w = compute_return_bars(px_series, trade_date, bars=130)
        pr52w = compute_return_bars(px_series, trade_date, bars=260)
        pr13w_pct_chg = 100.0 * pr13w if pd.notna(pr13w) else np.nan
        pr26w_pct_chg = 100.0 * pr26w if pd.notna(pr26w) else np.nan
        pr52w_pct_chg = 100.0 * pr52w if pd.notna(pr52w) else np.nan

        cur_fy_up_rev_4wk_ago = extract_current_fy_up_revision_4w(earnings_trend, info)
        eps_surprise_q1 = extract_eps_surprise_q1(earnings_history)

        # --- Additional P123-aligned factors ---
        gross_profit_ttm = np.nan
        if pd.notna(revenue_ttm) and pd.notna(cogs_ttm):
            gross_profit_ttm = revenue_ttm - cogs_ttm

        op_mgn_pct_ttm = 100.0 * safe_div(operating_income_ttm, revenue_ttm)
        net_profit_mgn_pct_ttm = 100.0 * safe_div(net_income_ttm, revenue_ttm)

        # Accruals to total assets: (OpInc - OpCF) / TotAssets — lower is better (AccrualsTTM/AstTot)
        accruals_to_assets = safe_div(
            (operating_income_ttm - operating_cf_ttm)
            if pd.notna(operating_income_ttm) and pd.notna(operating_cf_ttm)
            else np.nan,
            total_assets,
        )

        # Cash flow quality: OpCF / |NetInc| — higher is better
        opcf_to_net_income = np.nan
        if pd.notna(operating_cf_ttm) and pd.notna(net_income_ttm) and net_income_ttm != 0:
            opcf_to_net_income = safe_div(operating_cf_ttm, abs(net_income_ttm))
        elif pd.notna(operating_cf_ttm):
            opcf_to_net_income = 0.0

        # Total asset growth YoY — lower is better
        total_asset_growth = safe_div(total_assets - total_assets_lag4, abs(total_assets_lag4)) if pd.notna(total_assets_lag4) and total_assets_lag4 != 0 else np.nan

        # CapEx intensity: CapEx / Sales — lower is better
        capex_to_sales = safe_div(abs(capex_ttm), revenue_ttm) if pd.notna(capex_ttm) else np.nan

        # Interest coverage: EBIT / IntExp — higher is better
        int_cov_ttm = safe_div(ebit_ttm, interest_expense_ttm) if pd.notna(interest_expense_ttm) and interest_expense_ttm > 0 else np.nan

        # Debt to total capital — lower is better
        dbt_tot_2_cap = safe_div(total_debt, total_capital) if pd.notna(total_capital) and total_capital != 0 else np.nan

        # Forward earnings yield: forwardEps / price
        forward_eps = to_float_or_nan(info.get("forwardEps", np.nan))
        forward_earnings_yield = safe_div(forward_eps, px) if pd.notna(forward_eps) and px > 0 else np.nan

        # Gross profit to EV — higher is better
        gross_profit_to_ev = safe_div(gross_profit_ttm, enterprise_value)

        # Short days-to-cover ratio — lower is better (SIRatio)
        si_ratio = to_float_or_nan(info.get("shortRatio", np.nan))

        si_pct_float = to_float_or_nan(info.get("shortPercentOfFloat", np.nan))
        if pd.isna(si_pct_float):
            shares_short = to_float_or_nan(info.get("sharesShort", np.nan))
            float_shares = to_float_or_nan(info.get("floatShares", np.nan))
            shares_outstanding = to_float_or_nan(info.get("sharesOutstanding", shares))
            if pd.notna(shares_short):
                if pd.notna(float_shares) and float_shares > 0:
                    si_pct_float = safe_div(shares_short, float_shares)
                elif pd.notna(shares_outstanding) and shares_outstanding > 0:
                    si_pct_float = safe_div(shares_short, shares_outstanding)

        ins_shr_purch = extract_insider_shares_purchased(insider_transactions)

        mom_12_1 = compute_return(px_series, as_of, lookback_days=365, skip_recent_days=21)
        mom_6m = compute_return(px_series, as_of, lookback_days=182, skip_recent_days=0)
        sharpe_6m = rolling_sharpe(px_series, as_of, lookback_days=182)

        row = {
            "ticker": ticker,
            "date": as_of,
            "price": px,
            "marketcap": marketcap,
            "shares_fd": shares,
            "sales": revenue_ttm,
            "ast_tot": total_assets,
            "get_dep_and_amort": get_dep_and_amort_ttm,
            "net_inc_cf_stmt": net_inc_cf_stmt_ttm,
            "altman_x1": altman_x1,
            "altman_x2": altman_x2,
            "altman_x3": altman_x3,
            "altman_x4": altman_x4,
            "altman_x5": altman_x5,
            "altman_x4_rev": altman_x4_rev,
            "altman_z_orig": altman_z_orig,
            "beneish_m_score": beneish_m_score,
            "mscore_aqi": mscore_aqi,
            "mscore_depami": mscore_depami,
            "mscore_depi": mscore_depi,
            "mscore_dsri": mscore_dsri,
            "mscore_gmi": mscore_gmi,
            "mscore_lvgi": mscore_lvgi,
            "mscore_sgai": mscore_sgai,
            "mscore_sgi": mscore_sgi,
            "mscore_tata": mscore_tata,
            "fcf_yield": safe_div(fcf_ttm, marketcap),
            "earnings_yield": safe_div(net_income_ttm, marketcap),
            "sales_yield": safe_div(revenue_ttm, marketcap),
            "book_to_market": safe_div(equity, marketcap),
            "ebitda_ev": safe_div(ebitda_ttm, enterprise_value),
            "roe_pct_ttm": roe_pct_ttm,
            "roi_pct_ttm": roi_pct_ttm,
            "roa_pct_ttm": roa_pct_ttm,
            "gmgn_pct_ttm": gmgn_pct_ttm,
            "piot_f_score": float(piot_f_score),
            "ev2ebitda_ttm": ev2ebitda_ttm,
            "ev2sales_ttm": ev2sales_ttm,
            "pr13w_pct_chg": pr13w_pct_chg,
            "pr26w_pct_chg": pr26w_pct_chg,
            "pr52w_pct_chg": pr52w_pct_chg,
            "cur_fy_up_rev_4wk_ago": cur_fy_up_rev_4wk_ago,
            "si_pct_float": si_pct_float,
            "ins_shr_purch": ins_shr_purch,
            "ROE%TTM": roe_pct_ttm,
            "ROI%TTM": roi_pct_ttm,
            "ROA%TTM": roa_pct_ttm,
            "AltmanZOrig": altman_z_orig,
            "PiotFScore": float(piot_f_score),
            "GMgn%TTM": gmgn_pct_ttm,
            "EV2EBITDATTM": ev2ebitda_ttm,
            "EV2SalesTTM": ev2sales_ttm,
            "Pr13W%Chg": pr13w_pct_chg,
            "Pr26W%Chg": pr26w_pct_chg,
            "Pr52W%Chg": pr52w_pct_chg,
            "CurFYUpRev4WkAgo": cur_fy_up_rev_4wk_ago,
            "SI%Float": si_pct_float,
            "Ins#ShrPurch": ins_shr_purch,
            "mom_12_1": mom_12_1,
            "mom_6m": mom_6m,
            "mom_sharpe_6m": sharpe_6m,
            "revenue_growth_yoy": safe_div(revenue_ttm - revenue_ttm_lag4, abs(revenue_ttm_lag4)),
            "earnings_growth_yoy": safe_div(net_income_ttm - net_income_ttm_lag4, abs(net_income_ttm_lag4)),
            "opcf_growth_yoy": safe_div(operating_cf_ttm - opcf_ttm_lag4, abs(opcf_ttm_lag4)),
            # --- Additional P123-aligned factors ---
            "gross_profit_ttm": gross_profit_ttm,
            "op_mgn_pct_ttm": op_mgn_pct_ttm,
            "net_profit_mgn_pct_ttm": net_profit_mgn_pct_ttm,
            "accruals_to_assets": accruals_to_assets,
            "opcf_to_net_income": opcf_to_net_income,
            "total_asset_growth": total_asset_growth,
            "capex_to_sales": capex_to_sales,
            "int_cov_ttm": int_cov_ttm,
            "dbt_tot_2_cap": dbt_tot_2_cap,
            "forward_earnings_yield": forward_earnings_yield,
            "gross_profit_to_ev": gross_profit_to_ev,
            "eps_surprise_q1": eps_surprise_q1,
            "si_ratio": si_ratio,
            # P123-style aliases
            "OpMgn%TTM": op_mgn_pct_ttm,
            "NPMgn%TTM": net_profit_mgn_pct_ttm,
            "AstTurnTTM": asset_turn_ttm,
            "IntCovTTM": int_cov_ttm,
            "DbtTot2CapQ": dbt_tot_2_cap,
            "Surprise%Q1": eps_surprise_q1,
            "SIRatio": si_ratio,
        }
        rows.append(row)

    snapshot = pd.DataFrame(rows)
    snapshot = snapshot.replace([np.inf, -np.inf], np.nan)
    snapshot = snapshot.dropna(subset=["price"])
    return snapshot


def build_rebalance_dates(prices: pd.DataFrame) -> list[pd.Timestamp]:
    q_dates = pd.date_range(start=START_DATE, end=END_DATE, freq=REBALANCE_FREQ)
    rebalance_dates = []
    for q in q_dates:
        d = nearest_on_or_before(prices.index, pd.Timestamp(q))
        if d is not None:
            rebalance_dates.append(pd.Timestamp(d))
    rebalance_dates = sorted(set(rebalance_dates))
    return rebalance_dates


def apply_rank_tolerance(ranked: pd.DataFrame, prev_holdings: set[str]) -> list[str]:
    ordered = ranked["ticker"].tolist()
    if not ordered:
        return []

    if len(prev_holdings) == 0:
        return ordered[:TOP_N]

    tolerance_rank = int(np.ceil(len(ordered) * RANK_TOLERANCE_PCT))
    tolerance_rank = max(tolerance_rank, TOP_N)

    rank_pos = {ticker: i + 1 for i, ticker in enumerate(ordered)}
    kept = [t for t in prev_holdings if t in rank_pos and rank_pos[t] <= tolerance_rank]

    selected = list(kept)
    for ticker in ordered:
        if ticker in selected:
            continue
        selected.append(ticker)
        if len(selected) >= TOP_N:
            break

    return selected[:TOP_N]


def apply_multifactor_retention(
    ranked: pd.DataFrame,
    prev_holdings: set[str],
    hold_periods: dict[str, int],
    prices: pd.DataFrame,
    prev_rebal_date: Optional[pd.Timestamp],
    rebal_date: pd.Timestamp,
) -> list[str]:
    ordered = ranked["ticker"].tolist()
    if not ordered and not prev_holdings:
        return []

    if len(prev_holdings) == 0:
        return ordered[:TOP_N]

    tolerance_rank = int(np.ceil(max(len(ordered), 1) * RANK_TOLERANCE_PCT))
    tolerance_rank = max(tolerance_rank, TOP_N)

    hard_drop_rank = int(np.ceil(max(len(ordered), 1) * MULTIFACTOR_HARD_DROP_RANK_PCT))
    hard_drop_rank = max(hard_drop_rank, tolerance_rank, TOP_N)

    rank_pos = {ticker: i + 1 for i, ticker in enumerate(ordered)}
    kept = []

    for ticker in sorted(prev_holdings):
        hold_len = hold_periods.get(ticker, 0)
        force_keep = hold_len < MULTIFACTOR_MIN_HOLD_REBALANCES

        pos = rank_pos.get(ticker)
        winner_keep = False
        tolerance_keep = pos is not None and pos <= tolerance_rank

        if pos is not None and prev_rebal_date is not None:
            period_ret = trailing_return_until_date(
                prices,
                ticker,
                rebal_date,
                MULTIFACTOR_WINNER_LOOKBACK_DAYS,
            )
            if pd.notna(period_ret) and period_ret > 0 and pos <= hard_drop_rank:
                winner_keep = True

        if force_keep or winner_keep or tolerance_keep:
            kept.append(ticker)

    selected = list(kept)
    for ticker in ordered:
        if ticker in selected:
            continue
        selected.append(ticker)
        if len(selected) >= TOP_N:
            break

    return selected[:TOP_N]


def apply_core_combination_estimate_rules(ranked: pd.DataFrame, prev_holdings: set[str]) -> list[str]:
    if ranked is None or ranked.empty:
        return []

    estimate_entry_floor = 1.0 - ESTIMATE_ENTRY_TOP_PCT
    estimate_exit_floor = 1.0 - ESTIMATE_EXIT_TOP_PCT

    ordered = ranked.sort_values("core_rank_pct", ascending=False).reset_index(drop=True)
    row_map = ordered.set_index("ticker")

    selected = []
    if prev_holdings:
        for ticker in sorted(prev_holdings):
            if ticker not in row_map.index:
                continue

            estimate_rank_pct = row_map.loc[ticker, "estimate_rank_pct"]
            core_rank_pct = row_map.loc[ticker, "core_rank_pct"]

            if pd.isna(estimate_rank_pct) or pd.isna(core_rank_pct):
                continue

            # Sell only if BOTH estimate rank and core rank break the exit thresholds.
            estimate_below_exit = estimate_rank_pct < estimate_exit_floor
            core_below_exit = core_rank_pct < CORE_RANK_EXIT_THRESHOLD
            if not (estimate_below_exit and core_below_exit):
                selected.append(ticker)

    buy_candidates = ordered[ordered["estimate_rank_pct"] >= estimate_entry_floor]
    for ticker in buy_candidates["ticker"].tolist():
        if ticker in selected:
            continue
        selected.append(ticker)
        if len(selected) >= TOP_N:
            break

    return selected[:TOP_N]


def get_strategy_rankings(snapshot: pd.DataFrame) -> dict[str, pd.DataFrame]:
    universe = snapshot.copy()
    universe = universe.dropna(subset=["marketcap"])
    universe = universe[universe["marketcap"] > 0]

    universe["single_metric_score"] = cross_section_rank(universe, "fcf_yield", True)

    value_cols = ["fcf_yield", "earnings_yield", "sales_yield", "book_to_market", "ebitda_ev"]
    universe["value_score"] = equal_weight_composite(universe, value_cols)

    tech_cols = ["mom_12_1", "mom_6m", "mom_sharpe_6m"]
    universe["technical_score"] = equal_weight_composite(universe, tech_cols)

    fund_mom_cols = ["revenue_growth_yoy", "earnings_growth_yoy", "opcf_growth_yoy"]
    universe["fundamental_mom_score"] = equal_weight_composite(universe, fund_mom_cols)

    universe["multifactor_score"] = universe[["value_score", "technical_score", "fundamental_mom_score"]].mean(axis=1, skipna=True)

    # 100% SQGLP+ST
    universe["q_quality_score"] = weighted_rank_composite(
        universe,
        [
            ("roe_pct_ttm", 1.0 / 3.0, True),
            ("roi_pct_ttm", 1.0 / 3.0, True),
            ("roa_pct_ttm", 1.0 / 3.0, True),
        ],
    )
    universe["l_longevity_score"] = weighted_rank_composite(
        universe,
        [
            ("altman_z_orig", 1.0 / 3.0, True),
            ("piot_f_score", 1.0 / 3.0, True),
            ("gmgn_pct_ttm", 1.0 / 3.0, True),
        ],
    )
    universe["p_price_score"] = weighted_rank_composite(
        universe,
        [
            ("ev2ebitda_ttm", 0.5, False),
            ("ev2sales_ttm", 0.5, False),
        ],
    )
    universe["t_timing_score"] = weighted_rank_composite(
        universe,
        [
            ("pr13w_pct_chg", 1.0 / 3.0, True),
            ("pr26w_pct_chg", 1.0 / 3.0, True),
            ("pr52w_pct_chg", 1.0 / 3.0, True),
        ],
    )
    universe["s_sentiment_score"] = weighted_rank_composite(
        universe,
        [
            ("cur_fy_up_rev_4wk_ago", 0.4, True),
            ("si_pct_float", 0.4, False),
            ("ins_shr_purch", 0.2, True),
        ],
    )
    universe["sqglp_st_score"] = weighted_rank_composite(
        universe,
        [
            ("q_quality_score", 0.10, True),
            ("l_longevity_score", 0.20, True),
            ("p_price_score", 0.40, True),
            ("t_timing_score", 0.20, True),
            ("s_sentiment_score", 0.10, True),
        ],
    )
    universe["SQGLP+ST"] = universe["sqglp_st_score"]
    universe["core_rank_pct"] = cross_section_rank(universe, "sqglp_st_score", True)
    universe["estimate_rank_pct"] = cross_section_rank(universe, "cur_fy_up_rev_4wk_ago", True)

    # -----------------------------------------------------------------------
    # Penman & Pope ranking system — mirrors the verified P123 XML example.
    # Five composites: Valuation (30%), Operating Profitability (30%),
    # Earnings Quality (20%), Investment Risk (10%), Financial Leverage (10%).
    # -----------------------------------------------------------------------

    # Valuation (30%): Earnings Yield 40%, Book/Price 35%, EV Yield 25%
    # Earnings Yield sub-node: TTM earnings yield 60%, forward earnings yield 40%
    # EV Yield sub-node: EBITDA/EV 60%, EV/Sales (lower) 40%
    universe["pp_valuation_score"] = weighted_rank_composite(
        universe,
        [
            ("earnings_yield", 0.24, True),          # 40% × 60%
            ("forward_earnings_yield", 0.16, True),  # 40% × 40%
            ("book_to_market", 0.35, True),          # 35% (= 1/P2B, higher = cheaper)
            ("ebitda_ev", 0.15, True),               # 25% × 60%
            ("ev2sales_ttm", 0.10, False),           # 25% × 40% (lower is better)
        ],
    )

    # Operating Profitability (30%): ROI 40%, Op Margin 30%, Asset Turnover 30%
    universe["pp_profitability_score"] = weighted_rank_composite(
        universe,
        [
            ("roi_pct_ttm", 0.40, True),
            ("op_mgn_pct_ttm", 0.30, True),
            ("asset_turn_ttm", 0.30, True),
        ],
    )

    # Earnings Quality (20%): Accruals/Assets 50% (lower=better), OpCF/NetInc 50%
    universe["pp_quality_score"] = weighted_rank_composite(
        universe,
        [
            ("accruals_to_assets", 0.50, False),
            ("opcf_to_net_income", 0.50, True),
        ],
    )

    # Investment Risk (10%): Total Asset Growth 60% (lower=better), CapEx/Sales 40%
    universe["pp_inv_risk_score"] = weighted_rank_composite(
        universe,
        [
            ("total_asset_growth", 0.60, False),
            ("capex_to_sales", 0.40, False),
        ],
    )

    # Financial Leverage (10%): Interest Coverage 50%, Debt/Capital 50% (lower=better)
    universe["pp_leverage_score"] = weighted_rank_composite(
        universe,
        [
            ("int_cov_ttm", 0.50, True),
            ("dbt_tot_2_cap", 0.50, False),
        ],
    )

    universe["p123_penman_pope_score"] = weighted_rank_composite(
        universe,
        [
            ("pp_valuation_score", 0.30, True),
            ("pp_profitability_score", 0.30, True),
            ("pp_quality_score", 0.20, True),
            ("pp_inv_risk_score", 0.10, True),
            ("pp_leverage_score", 0.10, True),
        ],
    )

    # Enhanced Penman-Pope screen: keep valuation/profitability core,
    # then add practical balance-sheet, accrual, and crowding guards.
    pp_enhanced_screen = (
        (universe["marketcap"] >= 1_000_000_000)
        & (universe["roi_pct_ttm"] > 3.0)
        & (universe["op_mgn_pct_ttm"] > 3.0)
        & (universe["accruals_to_assets"] < 0.10)
        & ((universe["int_cov_ttm"] > 1.5) | (universe["dbt_tot_2_cap"] < 0.60))
        & (universe["total_asset_growth"] < 0.35)
        & (universe["si_ratio"].fillna(0.0) < 10.0)
    )

    screened_universe = universe[pp_enhanced_screen].copy()
    if len(screened_universe) < TOP_N:
        screened_universe = universe.copy()

    screened_universe["p123_penman_pope_enhanced_score"] = weighted_rank_composite(
        screened_universe,
        [
            ("p123_penman_pope_score", 0.55, True),
            ("mom_12_1", 0.20, True),
            ("cur_fy_up_rev_4wk_ago", 0.15, True),
            ("si_ratio", 0.10, False),
        ],
    )

    # Defensive variant: tighter balance-sheet and quality controls.
    pp_defensive_screen = (
        (universe["marketcap"] >= 2_000_000_000)
        & (universe["roi_pct_ttm"] > 6.0)
        & (universe["op_mgn_pct_ttm"] > 6.0)
        & (universe["accruals_to_assets"] < 0.06)
        & (universe["int_cov_ttm"] > 3.0)
        & (universe["dbt_tot_2_cap"] < 0.50)
        & (universe["total_asset_growth"] < 0.25)
        & (universe["si_ratio"].fillna(0.0) < 7.0)
    )
    pp_defensive_universe = universe[pp_defensive_screen].copy()
    if len(pp_defensive_universe) < TOP_N:
        pp_defensive_universe = screened_universe.copy() if len(screened_universe) >= TOP_N else universe.copy()

    pp_defensive_universe["p123_penman_pope_defensive_score"] = weighted_rank_composite(
        pp_defensive_universe,
        [
            ("p123_penman_pope_score", 0.60, True),
            ("pp_quality_score", 0.20, True),
            ("pp_leverage_score", 0.10, True),
            ("mom_sharpe_6m", 0.10, True),
        ],
    )

    # Aggressive variant: deeper value + revisions + momentum with looser risk gates.
    pp_aggressive_screen = (
        (universe["marketcap"] >= 750_000_000)
        & (universe["roi_pct_ttm"] > 0.0)
        & (universe["op_mgn_pct_ttm"] > 0.0)
        & (universe["accruals_to_assets"] < 0.18)
        & ((universe["int_cov_ttm"] > 1.0) | (universe["dbt_tot_2_cap"] < 0.70))
        & (universe["total_asset_growth"] < 0.60)
        & (universe["si_ratio"].fillna(0.0) < 14.0)
    )
    pp_aggressive_universe = universe[pp_aggressive_screen].copy()
    if len(pp_aggressive_universe) < TOP_N:
        pp_aggressive_universe = universe.copy()

    pp_aggressive_universe["p123_penman_pope_aggressive_score"] = weighted_rank_composite(
        pp_aggressive_universe,
        [
            ("p123_penman_pope_score", 0.40, True),
            ("book_to_market", 0.20, True),
            ("earnings_yield", 0.20, True),
            ("mom_12_1", 0.10, True),
            ("cur_fy_up_rev_4wk_ago", 0.10, True),
        ],
    )

    mapping = {
        "single_metric": "single_metric_score",
        "value_composite": "value_score",
        "multifactor": "multifactor_score",
        "sqglp_st": "sqglp_st_score",
        "p123_penman_pope": "p123_penman_pope_score",
    }
    rankings = {}
    for name, score_col in mapping.items():
        ranked = universe.dropna(subset=[score_col]).sort_values(score_col, ascending=False)
        rankings[name] = ranked[["ticker", score_col]].reset_index(drop=True)

    pp_enhanced_ranked = screened_universe.dropna(subset=["p123_penman_pope_enhanced_score"]).sort_values(
        "p123_penman_pope_enhanced_score",
        ascending=False,
    )
    rankings["p123_penman_pope_enhanced"] = pp_enhanced_ranked[
        ["ticker", "p123_penman_pope_enhanced_score"]
    ].reset_index(drop=True)

    pp_defensive_ranked = pp_defensive_universe.dropna(subset=["p123_penman_pope_defensive_score"]).sort_values(
        "p123_penman_pope_defensive_score",
        ascending=False,
    )
    rankings["p123_penman_pope_defensive"] = pp_defensive_ranked[
        ["ticker", "p123_penman_pope_defensive_score"]
    ].reset_index(drop=True)

    pp_aggressive_ranked = pp_aggressive_universe.dropna(subset=["p123_penman_pope_aggressive_score"]).sort_values(
        "p123_penman_pope_aggressive_score",
        ascending=False,
    )
    rankings["p123_penman_pope_aggressive"] = pp_aggressive_ranked[
        ["ticker", "p123_penman_pope_aggressive_score"]
    ].reset_index(drop=True)

    core_cols = ["ticker", "sqglp_st_score", "core_rank_pct", "estimate_rank_pct"]
    core_ranked = universe.dropna(subset=["sqglp_st_score", "core_rank_pct", "estimate_rank_pct"]).sort_values(
        "core_rank_pct",
        ascending=False,
    )
    rankings["core_combination_estimates"] = core_ranked[core_cols].reset_index(drop=True)

    return rankings


def calculate_capital_at_rebalance_dates(
    prices: pd.DataFrame,
    selections: dict[pd.Timestamp, list[str]],
    rebalance_dates: list[pd.Timestamp]
) -> dict[pd.Timestamp, float]:
    """Calculate capital at each rebalance point given selections."""
    capital_history = {rebalance_dates[0]: STARTING_CAPITAL}
    dates = sorted(selections.keys())

    if len(dates) < 2:
        return capital_history

    capital = float(STARTING_CAPITAL)
    prev_weights = {}

    for i in range(len(dates) - 1):
        start = dates[i]
        end = dates[i + 1]
        tickers = selections[start]

        new_weights = {t: 1.0 / len(tickers) for t in tickers} if len(tickers) > 0 else {}

        all_tickers = set(prev_weights.keys()) | set(new_weights.keys())
        trade_count = sum(1 for t in all_tickers if abs(new_weights.get(t, 0.0) - prev_weights.get(t, 0.0)) > 1e-12)
        transaction_cost = trade_count * TRANSACTION_COST_PER_TRADE
        capital = max(0.0, capital - transaction_cost)

        if len(tickers) == 0:
            prev_weights = new_weights
            capital_history[end] = capital
            continue

        period = prices.loc[(prices.index >= start) & (prices.index <= end), tickers].copy()
        if period.empty or len(period) < 2:
            prev_weights = new_weights
            capital_history[end] = capital
            continue

        period_returns = period.pct_change().dropna(how="all")
        if period_returns.empty:
            prev_weights = new_weights
            capital_history[end] = capital
            continue

        for current_date, row in period_returns.iterrows():
            active = row.dropna().index.tolist()
            if len(active) > 0:
                weight = 1.0 / len(active)
                day_ret = float((row[active] * weight).sum())
                capital *= (1.0 + day_ret)

        prev_weights = new_weights
        capital_history[end] = capital

    return capital_history


def run_backtest(prices: pd.DataFrame, selections: dict[pd.Timestamp, list[str]], strategy_name: str = "strategy") -> pd.DataFrame:
    dates = sorted(selections.keys())
    if len(dates) < 2:
        print(f"[{strategy_name}] Final capital: ${STARTING_CAPITAL:,.2f}")
        return pd.DataFrame()

    capital = float(STARTING_CAPITAL)
    nav_history = []
    prev_weights = {}

    for i in range(len(dates) - 1):
        start = dates[i]
        end = dates[i + 1]
        tickers = selections[start]

        print(f"[{strategy_name}] Capital before rebalance on {start.date()}: ${capital:,.2f}")

        new_weights = {t: 1.0 / len(tickers) for t in tickers} if len(tickers) > 0 else {}

        all_tickers = set(prev_weights.keys()) | set(new_weights.keys())
        trade_count = sum(1 for t in all_tickers if abs(new_weights.get(t, 0.0) - prev_weights.get(t, 0.0)) > 1e-12)
        transaction_cost = trade_count * TRANSACTION_COST_PER_TRADE
        capital = max(0.0, capital - transaction_cost)

        if len(tickers) == 0:
            prev_weights = new_weights
            continue

        period = prices.loc[(prices.index >= start) & (prices.index <= end), tickers].copy()
        if period.empty or len(period) < 2:
            prev_weights = new_weights
            continue

        period_returns = period.pct_change().dropna(how="all")
        if period_returns.empty:
            prev_weights = new_weights
            continue

        for current_date, row in period_returns.iterrows():
            active = row.dropna().index.tolist()
            if len(active) == 0:
                nav_history.append({"date": current_date, "nav": capital / STARTING_CAPITAL, "capital": capital})
                continue
            weight = 1.0 / len(active)
            day_ret = float((row[active] * weight).sum())
            capital *= (1.0 + day_ret)
            nav_history.append({"date": current_date, "nav": capital / STARTING_CAPITAL, "capital": capital})

        prev_weights = new_weights

    print(f"[{strategy_name}] Final capital: ${capital:,.2f}")

    result = pd.DataFrame(nav_history)
    if result.empty:
        return result
    result = result.drop_duplicates(subset=["date"]).sort_values("date")
    result["ret"] = result["nav"].pct_change()
    return result


def stock_return_between_dates(prices: pd.DataFrame, ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> float:
    if ticker not in prices.columns:
        return np.nan
    series = prices[ticker].dropna()
    if series.empty:
        return np.nan

    start_date = nearest_on_or_before(series.index, pd.Timestamp(start))
    end_date = nearest_on_or_before(series.index, pd.Timestamp(end))
    if start_date is None or end_date is None:
        return np.nan

    start_price = series.loc[start_date]
    end_price = series.loc[end_date]
    return safe_div(end_price - start_price, start_price)


def trailing_return_until_date(prices: pd.DataFrame, ticker: str, end: pd.Timestamp, lookback_days: int) -> float:
    start = pd.Timestamp(end) - pd.Timedelta(days=lookback_days)
    return stock_return_between_dates(prices, ticker, start, end)


def summarize(name: str, result: pd.DataFrame) -> dict:
    daily = result["ret"].dropna()
    if len(daily) == 0:
        return {"strategy": name}

    years = max((result["date"].iloc[-1] - result["date"].iloc[0]).days / 365.25, 1e-9)
    cagr = result["nav"].iloc[-1] ** (1 / years) - 1
    vol = daily.std(ddof=0) * np.sqrt(252)
    sharpe = (daily.mean() / daily.std(ddof=0) * np.sqrt(252)) if daily.std(ddof=0) != 0 else np.nan
    dd = result["nav"] / result["nav"].cummax() - 1
    max_dd = dd.min()

    return {
        "strategy": name,
        "cagr": cagr,
        "vol": vol,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "final_nav": result["nav"].iloc[-1],
    }


def normalize_series(df: pd.DataFrame, value_col: str, out_col: str) -> pd.DataFrame:
    out = df.copy()

    if "date" not in out.columns:
        if "Date" in out.columns:
            out = out.rename(columns={"Date": "date"})
        elif out.index.name in {"date", "Date"}:
            out = out.reset_index().rename(columns={out.index.name: "date"})
        elif isinstance(out.index, pd.DatetimeIndex):
            out = out.reset_index().rename(columns={out.columns[0]: "date"})
        elif "index" in out.columns:
            out = out.rename(columns={"index": "date"})

    out = out[["date", value_col]].copy()
    out = out.dropna()
    out[out_col] = out[value_col] / out[value_col].iloc[0]
    return out[["date", out_col]]


def build_spx_capital_curve(
    spx: pd.DataFrame,
    starting_capital: float,
    start_date: Optional[pd.Timestamp] = None,
    end_date: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    spx_norm = normalize_series(spx.reset_index(), "spx_close", "nav")
    if start_date is not None:
        spx_norm = spx_norm[spx_norm["date"] >= pd.Timestamp(start_date)]
    if end_date is not None:
        spx_norm = spx_norm[spx_norm["date"] <= pd.Timestamp(end_date)]
    if spx_norm.empty:
        return pd.DataFrame(columns=["date", "nav", "capital", "ret"])

    spx_norm = spx_norm.sort_values("date").drop_duplicates(subset=["date"])
    spx_norm["capital"] = spx_norm["nav"] * float(starting_capital)
    spx_norm["ret"] = spx_norm["nav"].pct_change()
    return spx_norm[["date", "nav", "capital", "ret"]]


def plot_curves(curves: dict[str, pd.DataFrame], spx: pd.DataFrame) -> None:
    plt.figure(figsize=(12, 7))
    for name, df in curves.items():
        if df.empty:
            continue
        plt.plot(df["date"], df["nav"], label=name)

    spx_norm = normalize_series(spx.reset_index(), "spx_close", "nav")
    plt.plot(spx_norm["date"], spx_norm["nav"], label="S&P 500", linestyle="--")

    plt.title("Layers of Return Replication (S&P 500, yfinance)")
    plt.xlabel("Date")
    plt.ylabel("Normalized NAV")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.show()


def plot_capital_comparison(multifactor: pd.DataFrame, spx_capital: pd.DataFrame) -> None:
    if multifactor.empty or spx_capital.empty:
        return

    plt.figure(figsize=(12, 7))
    plt.plot(multifactor["date"], multifactor["capital"], label="multifactor")
    plt.plot(spx_capital["date"], spx_capital["capital"], label="S&P 500", linestyle="--")
    plt.title("Capital Curve: Multifactor vs S&P 500")
    plt.xlabel("Date")
    plt.ylabel("Capital ($)")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.show()


def main():
    print(f"Run timestamp: {datetime.now()}")
    payload = download_or_load_data(LOAD_CACHE)
    prices = payload["prices"]
    fundamentals = payload["fundamentals"]
    spx = payload["spx"]

    rebalance_dates = build_rebalance_dates(prices)
    if len(rebalance_dates) < 3:
        print("Not enough rebalance dates.")
        return

    strategy_selections = {
        "single_metric": {},
        "value_composite": {},
        "multifactor": {},
        "sqglp_st": {},
        "core_combination_estimates": {},
        "p123_penman_pope": {},
        "p123_penman_pope_enhanced": {},
        "p123_penman_pope_defensive": {},
        "p123_penman_pope_aggressive": {},
    }

    prev_holdings = {
        "single_metric": set(),
        "value_composite": set(),
        "multifactor": set(),
        "sqglp_st": set(),
        "core_combination_estimates": set(),
        "p123_penman_pope": set(),
        "p123_penman_pope_enhanced": set(),
        "p123_penman_pope_defensive": set(),
        "p123_penman_pope_aggressive": set(),
    }
    multifactor_hold_periods = {}

    snapshots = []
    # Build all selections first (before pre-rebalance logging)
    for i, rebal_date in enumerate(rebalance_dates, start=1):
        snapshot = compute_snapshot(rebal_date, prices, fundamentals)
        if snapshot.empty:
            continue
        rankings = get_strategy_rankings(snapshot)
        for strategy_name, ranked in rankings.items():
            if strategy_name == "multifactor":
                prev_rebal_date = rebalance_dates[i - 2] if i > 1 else None
                selected = apply_multifactor_retention(
                    ranked,
                    prev_holdings[strategy_name],
                    multifactor_hold_periods,
                    prices,
                    prev_rebal_date,
                    rebal_date,
                )
                multifactor_hold_periods = {
                    ticker: multifactor_hold_periods.get(ticker, 0) + 1 for ticker in selected
                }
            elif strategy_name == "core_combination_estimates":
                selected = apply_core_combination_estimate_rules(
                    ranked,
                    prev_holdings[strategy_name],
                )
            else:
                selected = apply_rank_tolerance(ranked, prev_holdings[strategy_name])
            strategy_selections[strategy_name][rebal_date] = selected
            prev_holdings[strategy_name] = set(selected)

        snapshot["rebalance_date"] = rebal_date
        snapshots.append(snapshot)

        if i % 3 == 0:
            print(f"Processed rebalance snapshots: {i}/{len(rebalance_dates)}")

    # Calculate capital history for each strategy
    strategy_capital_history = {}
    for strategy_name, selections in strategy_selections.items():
        strategy_capital_history[strategy_name] = calculate_capital_at_rebalance_dates(prices, selections, rebalance_dates)

    # Now log pre-rebalance returns with correct capital
    pre_rebalance_return_logs = {name: [] for name in strategy_selections.keys()}
    for i, rebal_date in enumerate(rebalance_dates, start=1):
        if i > 1:
            prev_rebal_date = rebalance_dates[i - 2]
            do_print = (i % 3 == 0)
            if do_print:
                print(f"\nReturns before rebalancing on {rebal_date.date()} (since {prev_rebal_date.date()}):")
            for strategy_name in strategy_selections.keys():
                held_tickers = sorted(strategy_selections[strategy_name].get(prev_rebal_date, []))
                # Get capital at the start of this period (end of previous rebalance)
                capital_at_period_start = strategy_capital_history[strategy_name].get(prev_rebal_date, STARTING_CAPITAL)

                if not held_tickers:
                    if do_print:
                        print(f"  {strategy_name}: no existing holdings")
                    pre_rebalance_return_logs[strategy_name].append(
                        {
                            "from_date": prev_rebal_date,
                            "to_date": rebal_date,
                            "ticker": np.nan,
                            "return": np.nan,
                            "entry_type": "no_holdings",
                            "stock_count": 0,
                            "shares_held": np.nan,
                            "value_at_start": np.nan,
                            "value_at_end": np.nan,
                        }
                    )
                    continue

                if do_print:
                    print(f"  {strategy_name}:")
                strategy_returns = []
                position_values = []  # Track (value_start, value_end) for each position
                for ticker in held_tickers:
                    period_return = stock_return_between_dates(prices, ticker, prev_rebal_date, rebal_date)

                    # Get prices at start and end dates
                    price_start = prices.loc[nearest_on_or_before(prices.index, prev_rebal_date), ticker] if ticker in prices.columns else np.nan
                    price_end = prices.loc[nearest_on_or_before(prices.index, rebal_date), ticker] if ticker in prices.columns else np.nan

                    # Calculate position sizing: equal weight allocation from actual capital
                    notional_value_per_position = capital_at_period_start / len(held_tickers)
                    shares_held = safe_div(notional_value_per_position, price_start)
                    value_at_start = notional_value_per_position
                    value_at_end = shares_held * price_end if pd.notna(shares_held) and pd.notna(price_end) else np.nan

                    pre_rebalance_return_logs[strategy_name].append(
                        {
                            "from_date": prev_rebal_date,
                            "to_date": rebal_date,
                            "ticker": ticker,
                            "return": float(period_return) if pd.notna(period_return) else np.nan,
                            "entry_type": "stock",
                            "stock_count": np.nan,
                            "shares_held": float(shares_held) if pd.notna(shares_held) else np.nan,
                            "value_at_start": float(value_at_start),
                            "value_at_end": float(value_at_end) if pd.notna(value_at_end) else np.nan,
                        }
                    )
                    if pd.notna(period_return) and pd.notna(shares_held):
                        strategy_returns.append(float(period_return))
                        position_values.append((value_at_start, value_at_end))
                        if do_print:
                            print(f"    {ticker}: {period_return:.2%} | {shares_held:.1f} shares | ${value_at_start:,.2f} -> ${float(value_at_end):,.2f}", flush=True)
                    else:
                        if do_print:
                            print(f"    {ticker}: n/a")

                if strategy_returns:
                    overall_return = float(np.mean(strategy_returns))
                    total_value_start = sum([v[0] for v in position_values if pd.notna(v[0])])
                    total_value_end = sum([v[1] for v in position_values if pd.notna(v[1])])
                    if do_print:
                        print(f"    overall ({len(strategy_returns)} stocks): {overall_return:.2%} | ${total_value_start:,.2f} -> ${total_value_end:,.2f}", flush=True)
                    pre_rebalance_return_logs[strategy_name].append(
                        {
                            "from_date": prev_rebal_date,
                            "to_date": rebal_date,
                            "ticker": "__overall__",
                            "return": overall_return,
                            "entry_type": "overall",
                            "stock_count": len(strategy_returns),
                            "shares_held": np.nan,
                            "value_at_start": float(total_value_start),
                            "value_at_end": float(total_value_end),
                        }
                    )
                else:
                    if do_print:
                        print("    overall: n/a")
                    pre_rebalance_return_logs[strategy_name].append(
                        {
                            "from_date": prev_rebal_date,
                            "to_date": rebal_date,
                            "ticker": "__overall__",
                            "return": np.nan,
                            "entry_type": "overall",
                            "stock_count": 0,
                            "shares_held": np.nan,
                            "value_at_start": np.nan,
                            "value_at_end": np.nan,
                        }
                    )

    curves = {}
    summary_rows = []

    for strategy_name, selections in strategy_selections.items():
        result = run_backtest(prices, selections, strategy_name=strategy_name)
        if result.empty:
            print(f"No result for {strategy_name}")
            continue
        curves[strategy_name] = result
        metrics = summarize(strategy_name, result)
        summary_rows.append(metrics)
        result.to_csv(f"backtest_{strategy_name}.csv", index=False)

    if summary_rows:
        summary_df = pd.DataFrame(summary_rows)
        print("\nPerformance summary")
        print(summary_df)
        summary_df.to_csv("performance_summary.csv", index=False)

    for strategy_name, log_rows in pre_rebalance_return_logs.items():
        log_df = pd.DataFrame(log_rows)
        log_df.to_csv(f"pre_rebalance_returns_{strategy_name}.csv", index=False)

    if snapshots:
        snapshot_df = pd.concat(snapshots, ignore_index=True)
        snapshot_df.to_csv("factor_snapshots.csv", index=False)

        p123_columns = [
            "ticker",
            "date",
            "price",
            "marketcap",
            "shares_fd",
            "sales",
            "ast_tot",
            "get_dep_and_amort",
            "net_inc_cf_stmt",
            "altman_x1",
            "altman_x2",
            "altman_x3",
            "altman_x4",
            "altman_x5",
            "altman_x4_rev",
            "altman_z_orig",
            "beneish_m_score",
            "mscore_aqi",
            "mscore_depami",
            "mscore_depi",
            "mscore_dsri",
            "mscore_gmi",
            "mscore_lvgi",
            "mscore_sgai",
            "mscore_sgi",
            "mscore_tata",
            "roe_pct_ttm",
            "roi_pct_ttm",
            "roa_pct_ttm",
            "gmgn_pct_ttm",
            "piot_f_score",
            "ev2ebitda_ttm",
            "ev2sales_ttm",
            "pr13w_pct_chg",
            "pr26w_pct_chg",
            "pr52w_pct_chg",
            "cur_fy_up_rev_4wk_ago",
            "si_pct_float",
            "ins_shr_purch",
        ]
        available_p123_columns = [col for col in p123_columns if col in snapshot_df.columns]
        p123_df = snapshot_df[available_p123_columns].copy()
        p123_df.to_csv("p123_factor_snapshots.csv", index=False)
        print(f"Saved P123-mapped factor dataframe with {len(p123_df):,} rows to p123_factor_snapshots.csv")

    if curves:
        plot_curves(curves, spx)

    multifactor_curve = curves.get("multifactor", pd.DataFrame())
    if not multifactor_curve.empty:
        start_date = multifactor_curve["date"].min()
        end_date = multifactor_curve["date"].max()
        final_multifactor_capital = float(multifactor_curve["capital"].iloc[-1])
        multifactor_total_return = safe_div(final_multifactor_capital - STARTING_CAPITAL, STARTING_CAPITAL)
        print(
                f"[Multifactor Strategy] Final capital (from ${STARTING_CAPITAL:,.2f}): "
                f"${final_multifactor_capital:,.2f} ({multifactor_total_return:.2%})"
            )
        spx_capital_curve = build_spx_capital_curve(
            spx,
            starting_capital=STARTING_CAPITAL,
            start_date=start_date,
            end_date=end_date,
        )
        if not spx_capital_curve.empty:
            final_spx_capital = float(spx_capital_curve["capital"].iloc[-1])
            spx_total_return = safe_div(final_spx_capital - STARTING_CAPITAL, STARTING_CAPITAL)
            print(
                f"[S&P 500] Final capital (from ${STARTING_CAPITAL:,.2f}): "
                f"${final_spx_capital:,.2f} ({spx_total_return:.2%})"
            )
        else:
            print("[S&P 500] Capital benchmark unavailable for the multifactor date range.")

        plot_capital_comparison(multifactor_curve, spx_capital_curve)


if __name__ == "__main__":
    main()
