# ================= IMPORTS =================
import pandas as pd
import yfinance as yf
import numpy as np
import requests
import smtplib
from email.message import EmailMessage
import warnings
import os
from nsetools import Nse

warnings.filterwarnings("ignore")

# ================= CONFIG =================
TELEGRAM_BOT_TOKEN = "8270987808:AAHFrPtvl9vxSazNyVkdeKijHNTLniAfMXo"
TELEGRAM_CHAT_ID = "8337253908"

LOOKBACK_DAYS = 20
WEEK_LOOKBACK = 25
VOL_MULT = 1.05
NEAR_BREAKOUT_THRESHOLD = 0.95
MAX_EXTENSION = 0.05
ATR_MULT = 1.2
RR = 2
RISK_PER_TRADE = 1000
MIN_PRICE = 20
MIN_AVG_VOL = 100000
OFFLINE_CSV = "nse_historical_data.csv"

# ================= EMAIL CONFIG (GitHub Secrets) =================
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
EMAIL_TO = EMAIL_ADDRESS

# ================= UTILS =================
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=5
        )
    except:
        print("⚠️ Telegram failed")

def send_email(file_path):
    if not EMAIL_ADDRESS or not EMAIL_APP_PASSWORD:
        print("⚠️ Email secrets missing – skipping email")
        return

    msg = EmailMessage()
    msg["Subject"] = "Daily NSE Breakout Scan"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_TO
    msg.set_content("Attached is today's NSE Breakout Scan.")

    with open(file_path, "rb") as f:
        msg.add_attachment(
            f.read(),
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=file_path
        )

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        print("📧 Email sent successfully")
    except Exception as e:
        print("⚠️ Email error:", e)

# ================= INDICATORS =================
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    rs = gain.rolling(period).mean() / loss.rolling(period).mean()
    return 100 - (100 / (1 + rs))

def atr(df, period=14):
    tr = pd.concat([
        df["High"] - df["Low"],
        abs(df["High"] - df["Close"].shift()),
        abs(df["Low"] - df["Close"].shift())
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

# ================= NSE SYMBOLS =================
nse = Nse()
codes = nse.get_stock_codes()
SYMBOLS = [s + ".NS" for s in codes if s != "SYMBOL"]

print(f"✅ NSE symbols loaded: {len(SYMBOLS)}")

# ================= FETCH DATA =================
def fetch_data(symbol):
    try:
        df = yf.download(symbol, period="4mo", progress=False)
        if len(df) < 60:
            return None
        return df
    except:
        return None

# ================= SCANNER =================
def scan_stock(symbol):
    df = fetch_data(symbol)
    if df is None:
        return None

    df["EMA20"] = ema(df["Close"], 20)
    df["EMA50"] = ema(df["Close"], 50)
    df["RSI"] = rsi(df["Close"])
    df["ATR"] = atr(df)

    today = df.iloc[-1]
    yesterday = df.iloc[-2]

    close = float(today["Close"])
    ema20 = float(today["EMA20"])
    ema50 = float(today["EMA50"])
    rsi_today = float(today["RSI"])
    rsi_yesterday = float(yesterday["RSI"])
    atr_val = float(today["ATR"])
    vol = float(today["Volume"])

    res_d = float(df.iloc[-LOOKBACK_DAYS-1:-1]["High"].max())
    res_w = float(df.iloc[-WEEK_LOOKBACK-1:-1]["High"].max())
    avg_vol = float(df.iloc[-LOOKBACK_DAYS-1:-1]["Volume"].mean())

    results = []

    # ===== Confirmed Breakout =====
    if (
        close > res_d
        and close > res_w
        and close > ema20 > ema50
        and rsi_today > 45
        and rsi_today > rsi_yesterday
        and vol >= avg_vol * VOL_MULT
        and close > MIN_PRICE
        and avg_vol > MIN_AVG_VOL
    ):
        buy = round(today["High"] * 1.002, 2)
        sl = round(buy - atr_val * ATR_MULT, 2)
        risk = buy - sl
        if risk <= 0:
            return None
        target = round(buy + risk * RR, 2)
        qty = int(RISK_PER_TRADE / risk)

        results.append({
            "Stock": symbol.replace(".NS", ""),
            "Type": "Confirmed Breakout",
            "CMP": round(close, 2),
            "Buy": buy,
            "SL": sl,
            "Target": target,
            "Qty": qty,
            "RSI": round(rsi_today, 1),
            "Vol_X": round(vol / avg_vol, 2),
        })

    return results if results else None

# ================= RUN =================
final = []

for sym in SYMBOLS[:500]:
    r = scan_stock(sym)
    if r:
        final.extend(r)

if final:
    df = pd.DataFrame(final).sort_values("Vol_X", ascending=False)
    file = "breakout_scan.xlsx"
    df.to_excel(file, index=False)

    print(f"✅ Scan completed: {len(df)} stocks")

    msg = "📊 NSE Breakout Scan:\n"
    for _, row in df.iterrows():
        msg += f"{row['Stock']} | Buy {row['Buy']} | SL {row['SL']} | Target {row['Target']}\n"

    send_telegram(msg)
    send_email(file)
else:
    print("⚠️ No breakout found today")
