import streamlit as st
import psycopg2
import pandas as pd
import time, re, requests
from playwright.sync_api import sync_playwright

# ---------- DB CONFIG ----------
DB_CONFIG = {
    "user": "postgres.jsjlthhnrtwjcyxowpza",
    "password": "@Deep7067",
    "host": "aws-1-ap-south-1.pooler.supabase.com",
    "port": "6543",
    "dbname": "postgres",
    "sslmode": "require"
}

# ---------- Email/Phone Extract ----------
EMAIL_REGEX = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
PHONE_REGEX = r"\+?\d[\d\-\(\) ]{8,}\d"

def extract_email_phone(website_url):
    try:
        resp = requests.get(website_url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        text = resp.text
        emails = re.findall(EMAIL_REGEX, text)
        phones = re.findall(PHONE_REGEX, text)
        return (emails[0] if emails else ""), (phones[0] if phones else "")
    except:
        return "", ""

# ---------- Scraper ----------
def scrape_maps(url, limit=50, email_lookup=True):
    rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox","--disable-dev-shm-usage","--disable-gpu",
                "--disable-blink-features=AutomationControlled"
            ]
        )
        context = browser.new_context()
        page = context.new_page()
        page.goto(url, timeout=60000)

        cards = page.locator('//a[contains(@href,"/maps/place")]')
        seen = set()

        progress = st.progress(0)
        status_text = st.empty()
        start_time = time.time()
        times = []

        while len(rows) < limit:
            count = cards.count()
            for i in range(count):
                if len(rows) >= limit: break
                try:
                    card = cards.nth(i)
                    link = card.get_attribute("href")
                    if not link or link in seen: continue
                    seen.add(link)

                    card.click()
                    page.wait_for_timeout(2000)

                    # ---- extract details ----
                    try: name = page.locator('//h1[contains(@class,"fontHeadlineLarge")]').inner_text()
                    except: name = ""

                    try: rating = page.locator('//span[@aria-label[contains(.,"star")]]').first.inner_text()
                    except: rating = ""

                    try:
                        rev_text = page.locator('//span[contains(text(),"reviews")]').first.inner_text()
                        reviews = re.search(r"(\d[\d,]*)", rev_text).group(1)
                    except: reviews = ""

                    try: address = page.locator('//button[contains(@aria-label,"Address")]').inner_text()
                    except: address = ""

                    try: phone_maps = page.locator('//button[contains(@aria-label,"Phone:")]').inner_text()
                    except: phone_maps = ""

                    try: website = page.locator('//a[contains(@aria-label,"Website:")]').get_attribute("href")
                    except: website = ""

                    try: category = page.locator('//button[contains(@aria-label,"Category:")]').inner_text()
                    except: category = ""

                    email_site, phone_site = "", ""
                    if email_lookup and website:
                        email_site, phone_site = extract_email_phone(website)

                    # ---- Save row ----
                    rows.append({
                        "Business Name": name,
                        "Address": address,
                        "Phone (Maps)": phone_maps,
                        "Phone (Website)": phone_site,
                        "Email (Website)": email_site,
                        "Website": website,
                        "Rating": rating,
                        "Reviews": reviews,
                        "Category": category,
                        "Source Link": link
                    })

                    # ETA update
                    t1 = time.time()
                    times.append(t1 - start_time)
                    avg_time = sum(times) / len(times)
                    remaining = limit - len(rows)
                    eta_sec = int(avg_time * remaining)

                    progress.progress(int(len(rows) / limit * 100))
                    status_text.text(f"Scraping {len(rows)}/{limit} ... ⏳ ETA: {eta_sec}s")

                except Exception as e:
                    continue

            page.mouse.wheel(0, 2000)
            time.sleep(2)
            cards = page.locator('//a[contains(@href,"/maps/place")]')

        browser.close()

    progress.empty()
    total_time = int(time.time() - start_time)
    status_text.success(f"✅ Scraping complete in {total_time}s! ({len(rows)} results)")
    return pd.DataFrame(rows)

# ---------- DB Setup ----------
def get_conn():
    return psycopg2.connect(**DB_CONFIG)

def create_users_table():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,
    email TEXT NOT NULL
    );
    """)
    conn.commit()
    conn.close()

def add_user(username, password):
    if not username or not password:  # safeguard
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users(username,password) VALUES(%s,%s) ON CONFLICT DO NOTHING;",
        (username, password)
    )
    conn.commit()
    conn.close()


def check_user(username, password):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username=%s AND password=%s;", (username,password))
    user = cur.fetchone()
    conn.close()
    return user

# ---------- UI Pages ----------
def home():
    st.title("🏠 Google Maps Scraper Tool")
    st.write("➡️ Please Signup or Login to continue")

def signup():
    st.title("🔑 Signup")
    u = st.text_input("Username")
    p = st.text_input("Password", type="password")
    if st.button("Signup"):
        add_user(u, p)
        st.success("✅ Signup successful! Please login now.")

def login():
    st.title("🔐 Login")
    u = st.text_input("Username")
    p = st.text_input("Password", type="password")
    if st.button("Login"):
        user = check_user(u, p)
        if user:
            st.session_state.logged_in = True
            st.success("✅ Logged in successfully!")
        else:
            st.error("❌ Invalid credentials")

def scraper_page():
    st.title("🕵️ Google Maps Scraper")
    query_url = st.text_input("Enter Google Maps Search URL")
    limit = st.number_input("How many results?", min_value=10, max_value=200, value=50, step=10)

    if st.button("Start Scraping"):
        if not query_url:
            st.warning("⚠️ Please enter Google Maps search URL")
        else:
            df = scrape_maps(query_url, limit=limit, email_lookup=True)
            st.dataframe(df)

            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download CSV", csv, "results.csv", "text/csv")

            excel = df.to_excel("results.xlsx", index=False)
            with open("results.xlsx", "rb") as f:
                st.download_button("📥 Download Excel", f, "results.xlsx")

# ---------- Main App ----------
create_users_table()

menu = ["Home", "Signup", "Login", "Scraper"]
choice = st.sidebar.selectbox("Menu", menu)

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if choice == "Home":
    home()
elif choice == "Signup":
    signup()
elif choice == "Login":
    login()
elif choice == "Scraper":
    if st.session_state.logged_in:
        scraper_page()
    else:
        st.warning("⚠️ Please login first")


