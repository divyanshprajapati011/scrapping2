# app.py
import streamlit as st
import pandas as pd
import requests, re, io
from playwright.sync_api import sync_playwright
import time

# ================== APP CONFIG ==================
st.set_page_config(page_title="Google Maps Scraper", layout="wide")
st.title("🚀 Google Maps Scraper")

# ================== HELPERS ==================
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\+?\d[\d\-\(\)\/\. ]{8,}\d")
HEADERS = {"User-Agent": "Mozilla/5.0"}

def fetch_email_phone_from_site(url, timeout=10):
    """Fetch first email and phone from a website"""
    def grab(u):
        try:
            r = requests.get(u, headers=HEADERS, timeout=timeout)
            if 200 <= r.status_code < 400:
                html = r.text
                emails = EMAIL_RE.findall(html)
                phones = PHONE_RE.findall(html)
                return set(emails), set(phones)
        except:
            pass
        return set(), set()
    
    if not url or not url.startswith("http"):
        return "", ""
    
    emails, phones = grab(url)
    for path in ["/contact", "/about", "/support"]:
        e2, p2 = grab(url.rstrip("/") + path)
        emails |= e2
        phones |= p2
    return (next(iter(emails)) if emails else "", next(iter(phones)) if phones else "")

def build_maps_url(query: str) -> str:
    return f"https://www.google.com/maps/search/{requests.utils.quote(query)}"

@st.cache_resource
def get_browser():
    """Start Playwright browser once"""
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    return p, browser
def scrape_maps(query, limit=30, email_lookup=True):
    """Scrape Google Maps search results with robust scrolling"""
    url = build_maps_url(query)
    rows, seen = [], set()
    p, browser = get_browser()
    context = browser.new_context()
    page = context.new_page()
    page.goto(url, timeout=60_000)
    page.wait_for_timeout(3000)  # initial wait

    # Scroll sidebar to load all cards
    last_count = 0
    while True:
        cards = page.locator("div[role='article'], div.Nv2PK")
        page.evaluate(
            "arguments[0].scrollIntoView()",
            cards.nth(cards.count() - 1) if cards.count() else None
        )
        page.wait_for_timeout(1000)
        if cards.count() == last_count or cards.count() >= limit:
            break
        last_count = cards.count()

    st.write(f"Found {cards.count()} cards")  # debug

    for i in range(min(cards.count(), limit)):
        try:
            card = cards.nth(i)
            card.click(timeout=5000)
            page.wait_for_timeout(1000)

            # Safe extraction of each field
            try:
                name = page.locator('h1').first.inner_text(timeout=2000)
            except:
                name = ""
            if not name or name in seen:
                continue
            seen.add(name)

            try:
                website = page.locator('a[data-item-id="authority"]').first.get_attribute("href") if page.locator('a[data-item-id="authority"]').count() else ""
            except:
                website = ""

            try:
                address = page.locator('button[data-item-id="address"]').first.inner_text(timeout=1500) if page.locator('button[data-item-id="address"]').count() else ""
            except:
                address = ""

            try:
                phone_maps = page.locator('button[data-item-id^="phone:"]').first.inner_text(timeout=1500) if page.locator('button[data-item-id^="phone:"]').count() else ""
            except:
                phone_maps = ""

            try:
                rating = page.locator('span.MW4etd').first.inner_text(timeout=1500) if page.locator('span.MW4etd').count() else ""
            except:
                rating = ""

            try:
                review_count = page.locator('span.UY7F9').first.inner_text(timeout=1500) if page.locator('span.UY7F9').count() else ""
            except:
                review_count = ""

            email_site, phone_site = ("", "")
            if email_lookup and website:
                email_site, phone_site = fetch_email_phone_from_site(website)

            rows.append({
                "Business Name": name,
                "Website": website,
                "Address": address,
                "Phone (Maps)": phone_maps,
                "Phone (Website)": phone_site,
                "Email (Website)": email_site,
                "Rating": rating,
                "Review Count": review_count,
                "Source URL": page.url
            })
        except Exception as e:
            st.warning(f"Skipping card {i}: {e}")
            continue

    browser.close()
    return pd.DataFrame(rows)

def df_to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Sheet1")
    buf.seek(0)
    return buf.getvalue()

# ================== STREAMLIT INTERFACE ==================
query = st.text_input("🔎 Enter query", "top coaching in Bhopal")
limit = st.number_input("Number of results", 10, 50, 20, step=5)
email_lookup = st.checkbox("Also fetch Email/Phone from website", True)

if st.button("Start Scraping"):
    with st.spinner("⏳ Scraping…"):
        df = scrape_maps(query, limit, email_lookup)
        if not df.empty:
            st.success(f"✅ Found {len(df)} results.")
            st.dataframe(df)
            st.download_button("⬇️ Download CSV", df.to_csv(index=False).encode("utf-8"), "maps.csv")
            st.download_button("⬇️ Download Excel", df_to_excel_bytes(df), "maps.xlsx")
        else:
            st.warning("No results found. Try adjusting the query.")

