import pandas as pd
import numpy as np
import yfinance as yf
import requests
import smtplib
from email.message import EmailMessage
from datetime import datetime
import pytz
from nsetools import Nse

# ================== USER SETTINGS ==================

TIMEZONE = pytz.timezone("Asia/Kolkata")

ATR_PERIOD = 14
ATR_MULT = 1.5
VOLUME_MULT = 1.3

# 🔔 TELEGRAM
TELEGRAM_TOKEN = "8270987808:AAHFrPtvl9vxSazNyVkdeKijHNTLniAfMXo"
TELEGRAM_CHAT_ID = "8337253908"

# 📧 EMAIL (Gmail App Password)
EMAIL_ADDRESS = "virender27@gmail.com"
EMAIL_APP_PASSWORD = "kret cevl vcdn pwoa"
EMAIL_TO = "virender27@gmail.com"

# ===================================================

nse = Nse()

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except:
        pass

def send_email(subject, body, attachment):
    try:
        msg = EmailMessage()
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = EMAIL_TO
        msg["Subject"] = subject
        msg.set_content(body)

        with open(attachment, "rb") as f:
            msg.add_attachment(
                f.read(),
                maintype="application",
                subtype="octet-stream",
                filename=attachment
            )

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
            server.send_message(msg)

    except Exception as e:
        print("Email failed:", e)

def atr(df):
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()

def scan_stock(symbol):
    try:
        df = yf.download(symbol + ".NS", period="6mo", interval="1d", progress=False)
        if len(df) < 50:
            return None

        df.dropna(inplace=True)
        df["ATR"] = atr(df)

        today = df.iloc[-1]
        prev = df.iloc[-2]

        avg_vol = df["Volume"].iloc[-20:].mean()

        # -------- CONFIRMED BREAKOUT --------
        if (
            today["Close"] > df["High"].iloc[-20:-1].max() and
            today["Volume"] > avg_vol * VOLUME_MULT
        ):
            high = float(today["High"])
            atr_v = float(today["ATR"])

            buy = round(high * 1.002, 2)
            sl = round(buy - atr_v * ATR_MULT, 2)
            risk = float(buy - sl)

            if risk <= 0 or np.isnan(risk):
                return None

            return {
                "Symbol": symbol,
                "Type": "CONFIRMED",
                "Buy": buy,
                "SL": sl,
                "Target": round(buy + 2 * risk, 2),
                "Volume": int(today["Volume"])
            }

        # -------- NEAR BREAKOUT --------
        if today["Close"] > df["High"].iloc[-20:-1].max() * 0.995:
            high = float(today["High"])
            atr_v = float(today["ATR"])

            buy = round(high * 1.002, 2)
            sl = round(buy - atr_v * ATR_MULT, 2)
            risk = float(buy - sl)

            if risk <= 0 or np.isnan(risk):
                return None

            return {
                "Symbol": symbol,
                "Type": "NEAR",
                "Buy": buy,
                "SL": sl,
                "Target": round(buy + 2 * risk, 2),
                "Volume": int(today["Volume"])
            }

    except:
        return None

    return None

# ================== MAIN ==================

all_symbols = list(nse.get_stock_codes().keys())
all_symbols.remove("SYMBOL")
print(f"✅ NSE symbols fetched: {len(all_symbols)}")

results = []

for sym in all_symbols:
    res = scan_stock(sym)
    if res:
        results.append(res)

if not results:
    send_telegram("❌ No breakout stocks today")
    exit()

df_out = pd.DataFrame(results)
filename = f"nse_breakout_{datetime.now(TIMEZONE).strftime('%Y%m%d')}.xlsx"
df_out.to_excel(filename, index=False)

summary = f"📈 NSE Breakout Scan\nTotal: {len(df_out)} stocks"
send_telegram(summary)
send_email("NSE Breakout Scan", summary, filename)

print("✅ Scan complete")
