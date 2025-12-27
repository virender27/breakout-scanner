# ================= IMPORTS =================
import yfinance as yf
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import pytz

# ================= TELEGRAM CONFIG =================
BOT_TOKEN = "8270987808:AAHFrPtvl9vxSazNyVkdeKijHNTLniAfMXo"
CHAT_ID = "8337253908"

# ================= CONFIG =================
LOOKBACK = 20
VOL_MULT = 1.05         # relaxed to catch more stocks
NEAR_BREAKOUT_THRESHOLD = 0.95
MAX_EXTENSION = 0.05
ATR_MULT = 1.2
RR = 2
RISK_PER_TRADE = 1000
MIN_PRICE = 20
MIN_AVG_VOL = 100000

IST = pytz.timezone("Asia/Kolkata")

# ================= FUNCTIONS =================
def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, data=payload, timeout=5)
    except:
        print("Telegram send failed:", message)

def ema(s, p): 
    return s.ewm(span=p, adjust=False).mean()

def atr(df, p=14):
    tr = pd.concat([
        df["High"]-df["Low"], 
        abs(df["High"]-df["Close"].shift()), 
        abs(df["Low"]-df["Close"].shift())
    ], axis=1).max(axis=1)
    return tr.rolling(p).mean()

# ================= FETCH NSE SYMBOLS =================
url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
df = pd.read_csv(url)
SYMBOLS = [s + ".NS" for s in df["Symbol"].tolist()]

# ================= SCAN FUNCTION =================
def scan_market():
    results = []
    for sym in SYMBOLS[:50]:  # limit 50 for faster demo
        try:
            df = yf.download(sym, period="4mo", progress=False)
            if len(df) < LOOKBACK: continue

            df["EMA20"] = ema(df["Close"], 20)
            df["EMA50"] = ema(df["Close"], 50)
            df["ATR"] = atr(df)

            today = df.iloc[-1]
            resistance_d = df.iloc[-LOOKBACK-1:-1]["High"].max()
            avg_vol = df.iloc[-LOOKBACK-1:-1]["Volume"].mean()

            if (today["Close"] > resistance_d and 
                today["Close"] > today["EMA20"] > today["EMA50"] and
                today["Volume"] >= avg_vol*VOL_MULT and
                (today["Close"]-resistance_d)/resistance_d <= MAX_EXTENSION and
                today["Close"] > MIN_PRICE and avg_vol > MIN_AVG_VOL):

                buy = round(today["Close"]*1.002,2)
                sl = round(buy - today["ATR"]*ATR_MULT,2)
                risk = buy - sl
                target = round(buy + risk*RR,2)

                results.append({
                    "Stock": sym.replace(".NS",""),
                    "CMP": round(today["Close"],2),
                    "Daily_Res": round(resistance_d,2),
                    "Buy": buy,
                    "SL": sl,
                    "Target": target
                })
        except:
            continue

    # SEND TELEGRAM
    if results:
        msg = "📊 NSE Breakout Scan:\n"
        for r in results:
            msg += (f"{r['Stock']} | CMP: {r['CMP']} | Buy: {r['Buy']} | "
                    f"SL: {r['SL']} | Target: {r['Target']}\n")
        send_telegram(msg)
    else:
        send_telegram("⚠️ No breakout stocks found today.")

# ================= MAIN =================
def main():
    scan_market()

if __name__ == "__main__":
    main()
