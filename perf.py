import yfinance as yf
import datetime
import pandas as pd
import pdb
import warnings
warnings.filterwarnings("ignore")

# ---- User Inputs ----
df = pd.read_csv('stocks.csv')  # Assuming a CSV file with a column 'Ticker' for stock symbols
tickers = list(set(df['Company'].to_list()))
        # Stock symbol
monthly_investment = 25 # Amount invested each month
year = 2020              # Year for YTD tracking

# ---- Dates ----
today = datetime.datetime.today().date()
start_of_year = datetime.date(year, 1, 1)
total_current_value = 0
total_invested_value = 0
gain_or_loss = 0
total_return_pct = 0
for ticker in tickers:
    # ---- Fetch monthly data ----
    data = yf.download(ticker, start=start_of_year, end=today, interval="1mo")

    if data.empty or len(data) == 0:
        print("No data available for this period.")
    else:
        data['Close'] = data['Close'].ffill()  # Fill missing values

        # Track investments
        total_invested = 0
        total_shares = 0

        for idx, row in data.iterrows():
            price = row['Close'].values[0] if isinstance(row['Close'], pd.Series) else row['Close']
            total_invested += monthly_investment
            shares_bought = monthly_investment / price
            total_shares += shares_bought

        # Latest price
        latest_price = data['Close'].iloc[-1].values[0] if isinstance(data['Close'].iloc[-1], pd.Series) else data['Close'].iloc[-1]
        current_value = total_shares * latest_price
        gain = current_value - total_invested
        return_pct = (gain / total_invested) * 100
        total_current_value += current_value
        total_invested_value += total_invested
        gain_or_loss += gain

        #pdb.set_trace()
        # ---- Output ----
        print(f"--- {ticker} Monthly Investment Performance (from {year} to {today.year}) ---")
        print(f"Monthly Investment: ${monthly_investment}")
        print(f"Total Invested: ${total_invested:.2f}")
        print(f"Total Shares Accumulated: {total_shares:.4f}")
        print(f"Current Value: ${current_value:.2f}")
        print(f"Gain/Loss: ${gain:.2f} ({return_pct:.2f}%)")

total_return_pct = (gain_or_loss / total_invested_value) * 100 if total_invested_value != 0 else 0
print(f"\n--- Overall Portfolio Value as of {today} ---")
print(f"Total Invested Value: ${total_invested_value:.2f}")
print(f"Total Current Value: ${total_current_value:.2f}")
print(f"Total Gain/Loss: ${gain_or_loss:.2f}")
print(f"Total Return (%): {total_return_pct:.2f}%")
print("Total number of stocks analyzed:", len(tickers))