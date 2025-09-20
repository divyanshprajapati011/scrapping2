# app.py
import streamlit as st
import pandas as pd
import io, requests, re, subprocess, sys
from playwright.sync_api import sync_playwright

# ================== APP CONFIG ==================
st.set_page_config(page_title="Maps Scraper", layout="wide")

# ================== PLAYWRIGHT SETUP ==================
@st.cache_resource
@st.cache_resource
def get_browser():
    """Cache Playwright browser (Streamlit reruns safe)."""
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    except Exception:
        pass

    p = sync_playwright().start()
    browser = p.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"]
    )
    return p, browser
# ================== SCRAPER HELPERS ==================
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\+?\d[\d\-\(\)\/\. ]{8,}\d")
HEADERS = {"User-Agent": "Mozilla/5.0"}

def fetch_email_phone_from_site(url, timeout=10):
    def grab(u):
        try:
            r = requests.get(u, headers=HEADERS, timeout=timeout)
            if 200 <= r.status_code < 400:
                html = r.text
                emails = EMAIL_RE.findall(html)
                phones = PHONE_RE.findall(html)
                return set(emails), set(phones)
        except Exception:
            pass
        return set(), set()

    if not url or not url.startswith("http"):
        return "", ""

    emails, phones = grab(url)
    for path in ["/contact", "/about", "/support"]:
        e2, p2 = grab(url.rstrip("/") + path)
        emails |= e2
        phones |= p2

    return (next(iter(emails)) if emails else "",
            next(iter(phones)) if phones else "")

def build_maps_url(q: str) -> str:
    return q if q.startswith("http") else f"https://www.google.com/maps/search/{requests.utils.quote(q)}"

def scrape_maps(query, limit=30, email_lookup=True):
    url = build_maps_url(query)
    rows, seen = [], set()
    p, browser = get_browser()
    context = browser.new_context()
    page = context.new_page()
    page.goto(url, timeout=60_000)
    page.wait_for_timeout(1500)

    cards = page.locator("div.Nv2PK")
    for i in range(min(cards.count(), limit)):
        try:
            card = cards.nth(i)
            card.click(timeout=5000)
            page.wait_for_timeout(800)

            name = page.locator('h1.DUwDvf').inner_text(timeout=2000)
            if not name or (name in seen): 
                continue
            seen.add(name)

            website = ""
            if page.locator('a[data-item-id="authority"]').count():
                website = page.locator('a[data-item-id="authority"]').first.get_attribute("href")

            address = page.locator('button[data-item-id="address"]').inner_text(timeout=1500) if page.locator('button[data-item-id="address"]').count() else ""
            phone_maps = page.locator('button[data-item-id^="phone:"]').inner_text(timeout=1500) if page.locator('button[data-item-id^="phone:"]').count() else ""
            rating = page.locator('span.MW4etd').inner_text(timeout=1500) if page.locator('span.MW4etd').count() else ""
            review_count = page.locator('span.UY7F9').inner_text(timeout=1500) if page.locator('span.UY7F9').count() else ""

            email_site, phone_site = ("","")
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
        except Exception:
            continue

    return pd.DataFrame(rows)

# ================== DOWNLOAD HELPERS ==================
def df_to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Sheet1")
    buf.seek(0)
    return buf.getvalue()

# ================== MAIN PAGE ==================
def page_scraper():
    st.title("🚀 Google Maps Scraper")
    q = st.text_input("🔎 Enter query", "top coaching in Bhopal")
    n = st.number_input("Results", 10, 100, 30, step=10)
    lookup = st.checkbox("Also fetch Email/Phone from site", value=True)

    if st.button("Start Scraping"):
        with st.spinner("⏳ Scraping…"):
            try:
                df = scrape_maps(q, int(n), lookup)
                st.success(f"✅ Found {len(df)} results.")
                st.dataframe(df)
                st.download_button("⬇️ CSV", df.to_csv(index=False).encode("utf-8"), "maps.csv")
                st.download_button("⬇️ Excel", df_to_excel_bytes(df), "maps.xlsx")
            except Exception as e:
                st.error(f"❌ Scraping failed: {e}")

# Run page
page_scraper()

