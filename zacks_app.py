import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import time
import random
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import yfinance as yf

# -----------------------------
# CONFIG
# -----------------------------
BASE_URL = "https://www.zacks.com/stock/quote/{}"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

DEFAULT_TICKERS = [
    "LTM","PINE","EZPW","WWD","PAX","FOX","PM","GOOGL","META","ULTA",
    "GS","FSUN","AMZN","AAPL","JPM","SANM","NVDA","IBM","LRCX",
    "PLTR","UBER","AVGO","MSFT","ADBE","CRM","SPOT","FIGR","SHOP",
    "AXON","DUOL","NFLX"
]

# File used to persist your personal ticker list between sessions.
# This file is NOT meant to be committed to git - add "tickers.txt" to your
# .gitignore so editing your list on your phone never conflicts with the code.
TICKERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tickers.txt")

# How many tickers to scrape from Zacks at once. Keep this modest (3-5) -
# too high and you're back to looking like a bot.
MAX_WORKERS = 4

# -----------------------------
# PERSISTENCE HELPERS
# -----------------------------
def load_saved_tickers():
    if os.path.exists(TICKERS_FILE):
        try:
            with open(TICKERS_FILE, "r") as f:
                saved = [t.strip().upper() for t in f.read().split(",") if t.strip()]
            if saved:
                return saved
        except Exception:
            pass
    return DEFAULT_TICKERS.copy()

def save_tickers(ticker_list):
    with open(TICKERS_FILE, "w") as f:
        f.write(",".join(ticker_list))
    return TICKERS_FILE

# -----------------------------
# ZACKS SCRAPER (threaded)
# -----------------------------
def get_zacks_rank(ticker):
    # Small randomized pause before each request, spread across threads,
    # so request pacing per-ticker still looks the same as a single slow loop.
    time.sleep(random.uniform(0.6, 1.3))

    url = BASE_URL.format(ticker)
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
    except Exception:
        return ticker, None, None

    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(separator=" ")

    match = re.search(r"Zacks Rank\s*#?(\d)\s*-\s*(Strong Buy|Buy|Hold|Sell|Strong Sell)", text)

    if match:
        rank_num = int(match.group(1))
        rank_word = match.group(2)
        return ticker, rank_num, f"{rank_num} - {rank_word}"

    return ticker, None, None

@st.cache_data(ttl=900, show_spinner=False)
def fetch_all_zacks(ticker_tuple):
    results = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(get_zacks_rank, t) for t in ticker_tuple]
        for future in as_completed(futures):
            ticker, rank_num, rank_text = future.result()
            results[ticker] = (rank_num, rank_text)
    return results

# -----------------------------
# YAHOO FINANCE (batched price + threaded info)
# -----------------------------
@st.cache_data(ttl=900, show_spinner=False)
def fetch_batched_prices(ticker_tuple):
    """One request for all tickers' recent price history instead of one per ticker."""
    prices = {}
    try:
        data = yf.download(list(ticker_tuple), period="5d", group_by="ticker",
                            progress=False, threads=True)
    except Exception:
        return prices

    for t in ticker_tuple:
        try:
            if len(ticker_tuple) == 1:
                close_prices = data["Close"].dropna().tail(2)
            else:
                close_prices = data[t]["Close"].dropna().tail(2)

            if len(close_prices) == 2:
                prev_close = close_prices.iloc[0]
                today_price = close_prices.iloc[1]
                change = (today_price - prev_close) / prev_close * 100 if prev_close != 0 else None
            elif len(close_prices) == 1:
                today_price = close_prices.iloc[0]
                change = None
            else:
                today_price, change = None, None

            prices[t] = (today_price, change)
        except Exception:
            prices[t] = (None, None)
    return prices

# Yahoo's unofficial API tends to rate-limit (or silently return empty data)
# when hit with a burst of concurrent requests - especially on shared IPs like
# Streamlit Cloud's. Fewer workers, a small random delay, and a retry on
# failure make it much less likely to trip that.
YAHOO_MAX_WORKERS = 2

def get_yahoo_info(ticker, attempts=2):
    last_error = None
    for attempt in range(attempts):
        time.sleep(random.uniform(0.4, 1.0))
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            if not info or info.get("regularMarketPrice") is None and info.get("shortName") is None:
                # Empty/near-empty dict usually means Yahoo blocked or throttled this request,
                # not that the ticker has no data - worth retrying once.
                last_error = "Empty response from Yahoo (likely rate-limited)"
                continue
            return ticker, info.get("shortName"), info.get("recommendationMean"), info.get("targetMeanPrice"), None
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
    return ticker, None, None, None, last_error

