import streamlit as st
import psycopg2
import bcrypt
import pandas as pd
import time
import re
import requests
from playwright.sync_api import sync_playwright

# -------------------
# DB CONFIG (Supabase)
# -------------------
DB_CONFIG = {
    "user": "postgres.jsjlthhnrtwjcyxowpza",
    "password": "@Deep7067",
    "host": "aws-1-ap-south-1.pooler.supabase.com",
    "port": "6543",
    "dbname": "postgres",
    "sslmode": "require"
}

# -------------------
# Database Functions
# -------------------
def get_connection():
    return psycopg2.connect(**DB_CONFIG)

def create_table():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    );
    """)
    conn.commit()
    cur.close()
    conn.close()

def add_user(username, password):
    conn = get_connection()
    cur = conn.cursor()
    hashed_pw = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    cur.execute(
        "INSERT INTO users(username,password) VALUES(%s,%s) ON CONFLICT DO NOTHING;",
        (username, hashed_pw.decode("utf-8")),
    )
    conn.commit()
    cur.close()
    conn.close()

def verify_user(username, password):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT password FROM users WHERE username=%s;", (username,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    if result:
        stored_pw = result[0]
        return bcrypt.checkpw(password.encode("utf-8"), stored_pw.encode("utf-8"))
    return False

# -------------------
# Helper Function
# -------------------
def extract_email_phone(website_url):
    """Website से email और phone निकालने की कोशिश"""
    try:
        html = requests.get(website_url, timeout=5).text
        emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", html)
        phones = re.findall(r"\+?\d[\d\-\s]{8,}\d", html)
        email = emails[0] if emails else ""
        phone = phones[0] if phones else ""
        return email, phone
    except:
        return "", ""

# -------------------
# Playwright Scraper
# -------------------
def scrape_maps(query, limit=50, lookup=True):
    rows = []
    fetched = 0
    progress = st.progress(0)
    status_text = st.empty()
    start_time = time.time()
    times = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,
                                    args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.google.com/maps", timeout=60000)
        page.fill("input#searchboxinput", query)
        page.click("button#searchbox-searchbutton")
        page.wait_for_timeout(5000)

        # Scroll करके results load करना
        scrollable = page.locator("div[role='feed']")
        prev_height = 0
        while fetched < limit:
            page.mouse.wheel(0, 10000)
            page.wait_for_timeout(2000)
            curr_height = scrollable.evaluate("el => el.scrollHeight")
            if curr_height == prev_height:  # कोई नया result नहीं मिला
                break
            prev_height = curr_height

            results = page.locator("div[role='article']").all()
            for r in results:
                if fetched >= limit:
                    break
                try:
                    name = r.locator("div[role='heading']").inner_text()
                except:
                    name = ""
                try:
                    rating = r.locator("span[aria-label*='stars']").first.inner_text()
                except:
                    rating = ""
                try:
                    reviews = r.locator("span:has-text('reviews')").inner_text()
                except:
                    reviews = ""
                try:
                    category = r.locator("span[jsinstance]").nth(1).inner_text()
                except:
                    category = ""

                # क्लिक करके detail निकालना
                try:
                    r.click()
                    page.wait_for_timeout(3000)
                    try:
                        address = page.locator("button[data-item-id*='address']").inner_text()
                    except:
                        address = ""
                    try:
                        phone_maps = page.locator("button[data-item-id*='phone']").inner_text()
                    except:
                        phone_maps = ""
                    try:
                        website = page.locator("a[data-item-id*='authority']").get_attribute("href")
                    except:
                        website = ""
                except:
                    address, phone_maps, website = "", "", ""

                email_site, phone_site = "", ""
                if lookup and website:
                    email_site, phone_site = extract_email_phone(website)

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
                    "Source Link": page.url
                })

                fetched += 1

                # ETA
                t1 = time.time()
                times.append(t1 - start_time)
                avg_time = sum(times) / len(times)
                remaining = limit - fetched
                eta_sec = int(avg_time * remaining)
                progress.progress(int(fetched / limit * 100))
                status_text.text(
                    f"Scraping {fetched}/{limit} businesses... ⏳ ETA: {eta_sec}s"
                )

        browser.close()

    progress.empty()
    total_time = int(time.time() - start_time)
    status_text.success(f"✅ Scraping complete in {total_time}s! (Got {len(rows)} results)")

    return pd.DataFrame(rows)

# -------------------
# Streamlit UI
# -------------------
def main():
    st.title("🔐 Google Maps Scraper (Playwright) + Auth")

    create_table()

    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.username = ""

    menu = ["Login", "Signup"]
    choice = st.sidebar.selectbox("Menu", menu)

    if choice == "Signup":
        st.subheader("Create New Account")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Signup"):
            if username and password:
                add_user(username, password)
                st.success("✅ Account created! Now login.")
            else:
                st.error("⚠️ Please enter username & password.")

    elif choice == "Login":
        st.subheader("Login to Your Account")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            if verify_user(username, password):
                st.session_state.logged_in = True
                st.session_state.username = username
                st.success(f"✅ Welcome {username}!")
            else:
                st.error("❌ Invalid Username/Password")

    if st.session_state.logged_in:
        st.sidebar.success(f"Logged in as {st.session_state.username}")
        st.subheader("🔍 Google Maps Scraper")

        query = st.text_input("Enter search query (e.g. restaurants in Delhi)")
        limit = st.number_input("Number of results", min_value=10, max_value=200, step=10, value=50)

        if st.button("Start Scraping"):
            df = scrape_maps(query, limit)
            st.dataframe(df)

            csv = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download CSV", data=csv, file_name="maps_results.csv", mime="text/csv"
            )

if __name__ == "__main__":
    main()
