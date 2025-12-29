# ================= IMPORTS =================
import pandas as pd
import yfinance as yf
import numpy as np
import requests
import smtplib
from email.message import EmailMessage
import warnings
from nsetools import Nse
import os

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

# ================= EMAIL CONFIG =================
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
EMAIL_TO = EMAIL_ADDRESS

# ================= SAFE VALUE HELPER =================
def safe(v):
    if isinstance(v, pd.Series):
        return float(v.iloc[-1])
    return float(v)

# ================= UTILS =================
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
    except:
        print("⚠️ Telegram failed")

def send_email(file_path):
    if not EMAIL_ADDRESS or not EMAIL_APP_PASSWORD:
        print("⚠️ Email secrets missing")
        return

    msg = EmailMessage()
    msg["Subject"] = "Daily NSE Breakout Scan"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_TO
    msg.set_content("Attached: NSE Breakout Scan")

    with open(file_path, "rb") as f:
        msg.add_attachment(
            f.read(),
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=file_path,
        )

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        print("📧 Email sent")
    except Exception as e:
        print("⚠️ Email failed:", e)

# ================= INDICATORS =================
def ema(series, n):
    return series.ewm(span=n, adjust=False).mean()

def rsi(series, n=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = gain.rolling(n).mean() / loss.rolling(n).mean()
    return 100 - (100 / (1 + rs))

def atr(df, n=14):
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift()).abs(),
        (df["Low"] - df["Close"].shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()

# ================= NSE SYMBOLS =================
nse = Nse()
codes = nse.get_stock_codes()
SYMBOLS = [s + ".NS" for s in codes if s != "SYMBOL"]
print(f"✅ NSE symbols fetched: {len(SYMBOLS)}")

# ================= FETCH DATA =================
def fetch(symbol):
    try:
        df = yf.download(symbol, period="4mo", progress=False)
        if df is None or len(df) < 60:
            return None
        return df
    except:
        return None

# ================= SCAN =================
def scan_stock(symbol):
    df = fetch(symbol)
    if df is None:
        return None

    df["EMA20"] = ema(df["Close"], 20)
    df["EMA50"] = ema(df["Close"], 50)
    df["RSI"] = rsi(df["Close"])
    df["ATR"] = atr(df)

    today = df.iloc[-1]
    yesterday = df.iloc[-2]

    close = safe(today["Close"])
    ema20 = safe(today["EMA20"])
    ema50 = safe(today["EMA50"])
    rsi_t = safe(today["RSI"])
    rsi_y = safe(yesterday["RSI"])
    atr_v = safe(today["ATR"])
    vol = safe(today["Volume"])

    res_d = safe(df.iloc[-LOOKBACK_DAYS-1:-1]["High"].max())
    res_w = safe(df.iloc[-WEEK_LOOKBACK-1:-1]["High"].max())
    avg_vol = safe(df.iloc[-LOOKBACK_DAYS-1:-1]["Volume"].mean())

    if close < MIN_PRICE or avg_vol < MIN_AVG_VOL:
        return None

    # CONFIRMED
    if (
        close > res_d and
        close > res_w and
        close > ema20 > ema50 and
        rsi_t > 45 and rsi_t > rsi_y and
        vol >= avg_vol * VOL_MULT and
        (close - res_d) / res_d <= MAX_EXTENSION
    ):
        buy = round(safe(today["High"]) * 1.002, 2)
        sl = round(buy - atr_v * ATR_MULT, 2)
        risk = buy - sl
        if risk <= 0:
            return None

        return [{
            "Stock": symbol.replace(".NS", ""),
            "Type": "Confirmed Breakout",
            "CMP": round(close, 2),
            "Buy": buy,
            "SL": sl,
            "Target": round(buy + risk * RR, 2),
            "Qty": int(RISK_PER_TRADE / risk),
            "RSI": round(rsi_t, 1),
            "Vol_X": round(vol / avg_vol, 2),
        }]

    # NEAR
    if (
        close >= res_d * NEAR_BREAKOUT_THRESHOLD and
        close < res_d and
        close > ema20 > ema50 and
        rsi_t > 40 and
        vol >= avg_vol * 0.8
    ):
        buy = round(res_d * 1.002, 2)
        sl = round(buy - atr_v * ATR_MULT, 2)
        risk = buy - sl
        if risk <= 0:
            return None

        return [{
            "Stock": symbol.replace(".NS", ""),
            "Type": "Near Breakout",
            "CMP": round(close, 2),
            "Buy": buy,
            "SL": sl,
            "Target": round(buy + risk * RR, 2),
            "Qty": int(RISK_PER_TRADE / risk),
            "RSI": round(rsi_t, 1),
            "Vol_X": round(vol / avg_vol, 2),
        }]

    return None

# ================= RUN =================
results = []
for sym in SYMBOLS[:500]:
    r = scan_stock(sym)
    if r:
        results.extend(r)

if results:
    df = pd.DataFrame(results).sort_values("Vol_X", ascending=False)
    file = "breakout_scan.xlsx"
    df.to_excel(file, index=False)
    print(f"✅ Breakout scan saved: {len(df)} stocks")

    msg = "📊 NSE Breakout Summary\n"
    for _, r in df.iterrows():
        msg += (
            f"{r['Stock']} | {r['Type']} | CMP {r['CMP']} | "
            f"Buy {r['Buy']} | SL {r['SL']} | Target {r['Target']} | Qty {r['Qty']}\n"
        )
    send_telegram(msg)
    send_email(file)
else:
    print("⚠️ No breakout found today")
