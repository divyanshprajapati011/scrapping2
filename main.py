import streamlit as st
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
import hashlib, io, requests, re
import time

# ================== APP CONFIG ==================
st.set_page_config(page_title="Maps Scraper 🚀", layout="wide")

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

# ================== SCRAPER (SERPAPI + EMAIL LOOKUP) ==================
SERPAPI_KEY = "ea60d7830fc08072d9ab7f9109e10f1150c042719c20e7d8d9b9c6a25e3afe09"   # 🔑 अपनी key डालो

EMAIL_REGEX = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
PHONE_REGEX = r"\+?\d[\d\-\(\) ]{8,}\d"

def extract_email_phone(website_url):
    """website से email और phone extract करने का helper"""
    try:
        resp = requests.get(website_url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        text = resp.text
        emails = re.findall(EMAIL_REGEX, text)
        phones = re.findall(PHONE_REGEX, text)

        email = emails[0] if emails else ""
        phone = phones[0] if phones else ""
        return email, phone
    except Exception:
        return "", ""


def scrape_maps(query, limit=50, lookup=True):
    """SerpAPI से Google Maps scraping + Pagination + Progress + ETA"""
    url = "https://serpapi.com/search"
    params = {
        "engine": "google_maps",
        "q": query,
        "type": "search",
        "api_key": SERPAPI_KEY,
    }

    rows = []
    fetched = 0
    page = 1

    progress = st.progress(0)
    status_text = st.empty()
    start_time = time.time()
    times = []

    while fetched < limit:
        res = requests.get(url, params=params)
        data = res.json()

        local_results = data.get("local_results", [])
        if not local_results:
            break  # कोई और data नहीं मिला

        for r in local_results:
            if fetched >= limit:
                break

            t0 = time.time()

            email, phone_site = "", ""
            if lookup and r.get("website"):
                email, phone_site = extract_email_phone(r["website"])

            rows.append({
                "Business Name": r.get("title"),
                "Address": r.get("address"),
                "Phone (Maps)": r.get("phone"),
                "Phone (Website)": phone_site,
                "Email (Website)": email,
                "Website": r.get("website"),
                "Rating": r.get("rating"),
                "Reviews": r.get("reviews"),
                "Category": r.get("type"),
                "Source Link": r.get("link")
            })

            fetched += 1
            t1 = time.time()
            times.append(t1 - t0)

            # ETA calc
            avg_time = sum(times) / len(times)
            remaining = limit - fetched
            eta_sec = int(avg_time * remaining)

            progress.progress(int(fetched / limit * 100))
            status_text.text(
                f"Scraping {fetched}/{limit} businesses (Page {page})... ⏳ ETA: {eta_sec}s"
            )

        # Pagination (अगर next page है तो)
        next_page_token = data.get("serpapi_pagination", {}).get("next_page_token")
        if not next_page_token:
            break  # और pages नहीं मिले

        params = {
            "engine": "google_maps",
            "type": "search",
            "api_key": SERPAPI_KEY,
            "next_page_token": next_page_token
        }
        page += 1

        # ⏳ Wait before next call (SerpAPI docs suggest ~2s)
        time.sleep(2)

    progress.empty()
    total_time = int(time.time() - start_time)
    status_text.success(f"✅ Scraping complete in {total_time}s! (Got {len(rows)} results)")

    return pd.DataFrame(rows)


def df_to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Sheet1")
    buf.seek(0)
    return buf.getvalue()

# ================== TOPBAR ==================
def topbar():
    cols = st.columns([1, 3])
    with cols[0]:
        if st.button("🏠 Home"):
            go_to("home")
    with cols[1]:
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
    st.write("Signup → Login → Scrape Google Maps data")
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
            st.success("✅ Login successful! Redirecting to Scraper...")
            go_to("scraper")
        else:
            st.error("❌ Invalid credentials")
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
                st.error("❌ User already exists or DB error.")
        else:
            st.warning("⚠️ Please fill all fields.")
    st.button("⬅️ Back", on_click=lambda: go_to("home"))

def page_scraper():
    if not st.session_state.logged_in or not st.session_state.user:
        st.error("⚠️ Please login first")
        if st.button("Go to Login"):
            go_to("login")
        return

    st.title("🚀 Google Maps Scraper ")
    query = st.text_input("🔎 Enter your query", "top coaching in Bhopal")
    max_results = st.number_input("Maximum results to fetch", min_value=5, max_value=500, value=50, step=5)
    do_lookup = st.checkbox("Extract Email & Phone from Website", value=True)

    start_btn = st.button("Start Scraping")

    if start_btn:
        with st.spinner("⏳ Fetching data from SerpAPI..."):
            try:
                df = scrape_maps(query, int(max_results), lookup=do_lookup)
                st.success(f"✅ Found {len(df)} results.")
                st.dataframe(df, use_container_width=True)

                csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
                st.download_button("⬇️ Download CSV", data=csv_bytes, file_name="maps_scrape.csv", mime="text/csv")

                xlsx_bytes = df_to_excel_bytes(df)
                st.download_button("⬇️ Download Excel", data=xlsx_bytes,
                                   file_name="maps_scrape.xlsx",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
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
