# import streamlit as st
# import pandas as pd
# import hashlib, io, requests, re, time

# # ================== APP CONFIG ==================
# st.set_page_config(page_title="Maps Scraper 🚀", layout="wide")

# # ================== SCRAPER (SERPAPI + EMAIL LOOKUP) ==================
# SERPAPI_KEY = "ea60d7830fc08072d9ab7f9109e10f1150c042719c20e7d8d9b9c6a25e3afe09"

# EMAIL_REGEX = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
# PHONE_REGEX = r"\+?\d[\d\-\(\) ]{8,}\d"

# def extract_email_phone(website_url):
#     try:
#         resp = requests.get(website_url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
#         text = resp.text
#         emails = re.findall(EMAIL_REGEX, text)
#         phones = re.findall(PHONE_REGEX, text)
#         return emails[0] if emails else "", phones[0] if phones else ""
#     except Exception:
#         return "", ""

# def scrape_maps(query, limit=50, lookup=True):
#     url = "https://serpapi.com/search"
#     params = {"engine": "google_maps", "q": query, "type": "search", "api_key": SERPAPI_KEY}
#     rows, fetched, page = [], 0, 1
#     progress = st.progress(0); status_text = st.empty()
#     start_time, times = time.time(), []

#     while fetched < limit:
#         res = requests.get(url, params=params)
#         data = res.json()
#         local_results = data.get("local_results", [])
#         if not local_results: break

#         for r in local_results:
#             if fetched >= limit: break
#             t0 = time.time()
#             email, phone_site = "", ""
#             if lookup and r.get("website"):
#                 email, phone_site = extract_email_phone(r["website"])

#             rows.append({
#                 "Business Name": r.get("title"),
#                 "Address": r.get("address"),
#                 "Phone (Maps)": r.get("phone"),
#                 "Phone (Website)": phone_site,
#                 "Email (Website)": email,
#                 "Website": r.get("website"),
#                 "Rating": r.get("rating"),
#                 "Reviews": r.get("reviews"),
#                 "Category": r.get("type"),
#                 "Source Link": r.get("link")
#             })
#             fetched += 1
#             t1 = time.time(); times.append(t1 - t0)
#             avg_time = sum(times) / len(times); remaining = limit - fetched
#             eta_sec = int(avg_time * remaining)
#             progress.progress(int(fetched / limit * 100))
#             status_text.text(f"Scraping {fetched}/{limit} businesses (Page {page})... ⏳ ETA: {eta_sec}s")

#         next_url = data.get("serpapi_pagination", {}).get("next")
#         if not next_url or fetched >= limit: break
#         time.sleep(2); url = next_url; params = {}; page += 1

#     progress.empty()
#     status_text.success(f"✅ Scraping complete in {int(time.time() - start_time)}s! (Got {len(rows)} results)")
#     return pd.DataFrame(rows)

# def df_to_excel_bytes(df: pd.DataFrame) -> bytes:
#     buf = io.BytesIO()
#     with pd.ExcelWriter(buf, engine="openpyxl") as writer:
#         df.to_excel(writer, index=False, sheet_name="Sheet1")
#     buf.seek(0)
#     return buf.getvalue()

# # ================== MAIN PAGE ==================
# def page_scraper():
#     st.title("🚀 Google Maps Scraper (No Login Required)")
#     query = st.text_input("🔎 Enter your query", "top coaching in Bhopal")
#     max_results = st.number_input("Maximum results", min_value=5, max_value=500, value=50, step=5)
#     do_lookup = st.checkbox("Extract Email & Phone from Website", value=True)

#     if st.button("Start Scraping"):
#         with st.spinner("⏳ Fetching data from SerpAPI..."):
#             try:
#                 df = scrape_maps(query, int(max_results), lookup=do_lookup)
#                 st.success(f"✅ Found {len(df)} results."); st.dataframe(df, use_container_width=True)
#                 st.download_button("⬇ Download CSV", data=df.to_csv(index=False).encode("utf-8-sig"),
#                                    file_name="maps_scrape.csv", mime="text/csv")
#                 st.download_button("⬇ Download Excel", data=df_to_excel_bytes(df),
#                                    file_name="maps_scrape.xlsx",
#                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
#             except Exception as e:
#                 st.error(f"❌ Scraping failed: {e}")

