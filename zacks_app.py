import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import time
import random
import yfinance as yf

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

DEFAULT_TICKERS = ["AAPL", "MSFT", "NVDA", "TSLA", "FIGR", "AMZN", "GOOGL", "META", "JNJ", "JPM"]

# -----------------------------
# SCRAPER FUNCTION
# -----------------------------
def get_zacks_rank(ticker):
    """Scrape Zacks Rank Description"""
    url = BASE_URL.format(ticker)
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
    except requests.RequestException:
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    rank_block = soup.find("p", class_="rank_view")
    rank_text = rank_block.get_text(strip=True) if rank_block else None
    if rank_text:
        rank_text = re.sub(r"\s*of\s*\d+.*$", "", rank_text)
    return rank_text

# -----------------------------
# STREAMLIT UI
# -----------------------------
st.set_page_config(page_title="Zacks Rank Tracker", layout="wide")
st.title("📊 Zacks Rank Tracker")
st.markdown("Track **Zacks Rank Description** and **today's % change** for your portfolio.")

# Keep ticker list in session state
if "tickers" not in st.session_state:
    st.session_state.tickers = DEFAULT_TICKERS.copy()

# Editable ticker list
tickers_input = st.text_area(
    "Enter stock tickers separated by commas:",
    value=",".join(st.session_state.tickers),
    height=100
)

tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
st.session_state.tickers = tickers

# Fetch data button
if st.button("Fetch Data"):
    if not tickers:
        st.warning("Please enter at least one ticker.")
    else:
        with st.spinner("Fetching data... ⏳"):
            rows = []
            for t in tickers:
                # Get Zacks Rank
                rank = get_zacks_rank(t)
                time.sleep(random.uniform(1, 2))  # polite delay

                # Get company name and price info from yfinance
                try:
                    stock = yf.Ticker(t)
                    info = stock.info
                    company_name = info.get("shortName", None)
                    price_change = None
                    today_price = info.get("regularMarketPrice")
                    prev_close = info.get("regularMarketPreviousClose")
                    if today_price is not None and prev_close is not None:
                        price_change = f"{((today_price - prev_close)/prev_close*100):+.2f}%"
                except Exception:
                    company_name = None
                    price_change = None

                rows.append({
                    "Ticker": t,
                    "Company": company_name,
                    "Rank Description": rank,
                    "Today % Change": price_change
                })

            df = pd.DataFrame(rows)
        st.success("✅ Done!")
        st.dataframe(df[['Ticker', 'Company', 'Rank Description', 'Today % Change']], use_container_width=True)
