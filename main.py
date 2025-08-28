# app.py
import streamlit as st
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
import hashlib, io, requests, re, os, subprocess, sys, time
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

# ================== DB (env vars recommended) ==================
# If you want to use values directly, replace os.getenv(...) below with your values.
DB_USER = "postgres.jsjlthhnrtwjcyxowpza"
DB_PASS = "@Deep7067"
DB_HOST = "aws-1-ap-south-1.pooler.supabase.com"
DB_PORT = "6543"
DB_NAME = "postgres"
DB_SSLMODE = "require"

def get_connection():
    return psycopg2.connect(
        user=DB_USER,
        password=DB_PASS,
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        sslmode=os.getenv("DB_SSLMODE", "prefer"),
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

# ================== PLAYWRIGHT SETUP WITH CACHE ==================
@st.cache_resource
def get_playwright_resources():
    """
    Initializes and caches Playwright, browser, and context to prevent
    thread-related issues on Streamlit reruns.
    """
    try:
        # Check if Chromium is already installed by Playwright
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    except Exception as e:
        st.warning(f"Playwright browser install attempt failed: {e}")

    p = sync_playwright().start()
    browser = p.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-blink-features=AutomationControlled",
        ],
    )
    context = browser.new_context()
    return p, browser, context

# ================== SCRAPER UTILS ==================
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\+?\d[\d\-\(\)\/\. ]{8,}\d")
HEADERS = {"User-Agent": "Mozilla/5.0"}

def fetch_email_phone_from_site(url, timeout=10):
    """
    Finds email/phone from website HTML.
    Also probes common pages like /contact or /about.
    """
    def grab(u):
        try:
            r = requests.get(u, headers=HEADERS, timeout=timeout, allow_redirects=True)
            if r.status_code >= 200 and r.status_code < 400:
                html = r.text
                emails = EMAIL_RE.findall(html)
                phones = [p.strip() for p in PHONE_RE.findall(html)]
                return set(emails), set(phones)
        except Exception:
            pass
        return set(), set()

    if not url or not url.startswith("http"):
        return "", ""

    emails, phones = grab(url)

    # Try common subpages to improve hit-rate
    for path in ["/contact", "/contact-us", "/about", "/about-us", "/support", "/en/contact"]:
        try:
            u2 = url.rstrip("/") + path
            e2, p2 = grab(u2)
            emails |= e2
            phones |= p2
        except Exception:
            pass

    email = next(iter(emails)) if emails else ""
    phone = next(iter(phones)) if phones else ""
    return email, phone

# ================== CORE SCRAPER (DIRECT GOOGLE MAPS) ==================
from playwright.sync_api import sync_playwright
import re

def scrape_maps(url, limit=50, email_lookup=True):
    rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context()
        page = context.new_page()
        page.goto(url, timeout=60000)

        # wait for results list
        page.wait_for_selector('//div[@role="article"]')

        cards = page.locator('//div[@role="article"]').all()
        for idx, card in enumerate(cards[:limit]):
            try:
                # scroll card into view
                card.scroll_into_view_if_needed()
                page.wait_for_timeout(800)

                # store old values to detect change
                old_name, old_rating = "", ""
                try:
                    old_name = page.locator('h1.DUwDvf').inner_text(timeout=2000)
                except:
                    pass
                try:
                    old_rating = page.locator('//span[contains(@class,"MW4etd")]').inner_text(timeout=2000)
                except:
                    pass

                # click card
                card.click(timeout=5000)
                page.wait_for_timeout(1200)

                # wait until detail panel updates (name OR rating changes)
                try:
                    page.wait_for_function(
                        """(oldN, oldR) => {
                            let nm = document.querySelector('h1.DUwDvf');
                            let rt = document.querySelector('span.MW4etd');
                            if (!nm || !rt) return false;
                            let newN = nm.innerText.trim();
                            let newR = rt.innerText.trim();
                            return (newN && newN !== oldN?.trim()) || (newR && newR !== oldR?.trim());
                        }""",
                        arg=(old_name, old_rating),
                        timeout=10000
                    )
                except:
                    pass

                # === extract data ===
                name, address, phone_maps, rating, review_count, website, email = [""]*7

                try:
                    name = page.locator('h1.DUwDvf').inner_text()
                except:
                    pass
                try:
                    address = page.locator('button[data-item-id="address"]').inner_text()
                except:
                    pass
                try:
                    phone_maps = page.locator('button[data-item-id^="phone:"]').inner_text()
                except:
                    pass
                try:
                    rating = page.locator('//span[contains(@class,"MW4etd")]').first.inner_text()
                except:
                    pass
                try:
                    review_count = page.locator('//span[contains(@class,"UY7F9")]').first.inner_text()
                except:
                    pass
                try:
                    website = page.locator('a[data-item-id="authority"]').get_attribute("href")
                except:
                    pass

                # optional: lookup email/phone from website
                if email_lookup and website:
                    try:
                        wp = context.new_page()
                        wp.goto(website, timeout=10000)
                        html = wp.content()
                        match_email = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", html)
                        if match_email:
                            email = match_email.group(0)
                        wp.close()
                    except:
                        pass

                rows.append({
                    "Name": name,
                    "Address": address,
                    "Phone (Maps)": phone_maps,
                    "Phone (Website)": "",
                    "Email (Website)": email,
                    "Rating": rating,
                    "Review Count": review_count,
                    "Source (Maps URL)": page.url,
                })

            except Exception as e:
                print(f"Error on card {idx}: {e}")
                continue

        browser.close()

    return pd.DataFrame(rows[:limit])

    # progress.empty()
    # total_time = int(time.time() - t0)
    # status.success(f"✅ Completed in {total_time}s. Got {len(rows)} rows.")


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
    st.write("Signup → Login → Scrape Google Maps data (Direct Playwright)")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🔑 Login", use_container_width=True):
            go_to("login")
    with c2:
        if st.button("📝 Signup", use_container_width=True):
            go_to("signup")
    if st.session_state.logged_in:
        st.success("✅ You are logged in")
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
            st.success("✅ Login successful! Redirecting to Scraper…")
            go_to("scraper")
        else:
            st.error("❌ Invalid credentials")
    st.button("⬅️ Back", on_click=lambda: go_to("home"))

def page_signup():
    st.title("Signup �")
    new_user = st.text_input("Choose Username")
    new_email = st.text_input("Email")
    new_pass = st.text_input("Choose Password", type="password")
    if st.button("Create Account"):
        if new_user and new_email and new_pass:
            if register_user(new_user, new_pass, new_email):
                st.success("Signup successful! Please login now.")
                go_to("login")
            else:
                st.error("❌ User exists or DB error.")
        else:
            st.warning("⚠️ Please fill all fields.")
    st.button("⬅️ Back", on_click=lambda: go_to("home"))

def page_scraper():
    if not st.session_state.logged_in or not st.session_state.user:
        st.error("⚠️ Please login first")
        if st.button("Go to Login"):
            go_to("login")
        return

    st.title("🚀 Google Maps Scraper (Direct Playwright)")
    query = st.text_input("🔎 Enter query", "top coaching in Bhopal")
    max_results = st.number_input("Maximum results to fetch", min_value=10, max_value=500, value=50, step=10)
    do_lookup = st.checkbox("Also extract Email/Phone from website", value=True)

    if st.button("Start Scraping"):
        with st.spinner("⏳ Scraping in progress…"):
            try:
                df = scrape_maps(query, int(max_results), email_lookup=do_lookup)
                st.success(f"✅ Found {len(df)} results.")
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
                st.error(f"❌ Scraping failed: {e}")

# ================== LAYOUT ==================
topbar()
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


