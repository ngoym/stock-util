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

@app.route("/get_summary", methods=["POST"])
def get_summary():
    symbol = request.json.get("symbol", "")
    try:
        stock = yf.Ticker(symbol)
        info = stock.info

        summary_full = info.get("longBusinessSummary", "")
        summary_sentences = ". ".join(summary_full.split(". ")[:2]) + "." if summary_full else "No summary available."
        recommendation = info.get("recommendationKey", "N/A").capitalize()
        #analyst_count = info.get("analystCount", 0)
        #recommendation_pct = info.get("recommendation_pct", 0)

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
            #"recommendation_pct": recommendation_pct,
            #"analyst_count": analyst_count,
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
