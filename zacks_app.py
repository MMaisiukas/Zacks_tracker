import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import time
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

# -----------------------------
# CONFIG
# -----------------------------
BASE_URL = "https://www.zacks.com/stock/quote/{}"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

DEFAULT_TICKERS = [
"LTM","PINE","EZPW","WWD","PAX","FOX","PM","GOOGL","META","ULTA",
"GS","FSUN","AMZN","AAPL","JPM","SANM","NVDA","IBM","LRCX",
"PLTR","UBER","AVGO","MSFT","ADBE","CRM","SPOT","FIGR","SHOP",
"AXON","DUOL","NFLX"
]

# -----------------------------
# ZACKS SCRAPER
# -----------------------------
def get_zacks_rank(ticker):
    url = BASE_URL.format(ticker)
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
    except:
        return ticker, None, None

    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(separator=" ")

    match = re.search(r"Zacks Rank\s*#?(\d)\s*-\s*(Strong Buy|Buy|Hold|Sell|Strong Sell)", text)

    if match:
        rank_num = int(match.group(1))
        rank_text = f"{rank_num} - {match.group(2)}"
        return ticker, rank_num, rank_text
    return ticker, None, None

# -----------------------------
# TEXT COLOR FUNCTIONS
# -----------------------------
def text_color_zacks(val):
    if pd.isna(val):
        return ""
    if val.startswith("1"):
        return "color:#00cc00; font-weight:bold"
    elif val.startswith("2"):
        return "color:#66cc66"
    elif val.startswith("3"):
        return "color:#cccc00"
    elif val.startswith("4"):
        return "color:#ff6666"
    elif val.startswith("5"):
        return "color:#cc0000; font-weight:bold"
    return ""

def text_color_yahoo(val):
    if pd.isna(val):
        return ""
    try:
        num = float(val.split(" - ")[0])
    except:
        return ""
    if num < 1.5:
        return "color:#00cc00; font-weight:bold"
    elif num < 2.5:
        return "color:#66cc66"
    elif num < 3.5:
        return "color:#cccc00"
    elif num < 4.5:
        return "color:#ff6666"
    else:
        return "color:#cc0000; font-weight:bold"

def text_color_change(val):
    if pd.isna(val):
        return ""
    if val > 0:
        return "color:#00cc00; font-weight:bold"
    elif val < 0:
        return "color:#cc0000; font-weight:bold"
    return ""

# -----------------------------
# Convert numeric mean to text
# -----------------------------
def yahoo_rating_text(val):
    if pd.isna(val):
        return "N/A"
    try:
        num = float(val)
    except:
        return "N/A"
    if num < 1.5:
        txt = "Strong Buy"
    elif num < 2.5:
        txt = "Buy"
    elif num < 3.5:
        txt = "Hold"
    elif num < 4.5:
        txt = "Sell"
    else:
        txt = "Strong Sell"
    return f"{num:.2f} - {txt}"

# -----------------------------
# STREAMLIT UI
# -----------------------------
st.set_page_config(page_title="Zacks + Yahoo Dashboard", layout="wide")
st.title("📊 Zacks + Yahoo Analyst Dashboard")

if "tickers" not in st.session_state:
    st.session_state.tickers = DEFAULT_TICKERS.copy()

tickers_input = st.text_area(
    "Enter stock tickers separated by commas:",
    value=",".join(st.session_state.tickers),
    height=100
)

tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
st.session_state.tickers = tickers

if st.button("Fetch Data"):

    if not tickers:
        st.warning("Please enter at least one ticker.")
    else:
        with st.spinner("Fetching data..."):

            rows = []

            # ----- PARALLEL ZACKS SCRAPING -----
            zacks_results = {}
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(get_zacks_rank, t) for t in tickers]
                for future in as_completed(futures):
                    t, rank_num, rank_text = future.result()
                    zacks_results[t] = (rank_num, rank_text)

            # ----- FETCH YAHOO FINANCE -----
            for t in tickers:
                rank_num, rank_text = zacks_results.get(t, (None, None))

                today_price = None
                price_change = None
                analyst_mean = None
                company_name = None

                try:
                    stock = yf.Ticker(t)
                    # Use fast_info for reliable cloud price fetch
                    fast = getattr(stock, "fast_info", {})
                    today_price = fast.get("last_price", None)
                    prev_close = fast.get("previous_close", None)
                    if today_price is not None and prev_close is not None:
                        price_change = (today_price - prev_close) / prev_close * 100
                    else:
                        price_change = None

                    info = stock.info
                    company_name = info.get("shortName", None)
                    analyst_mean = info.get("recommendationMean", None)

                except:
                    pass

                yahoo_display = yahoo_rating_text(analyst_mean)

                rows.append({
                    "Ticker": t,
                    "Company": company_name,
                    "Zacks Rank": rank_text,
                    "Yahoo Avg Rating": yahoo_display,
                    "Current Price": today_price,
                    "Today % Change": price_change,
                    "Zacks Numeric": rank_num
                })

            df = pd.DataFrame(rows)
            df = df.sort_values(by="Zacks Numeric", ascending=True)

            df_display = df[[
                "Ticker",
                "Company",
                "Zacks Rank",
                "Yahoo Avg Rating",
                "Current Price",
                "Today % Change"
            ]]

        st.success("✅ Done!")

        # ----- STYLED DATAFRAME -----
        styled_df = df_display.style \
            .map(text_color_zacks, subset=["Zacks Rank"]) \
            .map(text_color_yahoo, subset=["Yahoo Avg Rating"]) \
            .map(text_color_change, subset=["Today % Change"]) \
            .format({
                "Current Price": lambda x: f"${x:.2f}" if pd.notna(x) else "-",
                "Today % Change": lambda x: f"{x:+.2f}%" if pd.notna(x) else "-"
            })

        st.dataframe(styled_df, width="stretch")
