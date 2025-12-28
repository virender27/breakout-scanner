# ================= IMPORTS =================
import pandas as pd
import yfinance as yf
import numpy as np
import requests
import smtplib
from email.message import EmailMessage
import time
import datetime as dt
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Border, Side
import warnings
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
ENTRY_VALID_DAYS = 2
MAX_HOLD_DAYS = 5
OFFLINE_CSV = "nse_historical_data.csv"

# ================= EMAIL CONFIG =================
import os
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")        # GitHub Secret
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")     # GitHub Secret
EMAIL_TO = EMAIL_ADDRESS

# ================= UTILS =================
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=5)
    except:
        print("⚠️ Telegram send failed")

def send_email(file_path, recipient):
    msg = EmailMessage()
    msg['Subject'] = "Daily NSE Breakout Scan"
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = recipient
    msg.set_content("Attached is today's NSE Breakout Scan (Confirmed + Near Breakouts).")
    with open(file_path, 'rb') as f:
        file_data = f.read()
        file_name = f.name
    msg.add_attachment(file_data, maintype='application',
                       subtype='vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                       filename=file_name)
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        print(f"📧 Email sent to {recipient}")
    except Exception as e:
        print("⚠️ Failed to send email:", e)

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta>0,0)
    loss = -delta.where(delta<0,0)
    rs = gain.rolling(period).mean()/loss.rolling(period).mean()
    return 100-(100/(1+rs))

def atr(df, period=14):
    tr = pd.concat([df["High"]-df["Low"], abs(df["High"]-df["Close"].shift()), abs(df["Low"]-df["Close"].shift())], axis=1).max(axis=1)
    return tr.rolling(period).mean()

# ================= FETCH NSE SYMBOLS =================
nse = Nse()
all_stock_codes = nse.get_stock_codes()

if isinstance(all_stock_codes, dict):
    SYMBOLS = [s + ".NS" for s in all_stock_codes.keys() if s != "SYMBOL"]
elif isinstance(all_stock_codes, list):
    SYMBOLS = [s + ".NS" for s in all_stock_codes]
else:
    raise TypeError("Unexpected type returned from nse.get_stock_codes()")

print(f"✅ NSE symbols fetched: {len(SYMBOLS)}")

# ================= FETCH DATA =================
def fetch_data(symbol):
    try:
        df = yf.download(symbol, period="4mo", progress=False)
        if len(df) < 60: return None
        return df
    except:
        try:
            df_all = pd.read_csv(OFFLINE_CSV, parse_dates=['Date'])
            df_symbol = df_all[df_all['Symbol']==symbol.replace(".NS","")].copy()
            df_symbol.set_index('Date', inplace=True)
            if len(df_symbol) < 60: return None
            return df_symbol
        except:
            return None

# ================= SCAN FUNCTION =================
def scan_stock(symbol):
    df = fetch_data(symbol)
    if df is None: return None

    df["EMA20"] = ema(df["Close"], 20)
    df["EMA50"] = ema(df["Close"], 50)
    df["RSI"] = rsi(df["Close"])
    df["ATR"] = atr(df)

    today = df.iloc[-1]
    yesterday = df.iloc[-2]

    close = float(today["Close"])
    ema20_val = float(today["EMA20"])
    ema50_val = float(today["EMA50"])
    today_rsi = float(today["RSI"])
    yesterday_rsi = float(yesterday["RSI"])
    atr_val = float(today["ATR"])
    today_vol = float(today["Volume"])

    resistance_d = float(df.iloc[-LOOKBACK_DAYS-1:-1]["High"].max())
    resistance_w = float(df.iloc[-WEEK_LOOKBACK-1:-1]["High"].max())
    avg_vol = float(df.iloc[-LOOKBACK_DAYS-1:-1]["Volume"].mean())

    results = []

    # Confirmed Breakout
    if (close > resistance_d and close > resistance_w and close > ema20_val > ema50_val and
        today_rsi>45 and today_rsi>yesterday_rsi and today_vol>=avg_vol*VOL_MULT and
        (close-resistance_d)/resistance_d<=MAX_EXTENSION and close>MIN_PRICE and avg_vol>MIN_AVG_VOL):

        buy = round(today["High"]*1.002,2)
        sl = round(buy - atr_val*ATR_MULT,2)
        risk = buy - sl
        if risk <= 0: return None
        target = round(buy + risk*RR,2)
        qty = int(RISK_PER_TRADE/risk)
        results.append({
            "Stock": symbol.replace(".NS",""),
            "Type": "Confirmed Breakout",
            "CMP": round(close,2),
            "Daily_Res": round(resistance_d,2),
            "Weekly_Res": round(resistance_w,2),
            "Buy": buy,
            "SL": sl,
            "Target": target,
            "Breakout_Trigger_Price": buy,
            "Qty": qty,
            "RSI": round(today_rsi,1),
            "Vol_X": round(today_vol/avg_vol,2),
        })
        return results

    # Near Breakout
    elif (close >= resistance_d*NEAR_BREAKOUT_THRESHOLD and close<resistance_d and close>ema20_val>ema50_val and
          today_rsi>40 and today_vol>=avg_vol*0.8 and close>MIN_PRICE and avg_vol>MIN_AVG_VOL):

        buy = round(resistance_d*1.002,2)
        sl = round(buy - atr_val*ATR_MULT,2)
        risk = buy - sl
        if risk <= 0: return None
        target = round(buy + risk*RR,2)
        qty = int(RISK_PER_TRADE/risk)
        results.append({
            "Stock": symbol.replace(".NS",""),
            "Type": "Near Breakout",
            "CMP": round(close,2),
            "Daily_Res": round(resistance_d,2),
            "Weekly_Res": round(resistance_w,2),
            "Buy": buy,
            "SL": sl,
            "Target": target,
            "Breakout_Trigger_Price": round(resistance_d*1.002,2),
            "Qty": qty,
            "RSI": round(today_rsi,1),
            "Vol_X": round(today_vol/avg_vol,2),
        })
        return results

    return None

# ================= RUN SCAN =================
final_results = []
for sym in SYMBOLS[:500]:  # optional speed limit
    res = scan_stock(sym)
    if res:
        final_results.extend(res)

if final_results:
    df_out = pd.DataFrame(final_results).sort_values("Vol_X", ascending=False)
    excel_file = "breakout_scan.xlsx"
    df_out.to_excel(excel_file, index=False)
    print(f"✅ Breakout scan saved: {len(df_out)} stocks")

    # Telegram summary
    summary_msg = "📊 Daily NSE Breakout Summary:\n"
    for idx, row in df_out.iterrows():
        summary_msg += (f"{row['Stock']} | {row['Type']} | CMP: {row['CMP']} | "
                        f"Breakout Price: {row['Breakout_Trigger_Price']} | Buy: {row['Buy']} | SL: {row['SL']} | Target: {row['Target']} | Qty: {row['Qty']}\n")
    send_telegram(summary_msg)
    print("✅ Telegram summary sent")

    # Email Excel
    send_email(excel_file, EMAIL_TO)

else:
    print("⚠️ No breakout or near-breakout stocks found today — consider lowering thresholds.")



