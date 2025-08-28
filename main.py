def scrape_maps(query, limit=50, email_lookup=True):
    """
    Direct Google Maps scraping via Playwright.
    - Robust scrolling (virtualized feed).
    - Click each card → detail page → Name, Website, Address, Phone, Rating, Review Count.
    - Optional website email/phone extraction.
    - De-dup by (name + address).
    """
    rows = []
    seen = set()

    progress = st.progress(0)
    status = st.empty()
    t0 = time.time()
    per_item_times = []

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

        search_url = "https://www.google.com/maps/search/" + requests.utils.quote(query)
        page.goto(search_url, timeout=90_000)
        page.wait_for_timeout(2500)

        # Feed panel पकड़ो
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

        cards = page.locator("div.Nv2PK")  # listing cards

        # कभी पहले render न हों तो nudge
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
        total_to_visit = min(total_cards, limit * 2)  # buffer for duplicates

        # ==== Visit each card, open detail & extract ====
        fetched = 0

        for i in range(total_to_visit):
            if fetched >= limit:
                break

            try:
                card = cards.nth(i)
                card.scroll_into_view_if_needed()
                card.click(timeout=4000)
                page.wait_for_timeout(1200)  # wait for details to load
            except Exception:
                continue

            # === Extract fresh detail panel ===
            try:
                page.wait_for_selector('h1.DUwDvf', timeout=5000)
                name = page.locator('h1.DUwDvf').inner_text(timeout=3000)
            except:
                continue

            # Category
            category = ""
            try:
                cat = page.locator('//button[contains(@jsaction,"pane.rating.category")]').first
                if cat.count():
                    category = cat.inner_text(timeout=1500)
            except:
                pass

            # Website
            website = ""
            try:
                w = page.locator('//a[@data-item-id="authority"]').first
                if w.count():
                    website = w.get_attribute("href") or ""
            except:
                pass

            # Address
            address = ""
            try:
                a = page.locator('//button[@data-item-id="address"]').first
                if a.count():
                    address = a.inner_text(timeout=1500)
            except:
                pass

            # Phone
            phone_maps = ""
            try:
                ph = page.locator('//button[starts-with(@data-item-id,"phone:")]').first
                if ph.count():
                    phone_maps = ph.inner_text(timeout=1500)
            except:
                pass

            # Rating
            rating = ""
            try:
                page.wait_for_selector('span.MW4etd', timeout=3000)
                rating = page.locator('span.MW4etd').first.inner_text()
            except:
                pass

            # Review Count
            review_count = ""
            try:
                page.wait_for_selector('span.UY7F9', timeout=3000)
                review_count = page.locator('span.UY7F9').first.inner_text()
            except:
                pass

            # ✅ Safeguard: avoid duplicate stale values
            if fetched > 0 and rating == rows[-1]["Rating"] and review_count == rows[-1]["Review Count"]:
                page.wait_for_timeout(1000)
                try:
                    rating = page.locator('span.MW4etd').first.inner_text()
                    review_count = page.locator('span.UY7F9').first.inner_text()
                except:
                    pass

            # === De-dup check ===
            key = (name.strip(), address.strip())
            if key in seen:
                continue
            seen.add(key)

            # Optional website email/phone extraction
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

            # Progress + ETA
            avg = sum(per_item_times) / len(per_item_times) if per_item_times else 0.8
            remaining = max(0, limit - fetched)
            eta = int(avg * remaining)
            progress.progress(int(fetched / max(1, limit) * 100))
            status.text(f"Scraping {fetched}/{limit}… ⏳ ETA: {eta}s")

        context.close()
        browser.close()

    progress.empty()
    total_time = int(time.time() - t0)
    status.success(f"✅ Completed in {total_time}s. Got {len(rows)} rows.")
    return pd.DataFrame(rows[:limit])