@st.cache_data(ttl=900, show_spinner=False)
def fetch_all_yahoo_info(ticker_tuple):
    results = {}
    errors = {}
    with ThreadPoolExecutor(max_workers=YAHOO_MAX_WORKERS) as executor:
        futures = [executor.submit(get_yahoo_info, t) for t in ticker_tuple]
        for future in as_completed(futures):
            ticker, name, rec_mean, target, error = future.result()
            results[ticker] = (name, rec_mean, target)
            if error:
                errors[ticker] = error
    return results, errors

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
    except Exception:
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

def text_color_target(val, current_price):
    if pd.isna(val) or pd.isna(current_price):
        return ""
    if val > current_price:
        return "color:#00cc00; font-weight:bold"
    elif val < current_price:
        return "color:#cc0000; font-weight:bold"
    return ""

# -----------------------------
# Convert numeric mean to text
# -----------------------------
def yahoo_rating_text(val):
    if pd.isna(val):
        return "-"
    try:
        num = float(val)
    except Exception:
        return "-"
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

# IMPORTANT: the text_area below is keyed "tickers_box". Once a widget with a
# key has been created, Streamlit treats st.session_state["tickers_box"] as the
# single source of truth for it on every future rerun - a separate `value=`
# argument gets silently ignored after the first render. So to programmatically
# set the box's content (loading from file, or the Reset button), we must set
# st.session_state["tickers_box"] itself, and only BEFORE the widget is created
# in that script run (which is why Reset calls st.rerun() right after setting it).
if "tickers_box" not in st.session_state:
    st.session_state["tickers_box"] = ",".join(load_saved_tickers())

tickers_input = st.text_area(
    "Enter stock tickers separated by commas:",
    height=100,
    key="tickers_box"
)

col1, col2, col3 = st.columns([1, 1, 1])
fetch_clicked = col1.button("🔄 Fetch Data")
save_clicked = col2.button("💾 Save as my list")
reset_clicked = col3.button("↩️ Reset to default")

if save_clicked:
    tickers_to_save = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
    if tickers_to_save:
        try:
            path = save_tickers(tickers_to_save)
            st.success(f"Saved {len(tickers_to_save)} tickers to `{path}`.")
        except Exception as e:
            st.error(f"Could not save the ticker list: {e}")
    else:
        st.warning("Nothing to save - the box is empty.")

if reset_clicked:
    st.session_state["tickers_box"] = ",".join(DEFAULT_TICKERS)
    st.rerun()

tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]

if fetch_clicked:

    if not tickers:
        st.warning("Please enter at least one ticker.")
    else:
        with st.spinner(f"Fetching data for {len(tickers)} tickers..."):

            ticker_tuple = tuple(tickers)

            zacks_results = fetch_all_zacks(ticker_tuple)
            price_results = fetch_batched_prices(ticker_tuple)
            yahoo_results, yahoo_errors = fetch_all_yahoo_info(ticker_tuple)

            rows = []
            for t in tickers:
                rank_num, rank_text = zacks_results.get(t, (None, None))
                today_price, price_change = price_results.get(t, (None, None))
                company_name, analyst_mean, target_price = yahoo_results.get(t, (None, None, None))

                yahoo_display = yahoo_rating_text(analyst_mean)

                rows.append({
                    "Ticker": t,
                    "Company": company_name,
                    "Zacks Rank": rank_text,
                    "Yahoo Avg Rating": yahoo_display,
                    "Yahoo Target": target_price,
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
                "Yahoo Target",
                "Current Price",
                "Today % Change"
            ]]

        st.success("✅ Done!")

        if yahoo_errors:
            with st.expander(f"⚠️ Yahoo data missing for {len(yahoo_errors)} ticker(s) - click for details"):
                for t, err in yahoo_errors.items():
                    st.write(f"**{t}**: {err}")
                st.caption(
                    "If most/all of these say 'Empty response' or mention rate limiting, "
                    "Yahoo is temporarily throttling this app - try again in a few minutes "
                    "with fewer tickers. If they show a different error (e.g. about a 'crumb' "
                    "or authentication), that's a Yahoo API change and the yfinance library "
                    "likely needs updating."
                )

        styled_df = df_display.style \
            .map(text_color_zacks, subset=["Zacks Rank"]) \
            .map(text_color_yahoo, subset=["Yahoo Avg Rating"]) \
            .map(lambda x: text_color_target(x, df_display.loc[df_display['Yahoo Target']==x,'Current Price'].values[0] if not pd.isna(x) else None), subset=["Yahoo Target"]) \
            .map(text_color_change, subset=["Today % Change"]) \
            .format({
                "Current Price": lambda x: f"${x:.2f}" if pd.notna(x) else "-",
                "Today % Change": lambda x: f"{x:+.2f}%" if pd.notna(x) else "-",
                "Yahoo Target": lambda x: f"${x:.2f}" if pd.notna(x) else "-"
            })

        st.dataframe(styled_df, use_container_width=True)
