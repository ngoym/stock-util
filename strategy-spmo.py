"""Monthly SPMO-style backtest with holdings carryover and fresh data per rebalance."""

from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf
import warnings

warnings.filterwarnings("ignore")

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

LOOKBACK_DAYS = 252          # ~12 months
SKIP_RECENT_DAYS = 10        # skip most recent month
VOL_LOOKBACK = 252
TOP_N = 20
WEIGHTING_METHOD = "momentum"  # "momentum" or "equal"
INITIAL_CAPITAL = 1000.0
BACKTEST_START = "2016-01-01"
BACKTEST_END = datetime.today().strftime("%Y-%m-%d")
COMPONENTS_FILE = "S&P 500 Historical Components & Changes.csv"
UNIVERSE_FROM_YEAR = 2018

def normalize_component_ticker(raw_ticker: str) -> str:
    token = str(raw_ticker).strip()
    if not token:
        return ""

    # Strip historical metadata suffixes like -200811.
    base = token.split("-")[0]
    # yfinance uses '-' instead of '.' for many symbols (e.g., BRK.B -> BRK-B).
    return base.replace(".", "-").strip()


def get_universe_from_components_since(
    csv_path: str = COMPONENTS_FILE,
    from_year: int = UNIVERSE_FROM_YEAR,
) -> list[str]:
    """Union all S&P 500 component symbols from `from_year` onward."""
    df = pd.read_csv(csv_path, usecols=["date", "tickers"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df[df["date"] >= pd.Timestamp(f"{from_year}-01-01")]

    universe: set[str] = set()
    for row in df["tickers"].dropna():
        for token in str(row).split(","):
            ticker = normalize_component_ticker(token)
            if ticker:
                universe.add(ticker)

    return sorted(universe)

def extract_close_prices(raw_prices: pd.DataFrame, fallback_name: str = "ticker") -> pd.DataFrame:
    """Normalize yfinance output into a close-price DataFrame."""
    if raw_prices.empty:
        return pd.DataFrame()

    if isinstance(raw_prices.columns, pd.MultiIndex):
        level0 = raw_prices.columns.get_level_values(0)
        level1 = raw_prices.columns.get_level_values(1)

        if "Close" in level0:
            close_df = raw_prices.xs("Close", axis=1, level=0)
        elif "Close" in level1:
            close_df = raw_prices.xs("Close", axis=1, level=1)
        else:
            raise ValueError("Downloaded data does not contain a Close price level")
    else:
        if "Close" in raw_prices.columns:
            close_df = raw_prices[["Close"]].rename(columns={"Close": fallback_name})
        else:
            close_df = raw_prices.copy()

    if isinstance(close_df, pd.Series):
        series_name = close_df.name if close_df.name else fallback_name
        close_df = close_df.to_frame(name=series_name)

    return close_df.dropna(axis=1, how="all")


def compute_momentum_score(price_df: pd.DataFrame) -> pd.DataFrame:
    """12m-minus-1m return divided by annualized volatility."""
    momentum_return = (
        price_df.shift(SKIP_RECENT_DAYS) /
        price_df.shift(LOOKBACK_DAYS)
    ) - 1

    daily_returns = price_df.pct_change()
    volatility = daily_returns.rolling(VOL_LOOKBACK).std() * np.sqrt(252)
    return momentum_return / volatility


def get_last_price(close_df: pd.DataFrame, ticker: str) -> float:
    if ticker not in close_df.columns:
        return None

    series = close_df[ticker].dropna()
    if series.empty:
        return None

    price = float(series.iloc[-1])
    return price if np.isfinite(price) and price > 0 else None


def build_target_weights(
    score_row: pd.Series,
    close_df: pd.DataFrame,
    top_n: int,
    weighting_method: str,
) -> pd.Series:
    """Build weights for exactly top_n tradable names when available."""
    ranked = score_row.dropna().sort_values(ascending=False)

    selected: list[str] = []
    for ticker in ranked.index:
        if get_last_price(close_df, ticker) is None:
            continue
        selected.append(ticker)
        if len(selected) == top_n:
            break

    if not selected:
        return pd.Series(dtype=float)

    method = weighting_method.lower()
    if method == "equal":
        return pd.Series(1.0 / len(selected), index=selected)

    if method != "momentum":
        raise ValueError("WEIGHTING_METHOD must be either 'momentum' or 'equal'")

    selected_scores = ranked.loc[selected]
    positive = selected_scores.clip(lower=0)
    total = float(positive.sum())

    if total > 0:
        return positive / total

    # If all selected scores are non-positive, keep allocation invested equally.
    return pd.Series(1.0 / len(selected), index=selected)


def run_backtest(
    price_data: pd.DataFrame,
    start_date: str,
    end_date: str,
    initial_capital: float,
    top_n: int,
    weighting_method: str,
) -> tuple[pd.DataFrame, dict[str, float], float]:
    """Rebalance monthly to a tradable top-N target with fractional shares."""
    rebalance_dates = pd.date_range(start=start_date, end=end_date, freq="BME")
    holdings: dict[str, float] = {}
    cash = float(initial_capital)
    history: list[dict[str, object]] = []

    if price_data.empty:
        return pd.DataFrame(history), holdings, cash

    for reb_date in rebalance_dates:
        # Use cached price history and only index up to current rebalance date.
        close_window = price_data.loc[:reb_date]

        if close_window.empty or len(close_window.index) < LOOKBACK_DAYS + SKIP_RECENT_DAYS + 1:
            continue

        scores = compute_momentum_score(close_window)
        latest_scores = scores.iloc[-1]
        target_weights = build_target_weights(latest_scores, close_window, top_n, weighting_method)
        if target_weights.empty:
            continue

        target_set = set(target_weights.index)
        current_set = set(holdings.keys())

        exiting = sorted(current_set - target_set)
        entering = sorted(target_set - current_set)
        staying = sorted(current_set & target_set)

        # Sell names that exited top N.
        for ticker in exiting:
            px = get_last_price(close_window, ticker)
            if px is None:
                continue
            cash += holdings[ticker] * px
            del holdings[ticker]

        # Re-target all kept/new names so total holdings equals target_set.
        equity_before = cash
        for ticker, shares in holdings.items():
            px = get_last_price(close_window, ticker)
            if px is None:
                continue
            equity_before += shares * px

        new_holdings: dict[str, float] = {}
        allocated_value = 0.0
        for ticker, weight in target_weights.items():
            px = get_last_price(close_window, ticker)
            if px is None:
                continue
            target_value = equity_before * float(weight)
            shares = target_value / px
            new_holdings[ticker] = shares
            allocated_value += shares * px

        holdings = new_holdings
        cash = max(0.0, equity_before - allocated_value)

        portfolio_value = cash
        for ticker, shares in holdings.items():
            px = get_last_price(close_window, ticker)
            if px is None:
                continue
            portfolio_value += shares * px

        target_count = min(top_n, len(target_weights))
        print("[INFO] - Portfolio on {}: ${:,.2f} (Cash: ${:,.2f}, Positions: {})".format(
            reb_date.strftime("%Y-%m-%d"),
            portfolio_value,
            cash,
            len(holdings),
        ))
        print("[INFO] - Holdings: {}\n".format(", ".join(sorted(holdings.keys()))))
        history.append(
            {
                "date": close_window.index[-1],
                "portfolio_value": portfolio_value,
                "holdings": ", ".join(sorted(holdings.keys())),
                "cash": cash,
                "positions": len(holdings),
                "target_positions": target_count,
                "entered": len(entering),
                "exited": len(exiting),
                "stayed": len(staying),
            }
        )

    return pd.DataFrame(history), holdings, cash


if __name__ == "__main__":
    pd.set_option("display.float_format", "{:.4f}".format)

    universe = get_universe_from_components_since(
        csv_path=COMPONENTS_FILE,
        from_year=UNIVERSE_FROM_YEAR,
    )
    if not universe:
        raise ValueError("Universe is empty; check the components CSV and year filter")

    # Single yfinance call for the full backtest interval.
    yf_end = (pd.Timestamp(BACKTEST_END) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    raw_prices = yf.download(
        universe,
        start=BACKTEST_START,
        end=yf_end,
        auto_adjust=True,
        progress=False,
    )
    close_prices = extract_close_prices(raw_prices)

    equity, final_holdings, final_cash = run_backtest(
        price_data=close_prices,
        start_date=BACKTEST_START,
        end_date=BACKTEST_END,
        initial_capital=INITIAL_CAPITAL,
        top_n=TOP_N,
        weighting_method=WEIGHTING_METHOD,
    )

    if equity.empty:
        print("No backtest output. Try extending history or reducing lookback requirements.")
    else:
        equity = equity.sort_values("date").reset_index(drop=True)
        equity["monthly_return"] = equity["portfolio_value"].pct_change()
        equity["year"] = equity["date"].dt.year

        monthly_returns = equity[["date", "monthly_return", "holdings"]].copy()
        yearly_returns = (
            equity
            .dropna(subset=["monthly_return"])
            .groupby("year")["monthly_return"]
            .apply(lambda x: (1 + x).prod() - 1)
            .reset_index(name="yearly_return")
        )
        yearly_values = (
            equity
            .groupby("year")["portfolio_value"]
            .agg(year_start_value="first", year_end_value="last")
            .reset_index()
        )
        yearly_returns = yearly_returns.merge(yearly_values, on="year", how="left")

        start_val = float(equity.iloc[0]["portfolio_value"])
        end_val = float(equity.iloc[-1]["portfolio_value"])
        periods = len(equity)
        years = periods / 12
        cagr = (end_val / start_val) ** (1 / years) - 1 if years > 0 else np.nan

        print("\nBacktest Summary")
        print("Start Value:", f"{start_val:,.2f}")
        print("End Value:", f"{end_val:,.2f}")
        print("CAGR:", f"{cagr:.2%}" if np.isfinite(cagr) else "n/a")
        print("Months:", periods)
        print("Final Cash:", f"{final_cash:,.2f}")
        print("Weighting Method:", WEIGHTING_METHOD)

        print("\nMonthly Returns (Last 12 Months)")
        monthly_last_year = monthly_returns.dropna(subset=["monthly_return"]).tail(12).copy()
        monthly_last_year["monthly_return"] = monthly_last_year["monthly_return"].map(lambda x: f"{x:.2%}")
        print(monthly_last_year[["date", "monthly_return", "holdings"]])

        print("\nEquity Tail")
        print(equity.tail(12))

        print("\nReturns Per Year")
        if yearly_returns.empty:
            print("No yearly returns available yet.")
        else:
            yearly_returns["yearly_return"] = yearly_returns["yearly_return"].map(lambda x: f"{x:.2%}")
            yearly_returns["year_start_value"] = yearly_returns["year_start_value"].map(lambda x: f"{x:,.2f}")
            yearly_returns["year_end_value"] = yearly_returns["year_end_value"].map(lambda x: f"{x:,.2f}")
            print(yearly_returns)

        if final_holdings:
            rows = []
            for ticker, shares in final_holdings.items():
                rows.append({"ticker": ticker, "shares": shares})

            final_positions = pd.DataFrame(rows).sort_values("shares", ascending=False)
            print("\nFinal Holdings (shares)")
            print(final_positions.head(20))