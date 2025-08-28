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

# ================== PLAYWRIGHT SAFETY NET ==================
def ensure_chromium_once():
    """
    Ensures a safe Chromium install on Streamlit Cloud/containers.
    """
    cache_flag = "/tmp/.chromium_ready"
    if os.path.exists(cache_flag):
        return
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            b.close()
        open(cache_flag, "w").close()
    except Exception:
        try:
            # Install browser
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            open(cache_flag, "w").close()
        except Exception as e:
            st.warning(f"Playwright browser install attempt failed: {e}")

ensure_chromium_once()

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
def scrape_maps(query, limit=50, email_lookup=True):
    rows = []
    seen = set()

    progress = st.progress(0)
    status = st.empty()
    t0 = time.time()
    per_item_times = []

    # Use session state to manage Playwright instance
    # This ensures the browser is not closed between Streamlit runs
    if 'playwright' not in st.session_state:
        st.session_state.playwright = sync_playwright().start()

    if 'browser' not in st.session_state:
        st.session_state.browser = st.session_state.playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
            ],
        )

    if 'context' not in st.session_state:
        st.session_state.context = st.session_state.browser.new_context()

    page = st.session_state.context.new_page()

    try:
        search_url = f"https://www.google.com/maps/search/{requests.utils.quote(query)}"
        page.goto(search_url, timeout=90_000)
        page.wait_for_timeout(2500)

        # Find the feed panel (works for new/old UI)
        feed = page.locator('div[role="feed"]').first
        if not feed.count():
            feed = page.locator('//div[contains(@class,"m6QErb") and @role="region"]').first
        try:
            feed.wait_for(state="visible", timeout=10_000)
        except Exception:
            pass

        def click_show_more():
            try:
                btn = page.locator(
                    '//button[.//span[contains(text(),"More") or contains(text(),"Show") or contains(text(),"और")]]'
                ).first
                if btn.count():
                    btn.click(timeout=2000)
                    page.wait_for_timeout(1200)
            except Exception:
                pass

        cards = page.locator("div.Nv2PK")
        for _ in range(2):
            if cards.count() == 0:
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(600)

        prev_count, stagnant = 0, 0
        max_no_growth_cycles = 12

        # ==== Aggressive scroll till we have >= limit cards ====
        while True:
            try:
                eh = feed.element_handle()
                for _ in range(3):
                    page.evaluate("(el) => el.scrollBy(0, el.clientHeight)", eh)
                    page.wait_for_timeout(450)
            except Exception:
                page.mouse.wheel(0, 4000)

            click_show_more()

            try:
                cur = cards.count()
            except Exception:
                cur = prev_count

            if cur > prev_count:
                prev_count = cur
                stagnant = 0
            else:
                stagnant += 1

            if prev_count >= limit or stagnant >= max_no_growth_cycles:
                break

        total_cards = cards.count()
        total_to_visit = min(total_cards, limit * 2)

        # ==== Visit each card, open detail & extract ====
        fetched = 0
        
        for i in range(total_to_visit):
            if fetched >= limit:
                break
            
            try:
                card = cards.nth(i)
                card.scroll_into_view_if_needed()
                card.click(timeout=4000)
                page.wait_for_timeout(1200)
            except Exception:
                continue

            # Identify the detail pane to scope all subsequent searches
            detail_pane = page.locator('div[jsaction^="pane.place.title"]').first
            if not detail_pane.count():
                continue

            # Name (scoped to the detail pane)
            name = ""
            try:
                name = detail_pane.locator('h1.DUwDvf').inner_text(timeout=3000)
            except Exception:
                continue
                
            # Category (scoped)
            category = ""
            try:
                cat = detail_pane.locator('//button[contains(@jsaction,"pane.rating.category")]').first
                if cat.count():
                    category = cat.inner_text(timeout=1500)
            except Exception:
                pass
            
            # Website (scoped)
            website = ""
            try:
                w = detail_pane.locator('//a[@data-item-id="authority"]').first
                if w.count():
                    website = w.get_attribute("href") or ""
            except Exception:
                pass
            
            # Address (scoped)
            address = ""
            try:
                a = detail_pane.locator('//button[@data-item-id="address"]').first
                if a.count():
                    address = a.inner_text(timeout=1500)
            except Exception:
                pass
            
            # Phone (from maps panel) (scoped)
            phone_maps = ""
            try:
                ph = detail_pane.locator('//button[starts-with(@data-item-id,"phone:")]').first
                if ph.count():
                    phone_maps = ph.inner_text(timeout=1500)
            except Exception:
                pass
                
            # Rating & Review Count (scoped to the detail pane)
            rating = ""
            try:
                # This selector is crucial for scoping the rating to the detail pane
                rating_elem = detail_pane.locator('span.MW4etd').first
                if rating_elem.count():
                    rating = rating_elem.inner_text(timeout=1500)
            except Exception:
                pass
                
            review_count = ""
            try:
                # This selector is crucial for scoping the review count to the detail pane
                review_count_elem = detail_pane.locator('span.UY7F9').first
                if review_count_elem.count():
                    review_count = review_count_elem.inner_text(timeout=1500)
            except Exception:
                pass

            # De-dup by (name + address)
            key = (name.strip(), address.strip())
            if key in seen:
                # Close the detail pane before continuing to the next card
                try:
                    close_btn = page.locator('button[jsaction="pane.place.back.back"]').first
                    if close_btn.count():
                        close_btn.click()
                        page.wait_for_timeout(500)
                except Exception:
                    pass
                continue
            seen.add(key)
            
            # Optional: website se email/extra phone
            email_site, phone_site = "", ""
            t_item0 = time.time()
            if email_lookup and website:
                email_site, phone_site = fetch_email_phone_from_site(website)
            t_item1 = time.time()
            per_item_times.append(t_item1 - t_item0)
            
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
            
            # Close the detail pane to ensure a clean state for the next card
            try:
                close_btn = page.locator('button[jsaction="pane.place.back.back"]').first
                if close_btn.count():
                    close_btn.click()
                    page.wait_for_timeout(500)
            except Exception:
                pass

            # Progress + ETA
            avg = sum(per_item_times) / len(per_item_times) if per_item_times else 0.8
            remaining = max(0, limit - fetched)
            eta = int(avg * remaining)
            progress.progress(int(fetched / max(1, limit) * 100))
            status.text(f"Scraping {fetched}/{limit}… ⏳ ETA: {eta}s")

    finally:
        # Close the page, not the entire browser/context, as they are stored in session state
        page.close()

    progress.empty()
    total_time = int(time.time() - t0)
    status.success(f"✅ Completed in {total_time}s. Got {len(rows)} rows.")
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
