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
import time
import re
from playwright.sync_api import sync_playwright

st.set_page_config(page_title="Google Maps Scraper 🚀", layout="wide")

st.title("🗺️ Google Maps Scraper (Playwright + Streamlit)")

query = st.text_input("🔎 Enter your query", "Hospitals in Bhopal")
max_results = st.number_input("Maximum results", min_value=10, max_value=500, value=100, step=10)
extract_email_phone = st.checkbox("Extract Email & Phone from Website", value=True)

if st.button("Start Scraping"):
    st.info("⏳ Scraping in progress... please wait")

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        search_url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
        page.goto(search_url)

        # Scroll loop
        prev_height = 0
        while len(results) < max_results:
            page.mouse.wheel(0, 10000)
            time.sleep(3)

            cards = page.query_selector_all('div[role="article"]')
            for card in cards:
                try:
                    name = card.query_selector('div.fontHeadlineSmall').inner_text()
                except:
                    name = None
                try:
                    address = card.query_selector('div.fontBodyMedium').inner_text()
                except:
                    address = None
                try:
                    phone = card.query_selector('span[aria-label^="+91"]').inner_text()
                except:
                    phone = None

                if name and not any(r["Business Name"] == name for r in results):
                    results.append({
                        "Business Name": name,
                        "Address": address,
                        "Phone": phone,
                        "Website": None,
                        "Email": None
                    })

            # Break if no new data is loading
            curr_height = page.evaluate("document.body.scrollHeight")
            if curr_height == prev_height:
                break
            prev_height = curr_height

        browser.close()

    df = pd.DataFrame(results)

    # Optional Email/Phone extraction from websites
    if extract_email_phone:
        import requests
        from bs4 import BeautifulSoup

        for i, row in df.iterrows():
            if row["Website"]:
                try:
                    r = requests.get(row["Website"], timeout=5)
                    soup = BeautifulSoup(r.text, "html.parser")
                    emails = set(re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", r.text))
                    phones = set(re.findall(r"\+91[0-9]{10}", r.text))
                    if emails:
                        df.at[i, "Email"] = list(emails)[0]
                    if phones:
                        df.at[i, "Phone"] = list(phones)[0]
                except:
                    pass

    st.success(f"✅ Found {len(df)} results.")
    st.dataframe(df)

    # Download buttons
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("⬇ Download CSV", csv, "maps_data.csv", "text/csv")

    excel = df.to_excel("maps_data.xlsx", index=False)
    with open("maps_data.xlsx", "rb") as f:
        st.download_button("⬇ Download Excel", f, "maps_data.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
