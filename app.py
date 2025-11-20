from flask import Flask, request, jsonify, render_template
import yfinance as yf
import sqlite3
import os
import pandas as pd

app = Flask(__name__)
DB_FILE = "tickers.db"

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS tickers (symbol TEXT PRIMARY KEY)")
        conn.commit()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/get_saved_tickers", methods=["GET"])
def get_saved_tickers():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("SELECT symbol FROM tickers")
        rows = c.fetchall()
        return jsonify([row[0] for row in rows])

@app.route("/save_ticker", methods=["POST"])
def save_ticker():
    symbol = request.json.get("symbol")
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        try:
            c.execute("INSERT INTO tickers (symbol) VALUES (?)", (symbol.upper(),))
            conn.commit()
        except sqlite3.IntegrityError:
            pass  # Already exists
    return jsonify(success=True)

@app.route("/remove_ticker", methods=["POST"])
def remove_ticker():
    symbol = request.json.get("symbol")
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM tickers WHERE symbol = ?", (symbol.upper(),))
        conn.commit()
    return jsonify(success=True)

@app.route("/get_stock_data", methods=["POST"])
def get_stock_data():
    data = request.get_json()
    symbols = data.get("symbols", [])
    period = data.get("period", "1d")

    result = {}
    for symbol in symbols:
        try:
            stock = yf.Ticker(symbol)
            hist = stock.history(period=period)
            if len(hist) >= 2:
                start = hist["Close"].iloc[0]
                end = hist["Close"].iloc[-1]
                percent_change = ((end - start) / start) * 100
                result[symbol] = round(percent_change, 2)
            else:
                result[symbol] = None
        except Exception:
            result[symbol] = None

    return jsonify(result)

@app.route("/get_analysis_data", methods=["POST"])
@app.route("/get_analysis_data", methods=["POST"])
def get_analysis_data():
    data = request.get_json()
    symbols = data.get("symbols", [])

    price_target_data = {}
    revenue_growth_data = {}
    sectors = {}   # ← NEW: store sector for each ticker

    for symbol in symbols:
        try:
            stock = yf.Ticker(symbol)
            info = stock.info

            # Save the sector info
            sector = info.get("sector", "Other")
            sectors[symbol] = sector

            # Price target upside
            target_price = stock.analyst_price_targets['mean']
            current_price = stock.analyst_price_targets['current']

            upside = ((target_price - current_price) / current_price) * 100
            price_target_data[symbol] = round(upside, 2)

            # Revenue estimates
            df_rev = stock.revenue_estimate
            current_year = df_rev.loc["0y", "avg"]
            next_year = df_rev.loc["+1y", "avg"]

            if current_year and next_year:
                revenue_growth = ((next_year - current_year) / current_year) * 100
            else:
                revenue_growth = None

            # EPS estimates
            df_eps = stock.earnings_estimate
            current_eps = df_eps.loc["0y", "avg"]
            next_eps = df_eps.loc["+1y", "avg"]

            if current_eps and next_eps:
                eps_growth = ((next_eps - current_eps) / current_eps) * 100
                eps_growth = round(eps_growth, 2)
            else:
                eps_growth = None

            if revenue_growth is not None and eps_growth is not None:
                revenue_growth_data[symbol] = round(revenue_growth, 2) + eps_growth
            else:
                revenue_growth_data[symbol] = None

        except Exception as e:
            print(f"Error fetching analysis data for {symbol}: {e}")
            price_target_data[symbol] = None
            revenue_growth_data[symbol] = None
            sectors[symbol] = "Other"

    return jsonify({
        "price_target_upside": price_target_data,
        "revenue_growth_next_year": revenue_growth_data,
        "sectors": sectors   # ← NEW FIELD
    })

@app.route("/get_summary", methods=["POST"])
def get_summary():
    symbol = request.json.get("symbol", "")
    try:
        stock = yf.Ticker(symbol)
        info = stock.info

        summary_full = info.get("longBusinessSummary", "")
        summary_sentences = ". ".join(summary_full.split(". ")[:2]) + "." if summary_full else "No summary available."
        recommendation = info.get("recommendationKey", "N/A").capitalize()

        financials = stock.financials.T
        dividends = stock.dividends

        # Revenue
        revenue = financials.get("Total Revenue", pd.Series()).dropna().tail(5)

        # EPS (Diluted)
        eps = financials.get("Diluted EPS", pd.Series()).dropna().tail(5)

        # Dividends per year
        dividends_yearly = dividends.resample('YE').sum().tail(5) if not dividends.empty else pd.Series()

        # Gross Margin
        gross_profit = financials.get("Gross Profit", pd.Series()).dropna().tail(5)
        gross_margin = ((gross_profit / revenue) * 100).dropna() if not revenue.empty else pd.Series()

        def safe_dict(series):
            return {str(k): float(v) for k, v in series.items() if pd.notnull(v)}

        result = {
            "name": info.get("longName", symbol),
            "industry": info.get("industry", "Unknown"),
            "summary": summary_sentences,
            "recommendation": recommendation,
            "revenue": safe_dict(revenue),
            "eps": safe_dict(eps),
            "dividends": safe_dict(dividends_yearly),
            "gross_margin": safe_dict(gross_margin)
        }

        return jsonify(result)

    except Exception as e:
        print("Error fetching summary:", e)
        return jsonify({"error": "Could not fetch summary."}), 500

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