# # ================== RUN ==================
# page_scraper()








import streamlit as st
import pandas as pd
import re, time
from playwright.sync_api import sync_playwright

# ================== REGEX for Email & Phone ==================
EMAIL_REGEX = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
PHONE_REGEX = r"\+?\d[\d\-\(\) ]{8,}\d"

# ================== Email/Phone Extractor ==================
import requests
def extract_email_phone(website_url):
    try:
        resp = requests.get(website_url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        text = resp.text
        emails = re.findall(EMAIL_REGEX, text)
        phones = re.findall(PHONE_REGEX, text)
        return emails[0] if emails else "", phones[0] if phones else ""
    except:
        return "", ""

# ================== SCRAPER ==================
def scrape_google_maps(query, limit=100, lookup=True):
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = browser.new_page()
        search_url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
        page.goto(search_url, timeout=60000)
        page.wait_for_selector("div.Nv2PK", timeout=20000)

        # Scroll loop to load more results
        last_count = 0
        for _ in range(20):  # scroll up to 20 times
            page.mouse.wheel(0, 4000)
            time.sleep(2)
            cards = page.locator("div.Nv2PK")
            new_count = cards.count()
            if new_count == last_count:
                break
            last_count = new_count
            if new_count >= limit:
                break

        cards = page.locator("div.Nv2PK")
        total = min(cards.count(), limit)

        for i in range(total):
            try:
                card = cards.nth(i)
                card.click(timeout=5000)
                page.wait_for_timeout(2000)

                name = page.locator("h1.DUwDvf").inner_text() if page.locator("h1.DUwDvf").count() else ""
                addr = page.locator("button[data-item-id*='address']").inner_text() if page.locator("button[data-item-id*='address']").count() else ""
                phone = page.locator("button[data-item-id*='phone']").inner_text() if page.locator("button[data-item-id*='phone']").count() else ""
                website = page.locator("a[data-item-id*='authority']").get_attribute("href") if page.locator("a[data-item-id*='authority']").count() else ""
                rating = page.locator("span.F7nice").inner_text() if page.locator("span.F7nice").count() else ""

                email, phone_site = "", ""
                if lookup and website:
                    email, phone_site = extract_email_phone(website)

                results.append({
                    "Business Name": name,
                    "Address": addr,
                    "Phone (Maps)": phone,
                    "Phone (Website)": phone_site,
                    "Email (Website)": email,
                    "Website": website,
                    "Rating": rating
                })
            except Exception as e:
                print("Error:", e)
                continue

        browser.close()
    return pd.DataFrame(results)

# ================== STREAMLIT APP ==================
st.set_page_config(page_title="Google Maps Scraper (Playwright)", layout="wide")
st.title("🚀 Google Maps Scraper (No API, Full Results)")

query = st.text_input("🔎 Enter your query", "Hospitals in Bhopal")
max_results = st.number_input("Maximum results", min_value=10, max_value=500, value=100, step=10)
do_lookup = st.checkbox("Extract Email & Phone from Website", value=True)

if st.button("Start Scraping"):
    with st.spinner("⏳ Scraping Google Maps..."):
        df = scrape_google_maps(query, int(max_results), lookup=do_lookup)
        st.success(f"✅ Found {len(df)} results.")
        st.dataframe(df, use_container_width=True)

        st.download_button("⬇ Download CSV", df.to_csv(index=False).encode("utf-8-sig"),
                           file_name="maps_scrape.csv", mime="text/csv")
        st.download_button("⬇ Download Excel", df.to_excel("maps_scrape.xlsx", index=False),
                           file_name="maps_scrape.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

