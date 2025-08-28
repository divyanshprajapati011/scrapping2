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

def build_maps_url(query_or_url: str) -> str:
    """Return a valid Google Maps URL from user input"""
    if query_or_url.strip().lower().startswith("http"):
        return query_or_url.strip()
    q = requests.utils.quote(query_or_url.strip())
    return f"https://www.google.com/maps/search/{q}"





def scrape_maps(query_or_url, limit=50, email_lookup=True):
    """
    Google Maps (Playwright) scraper.
    - Converts plain query to Maps URL
    - Aggressive scroll to load enough cards
    - Click each card, wait for detail pane to change
    - Extract: Name, Category, Website, Address, Phone, Rating, Review Count
    - Optional email/phone lookup on website
    """
    url = build_maps_url(query_or_url)
    rows, seen = [], set()

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
        page.goto(url, timeout=90_000)
        page.wait_for_timeout(1500)

        # feed panel (new/old UIs)
        feed = page.locator('div[role="feed"]').first
        if not feed.count():
            feed = page.locator('//div[contains(@class,"m6QErb") and @role="region"]').first

        # cards (robust selector variants)
        cards = page.locator("div.Nv2PK, div.lgrgJe, div.Nv2PK.tH5jfe.PIXjeb")

        # ===== scroll until enough cards are loaded =====
        prev, stagnant, max_no_growth = 0, 0, 14
        for _ in range(120):  # hard cap
            try:
                eh = feed.element_handle()
                for __ in range(3):
                    page.evaluate("(el) => el.scrollBy(0, el.clientHeight)", eh)
                    page.wait_for_timeout(350)
            except Exception:
                page.mouse.wheel(0, 3000)

            cur = 0
            try:
                cur = cards.count()
            except Exception:
                pass

            if cur > prev:
                prev, stagnant = cur, 0
            else:
                stagnant += 1

            if prev >= limit or stagnant >= max_no_growth:
                break

        total_cards = cards.count()
        total_to_visit = min(total_cards, max(limit * 2, limit))  # buffer for dup/closed

        fetched = 0
        last_name_seen = None

        for i in range(total_to_visit):
            if fetched >= limit:
                break

            # ensure the card is in view and clickable
            try:
                card = cards.nth(i)
                card.scroll_into_view_if_needed()
                page.wait_for_timeout(250)
            except Exception:
                continue

            # previous name/rating to detect pane change
            old_name, old_rating = "", ""
            try:
                old_name = page.locator('h1.DUwDvf').inner_text(timeout=1000)
            except Exception:
                pass
            try:
                old_rating = page.locator('span.MW4etd').first.inner_text(timeout=1000)
            except Exception:
                pass

            # click and wait for detail to update
            try:
                card.click(timeout=5000)
                page.wait_for_timeout(800)
                page.wait_for_function(
                    """(oldN, oldR) => {
                        const nm = document.querySelector('h1.DUwDvf');
                        const rt = document.querySelector('span.MW4etd');
                        const newN = nm && nm.innerText ? nm.innerText.trim() : "";
                        const newR = rt && rt.innerText ? rt.innerText.trim() : "";
                        return (newN && newN !== (oldN||"").trim()) || (newR && newR !== (oldR||"").trim());
                    }""",
                    arg=(old_name, old_rating),
                    timeout=10_000
                )
                page.wait_for_timeout(400)  # tiny settle
            except Exception:
                # if pane didn’t change, try once more
                try:
                    card.click(timeout=3000)
                    page.wait_for_timeout(800)
                except Exception:
                    continue

            # ===== extract (scoped to detail pane where possible) =====
            def safe_text(locator_css_or_xpath, timeout=1500):
                try:
                    loc = page.locator(locator_css_or_xpath).first
                    if loc.count():
                        return loc.inner_text(timeout=timeout)
                except Exception:
                    return ""
                return ""

            name = safe_text('h1.DUwDvf', 4000)
            if not name or name == last_name_seen:
                # if we didn’t really change, skip
                continue
            last_name_seen = name

            # category
            category = safe_text('//button[contains(@jsaction,"pane.rating.category")]')

            # website
            website = ""
            try:
                w = page.locator('a[data-item-id="authority"]').first
                if w.count():
                    website = w.get_attribute("href") or ""
            except Exception:
                pass

            # address
            address = safe_text('button[data-item-id="address"]')

            # phone (maps)
            phone_maps = safe_text('button[data-item-id^="phone:"]')

            # rating – try aria-label stars, else numeric span
            rating = ""
            try:
                star = page.locator('span[role="img"][aria-label*="star"]').first
                if star.count():
                    # aria-label like "4.6 stars"
                    m = re.search(r"(\d+(?:\.\d+)?)", star.get_attribute("aria-label") or "")
                    if m:
                        rating = m.group(1)
            except Exception:
                pass
            if not rating:
                rating = safe_text('span.MW4etd')

            # review count – usually "(591)"
            review_count = safe_text('span.UY7F9')
            if review_count:
                m = re.search(r"(\d[\d,\.]*)", review_count)
                if m:
                    review_count = m.group(1).replace(",", "")

            # de-dup (name + address)
            key = (name.strip(), address.strip())
            if key in seen:
                continue
            seen.add(key)

            # optional site email/phone
            email_site, phone_site = "", ""
            if email_lookup and website:
                try:
                    e, p_ = fetch_email_phone_from_site(website)
                    email_site, phone_site = e, p_
                except Exception:
                    pass

            rows.append({
                "Business Name": name,
                "Category": category,
                "Website": website,
                "Address": address,
                "Phone (Maps)": phone_maps,
                "Phone (Website)": phone_site,
                "Email (Website)": email_site,
                "Rating": rating,
                "Review Count": review_count,
                "Source (Maps URL)": page.url
            })

            fetched += 1

        browser.close()

    return pd.DataFrame(rows[:limit])
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



