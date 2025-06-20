from flask import Flask, request, jsonify, render_template
import yfinance as yf
import sqlite3
import os

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

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
