# app.py
import streamlit as st
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
import hashlib, io, requests, re, os, subprocess, sys
from playwright.sync_api import sync_playwright

# ================== APP CONFIG ==================
st.set_page_config(page_title="Maps Scraper + Auth Flow", layout="wide")

# ================== SESSION ROUTER ==================
if "page" not in st.session_state:
    st.session_state.page = "home"
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user" not in st.session_state:
    st.session_state.user = None

def go_to(p):
    st.session_state.page = p

# ================== DB (use st.secrets in production) ==================


def get_connection():
    return psycopg2.connect(
        user="postgres.fpkyghloouywbxbdmqlp",
        password="@Deep7067",
        host="aws-1-ap-south-1.pooler.supabase.com",
        port="5432",
        dbname="postgres",
        sslmode="require",
    )

# ================== SECURITY HELPERS ==================
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

# ---------- USERS ----------
def register_user(username, password, email):
    db = get_connection()
    cur = db.cursor()
    try:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users(
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE,
                password TEXT,
                email TEXT
            );
            """
        )
        db.commit()
        cur.execute(
            "INSERT INTO users (username, password, email) VALUES (%s,%s,%s)",
            (username, hash_password(password), email),
        )
        db.commit()
        return True
    except Exception:
        return False
    finally:
        cur.close(); db.close()

def login_user(username, password):
    db = get_connection()
    cur = db.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        "SELECT * FROM users WHERE username=%s AND password=%s",
        (username, hash_password(password)),
    )
    user = cur.fetchone()
    cur.close(); db.close()
    return user

# ================== PLAYWRIGHT SETUP ==================
@st.cache_resource
def get_browser():
    import subprocess, sys
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    return p, browser

# ================== SCRAPER ==================
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
            if not name or (name in seen): continue
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

# ================== TOPBAR ==================
def topbar():
    cols = st.columns([1,1,1,3])
    with cols[0]:
        if st.button("🏠 Home"): go_to("home")
    with cols[3]:
        if st.session_state.logged_in and st.session_state.user:
            st.info(f"Logged in as **{st.session_state.user['username']}**")
            if st.button("🚪 Logout"):
                st.session_state.logged_in, st.session_state.user = False, None
                go_to("home")

# ================== PAGES ==================
def page_home():
    st.title("Welcome to Maps Scraper 🚀")
    c1, c2 = st.columns(2)
    if st.button("🔑 Login", use_container_width=True): go_to("login")
    if st.button("📝 Signup", use_container_width=True): go_to("signup")
    if st.button("📝 scrapper", use_container_width=True): go_to("scraper")
    # if st.session_state.logged_in: 
    #     st.success("✅ Logged in")
    #     if st.button("➡️ Open Scraper", use_container_width=True): go_to("scraper")

def page_login():
    st.title("Login 🔑")
    u = st.text_input("Username"); p = st.text_input("Password", type="password")
    if st.button("Login"):
        user = login_user(u, p)
        if user: st.session_state.logged_in, st.session_state.user, go_to("scraper") == (True, user, True)
        else: st.error("❌ Invalid credentials")
    st.button("⬅️ Back", on_click=lambda: go_to("home"))

def page_signup():
    st.title("Signup 📝")
    u = st.text_input("Choose Username"); e = st.text_input("Email"); p = st.text_input("Choose Password", type="password")
    if st.button("Create Account"):
        if u and e and p:
            if register_user(u, p, e): st.success("Signup successful! Please login."); go_to("login")
            else: st.error("❌ User exists or DB error.")
        else: st.warning("⚠️ Fill all fields.")
    st.button("⬅️ Back", on_click=lambda: go_to("home"))

def page_scraper():
    # if not st.session_state.logged_in: 
    #     st.error("⚠️ Please login first"); return
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

# ================== ROUTER ==================
topbar()
page = st.session_state.page
if page == "home": page_home()
elif page == "login": page_login()
elif page == "signup": page_signup()
elif page == "scraper": page_scraper()



