# main.py
import streamlit as st
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
import hashlib, io, time, urllib.parse, re, requests, os, subprocess, sys
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

# ================== DB ==================
def get_connection():
    return psycopg2.connect(
        user="postgres.jsjlthhnrtwjcyxowpza",
        password="@Deep7067",
        host="aws-1-ap-south-1.pooler.supabase.com",
        port="6543",
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

# ================== PLAYWRIGHT SAFETY NET ==================
def ensure_chromium_once():
    cache_flag = "/tmp/.chromium_ready"
    if os.path.exists(cache_flag):
        return
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            browser.close()
        open(cache_flag, "w").close()
    except Exception:
        try:
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            open(cache_flag, "w").close()
        except Exception as e:
            st.warning(f"Playwright browser install attempt failed: {e}")

ensure_chromium_once()

# ================== SCRAPER UTILS ==================
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+?\d[\d\-\s]{7,}\d)")
HEADERS = {"User-Agent": "Mozilla/5.0"}

def get_maps_url(user_input: str):
    user_input = user_input.strip()
    if "google.com/search" in user_input and "q=" in user_input:
        m = re.search(r"q=([^&]+)", user_input)
        if m:
            query_text = urllib.parse.unquote(m.group(1))
            return "https://www.google.com/maps/search/" + urllib.parse.quote_plus(query_text)
    elif "google.com/maps" in user_input:
        return user_input
    else:
        return "https://www.google.com/maps/search/" + urllib.parse.quote_plus(user_input)

def fetch_email_phone_from_site(url, timeout=12):
    if not url or not url.startswith("http"):
        return "", ""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        html = resp.text
        emails = list({e for e in EMAIL_RE.findall(html)})
        phones = list({p.strip() for p in PHONE_RE.findall(html)})
        return "; ".join(emails[:5]), "; ".join(phones[:5])
    except Exception:
        return "", ""

# ================== SCRAPER FUNCTION ==================
def scrape_maps(url, limit=100, email_lookup=True):
    rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context()
        page = context.new_page()
        page.goto(url, timeout=60_000)
        time.sleep(4)

        cards = page.locator("//div[contains(@class,'Nv2PK')]").all()
        count, last_name = 0, None

        for card in cards:
            if limit and count >= limit:
                break
            try:
                card.scroll_into_view_if_needed()
                card.click()
                page.wait_for_timeout(1400)
            except Exception:
                continue

            try:
                name = page.locator('//h1[contains(@class,"DUwDvf")]').inner_text(timeout=3000)
            except Exception:
                continue
            if name == last_name:
                continue
            last_name = name

            website, address, phone, rating = "", "", "", ""
            try:
                if page.locator('//a[@data-item-id="authority"]').count():
                    website = page.locator('//a[@data-item-id="authority"]').get_attribute("href", timeout=1000) or ""
                if page.locator('//button[@data-item-id="address"]').count():
                    address = page.locator('//button[@data-item-id="address"]').inner_text(timeout=1000)
                if page.locator('//button[starts-with(@data-item-id,"phone:")]').count():
                    phone = page.locator('//button[starts-with(@data-item-id,"phone:")]').inner_text(timeout=1000)
                el = page.locator('//span[@role="img" and contains(@aria-label,"stars")]')
                if el.count():
                    aria = el.get_attribute("aria-label", timeout=1000) or ""
                    r1 = re.search(r"(\d+(?:\.\d+)?)", aria)
                    rating = r1.group(1) if r1 else ""
            except Exception:
                pass

            email_from_site, extra_phones_from_site = ("", "")
            if email_lookup and website:
                email_from_site, extra_phones_from_site = fetch_email_phone_from_site(website)

            rows.append({
                "Business Name": name,
                "Website": website,
                "Address": address,
                "Phone (Maps)": phone,
                "Email (from site)": email_from_site,
                "Extra Phones (from site)": extra_phones_from_site,
                "Rating": rating,
                "Source (Maps URL)": page.url
            })
            count += 1

        context.close()
        browser.close()
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
        if st.button("🏠 Home"):
            go_to("home")
    # with cols[1]:
    #     if st.button("🔑 Login"):
    #         go_to("login")
    # with cols[2]:
    #     if st.button("📝 Signup"):
    #         go_to("signup")
    with cols[3]:
        if st.session_state.logged_in and st.session_state.user:
            u = st.session_state.user["username"]
            st.info(f"Logged in as **{u}**")
            if st.button("🚪 Logout"):
                st.session_state.logged_in = False
                st.session_state.user = None
                go_to("home")

# ================== PAGES ==================
def page_home():
    st.title("Welcome to Maps Scraper 🚀")
    st.write("Choose an option below to continue.")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🔑 Go to Login", use_container_width=True):
            go_to("login")
    with c2:
        if st.button("📝 Create Account", use_container_width=True):
            go_to("signup")
    if st.session_state.logged_in:
        st.success("You are already logged in.")
        if st.button("➡️ Open Scraper", use_container_width=True):
            go_to("scraper")

def page_login():
    st.title("Login 🔑")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        user = login_user(username, password)
        if user:
            st.session_state.logged_in = True
            st.session_state.user = user
            st.success("Login successful! Redirecting to Scraper...")
            go_to("scraper")
        else:
            st.error("Invalid credentials")
    st.button("⬅️ Back", on_click=lambda: go_to("home"))

def page_signup():
    st.title("Signup 📝")
    new_user = st.text_input("Choose Username")
    new_email = st.text_input("Email")
    new_pass = st.text_input("Choose Password", type="password")
    if st.button("Create Account"):
        if new_user and new_email and new_pass:
            if register_user(new_user, new_pass, new_email):
                st.success("Signup successful! Please login now.")
                go_to("login")
            else:
                st.error("User already exists or DB error.")
        else:
            st.warning("Please fill all fields.")
    st.button("⬅️ Back", on_click=lambda: go_to("home"))

def page_scraper():
    if not st.session_state.logged_in or not st.session_state.user:
        st.error("Please login first")
        if st.button("Go to Login"):
            go_to("login")
        return
    st.title("🚀 Google Maps Scraper")
    user_input = st.text_input("🔎 Enter query OR Google Search URL OR Google Maps URL", "top coaching in Bhopal")
    max_results = st.number_input("Maximum results to fetch", min_value=5, max_value=500, value=60, step=5)
    do_email_lookup = st.checkbox("Website से Email/extra Phones भी निकालें (slower)", value=True)
    start_btn = st.button("Start Scraping")
    if start_btn:
        maps_url = get_maps_url(user_input)
        if not maps_url.strip():
            st.error("Please enter a valid URL or query")
        else:
            with st.spinner("Scraping in progress..."):
                try:
                    df = scrape_maps(maps_url, int(max_results), bool(do_email_lookup))
                    st.success(f"Scraping completed! Found {len(df)} results.")
                    st.dataframe(df, use_container_width=True)
                    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
                    st.download_button("⬇️ Download CSV", data=csv_bytes, file_name="maps_scrape.csv", mime="text/csv")
                    xlsx_bytes = df_to_excel_bytes(df)
                    st.download_button(
                        "⬇️ Download Excel",
                        data=xlsx_bytes,
                        file_name="maps_scrape.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                except Exception as e:
                    st.error(f"Scraping failed: {e}")

# ================== LAYOUT ==================
topbar()

# Simple router
page = st.session_state.page
if page == "home":
    page_home()
elif page == "login":
    page_login()
elif page == "signup":
    page_signup()
elif page == "scraper":
    page_scraper()
else:
    page_home()
