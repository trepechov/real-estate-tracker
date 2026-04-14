#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Real Estate Tracker
General purpose scraper for imot.bg. Supports custom URLs and CSV output in reports/ folder.
"""

import re
import time
import random
import os
import argparse
import csv
from datetime import date, datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import json
import gspread
import statistics

# ─────────────────────────────────────────────
# CONSTANTS & DEFAULTS
# ─────────────────────────────────────────────
DEFAULT_OUTPUT = "listings.csv"
REPORTS_DIR = "reports"

# Column definitions (Schema)
COLUMN_HEADERS = [
    "ID", "Status", "Price", "PriceSQM", "vsAvg", "Location", "Type", "Area", "FloorTotal",
    "Construction", "Year", "Broker", "FirstSeen", "DateSold", "DaysMarket", "LastSeen", "URL"
]

# Status Labels
STATUS_NEW        = "new"
STATUS_1W         = "1 week"
STATUS_2W         = "2 weeks"
STATUS_3W         = "3 weeks"
STATUS_4W         = "4 weeks"
STATUS_SOLD       = "sold"
STATUS_SOLD_Q     = "sold?"

# ─────────────────────────────────────────────
# BROWSER AUTOMATION
# ─────────────────────────────────────────────

def scroll_page(page):
    """Scroll down slowly to trigger any lazy loading."""
    current_height = page.evaluate("document.body.scrollHeight")
    for i in range(1, 4):
        page.evaluate(f"window.scrollTo(0, {current_height * i / 4})")
        time.sleep(random.uniform(0.5, 1.0))
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(1)

def scrape_page(page, url):
    """Scrape a results page using Playwright."""
    print(f"  Navigating to: {url}")
    try:
        page.goto(url, wait_until="networkidle", timeout=60000)
    except Exception as e:
        print(f"  [ERROR] Failed to load {url}: {e}")
        return []
    
    # Check for cookie consent
    try:
        consent_selector = "button:has-text('Приемам'), .didomi-continue-without-agreeing"
        if page.is_visible(consent_selector, timeout=2000):
            page.click(consent_selector)
            time.sleep(1)
    except:
        pass

    scroll_page(page)
    
    content = page.content()
    soup = BeautifulSoup(content, "html.parser")
    items = soup.select("div[id^='ida']")
    properties = []

    for item in items:
        prop_id = item.get("id", "").replace("ida", "")
        if not prop_id: continue

        # URL Extraction
        link_el = item.select_one("a[href*='obiava']")
        raw_href = link_el["href"] if link_el else ""
        if not raw_href:
            prop_url = ""
        elif raw_href.startswith("http"):
            prop_url = raw_href
        elif raw_href.startswith("//"):
            prop_url = "https:" + raw_href
        else:
            prop_url = "https://www.imot.bg" + (raw_href if raw_href.startswith("/") else "/" + raw_href)

        # Price Extraction (Take only EUR part, ignore BGN)
        price_el = item.select_one(".price")
        price_text = price_el.get_text(" ", strip=True) if price_el else ""
        # Match the first number sequence (EUR) and ignore the rest (BGN usually follows)
        price_match = re.search(r"^([\d\s]+)", price_text)
        price_clean = re.sub(r"[^\d]", "", price_match.group(1)) if price_match else ""
        price_parsed = int(price_clean) if price_clean else None

        full_text = item.get_text(" ", strip=True)
        area_match = re.search(r"(\d+)\s*кв\.м", full_text)
        area = int(area_match.group(1)) if area_match else None

        floor_match = re.search(r"(\d+)-[а-я]+\s+ет\.\s*от\s*(\d+)", full_text)
        floor = int(floor_match.group(1)) if floor_match else None
        total_floors = int(floor_match.group(2)) if floor_match else None

        type_match = re.search(r"Продава\s+(\d-СТАЕН)", full_text)
        prop_type = type_match.group(1) if type_match else ""

        loc_el = item.select_one("location") or item.select_one(".location")
        location = loc_el.get_text(strip=True) if loc_el else ""

        price_per_sqm = round(price_parsed / area) if price_parsed and area else None

        # Construction Type Extraction
        c_match = re.search(r"(тухл|панел|епк|пълзящ кофраж|гредоред)", full_text, re.IGNORECASE)
        construction = ""
        if c_match:
            c_text = c_match.group(1).lower()
            if "тухл" in c_text: construction = "Тухла"
            elif "панел" in c_text: construction = "Панел"
            elif "епк" in c_text or "пълзящ" in c_text: construction = "ЕПК"
            elif "гредоред" in c_text: construction = "Гредоред"

        # Year Extraction
        year_match = re.search(r"(18\d{2}|19\d{2}|20\d{2})\s*г\.", full_text, re.IGNORECASE)
        if not year_match:
            year_match = re.search(r"(18\d{2}|19\d{2}|20\d{2})", full_text)
        year = int(year_match.group(1)) if year_match else ""

        # Broker / Agency Extraction
        broker = "Частно лице"  # Default to private
        
        # 1. Try the direct seller name (User's suggested selector)
        seller_name_el = item.select_one(".seller .name")
        if seller_name_el:
            broker = seller_name_el.get_text(strip=True)
        else:
            # 2. Fallback to agency link (subdomain of imot.bg)
            broker_el = item.select_one('a[href*=".imot.bg"]:not(.saveSlink):not([href*="www.imot.bg"])')
            if broker_el:
                name = broker_el.get_text(strip=True)
                if name:
                    broker = name
                else:
                    # 3. Check for logo img title if text is empty
                    img = broker_el.select_one("img")
                    if img and img.get("alt"):
                        broker = img.get("alt")

        properties.append({
            "ID": prop_id,
            "URL": prop_url,
            "Location": location,
            "Type": prop_type,
            "Area": area,
            "FloorTotal": f"{floor}/{total_floors}" if floor else "",
            "Construction": construction,
            "Year": year,
            "Price": price_parsed,
            "PriceSQM": price_per_sqm,
            "Broker": broker,
        })

    return properties

def extract_top_metrics(soup):
    """Extract metrics from the top summary box on the search results page."""
    metrics = {
        "TotalResults": 0,
        "MedianPrice": 0,
        "MedianSQM": 0
    }
    
    # Total Results
    # Pattern 1: Намерени са 85 обяви (Sometimes on first page/specific agents)
    # Pattern 2: от общо 85 обяви (Common in list-info header)
    text_content = soup.get_text()
    match = re.search(r"Намерени[^\d]*(\d+)", text_content.replace("\xa0", " ").replace(" ", ""))
    if not match:
        match = re.search(r"общо(\d+)обяви", text_content.replace("\xa0", " ").replace(" ", ""))
    
    if match:
        metrics["TotalResults"] = int(match.group(1))
    
    # Fallback to specifically checking span/div if needed
    if metrics["TotalResults"] == 0:
        for el in soup.select("span, div.list-info"):
            t = el.get_text().replace(" ", "").replace("\xa0", "")
            m = re.search(r"(\d+)", t)
            if "Намерени" in t or "общо" in t:
                m = re.search(r"(\d+)", t)
                if m:
                    metrics["TotalResults"] = int(m.group(1))
                    break

    # Prices (Median)
    # The box with 'медианна стойност'
    summary_box = soup.find("div", class_="params2", style=lambda s: s and "float:right" in s)
    if summary_box:
        text = summary_box.get_text(" ", strip=True)
        # Regex for numbers followed by 'euro'
        # Group 1: Price, Group 2: SQM Price
        prices = re.findall(r"([\d\s]+)\s*euro", text)
        if len(prices) >= 2:
            metrics["MedianPrice"] = int(re.sub(r"\s+", "", prices[0]))
            metrics["MedianSQM"] = int(re.sub(r"\s+", "", prices[1]))
            
    return metrics

def get_last_summary(output_name):
    """Load the most recent metrics from the summary CSV."""
    summary_filename = output_name.replace(".csv", "") + "_summary.csv"
    summary_path = os.path.join(REPORTS_DIR, summary_filename)
    
    if not os.path.exists(summary_path):
        return None
        
    try:
        with open(summary_path, mode='r', encoding='utf-8') as f:
            reader = list(csv.DictReader(f))
            if not reader: return None
            # Return the last row
            row = reader[-1]
            return {
                "ScrapedCount": int(row.get("ScrapedCount", 0)),
                "TotalPages": int(row.get("TotalPages", 0)),
                "MedianPrice": int(float(row.get("MedianPrice", 0))),
                "MedianPriceSQM": int(float(row.get("MedianPriceSQM", 0)))
            }
    except:
        return None

def scrape_all(urls, optimized=True, datastore=None):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        all_props = []
        seen_ids = set()

        for base_url in urls:
            metrics = {
                "TotalResults": 0,
                "MedianPrice": 0,
                "MedianSQM": 0
            }
            try:
                page.goto(base_url, wait_until="networkidle", timeout=60000)
                soup = BeautifulSoup(page.content(), "html.parser")
                
                # Extract site-official metrics
                metrics = extract_top_metrics(soup)
                
                # Get total pages
                page_links = [a.get_text(strip=True) for a in soup.select("a") if re.match(r"^\d+$", a.get_text(strip=True))]
                nums = [int(p) for p in page_links if p.isdigit()]
                total_pages = max(nums) if nums else 1

                # OPTIMIZATION CHECK
                if optimized and datastore:
                    last = datastore.get_last_metrics()
                    if last:
                        # Comparison against official site numbers stored in previous run
                        if (metrics["TotalResults"] == last.get("ScrapedCount") and
                            metrics["MedianPrice"] == last.get("MedianPrice") and
                            metrics["MedianSQM"] == last.get("MedianPriceSQM") and
                            total_pages == last.get("TotalPages")):
                            
                            print(f"  [Smart Check] No changes detected since last run ({metrics['TotalResults']} results, {total_pages} pages). Skipping.")
                            # Still need to scrape page 1 to return current results for sync
                            props = scrape_page(page, base_url)
                            all_props.extend(props)
                            return all_props, total_pages, metrics, True

                print(f"  Detected {total_pages} pages")

                for page_num in range(1, total_pages + 1):
                    if page_num == 1:
                        page_url = base_url
                    else:
                        parts = base_url.split("?", 1)
                        page_url = f"{parts[0]}/p-{page_num}?{parts[1]}" if len(parts) > 1 else f"{parts[0]}/p-{page_num}"
                    
                    print(f"  Scraping Page {page_num}/{total_pages}")
                    props = scrape_page(page, page_url)
                    for p_dict in props:
                        if p_dict["ID"] not in seen_ids:
                            seen_ids.add(p_dict["ID"])
                            all_props.append(p_dict)
                    time.sleep(random.uniform(2, 4))
            except Exception as e:
                print(f"  [ERROR] Failed to process {base_url}: {e}")

        browser.close()
        return all_props, total_pages, metrics, False

# ─────────────────────────────────────────────
# DATA STORAGE (Abstracted for future Google Sheets)
# ─────────────────────────────────────────────

class CSVDataStore:
    def __init__(self, filename):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        self.filename = filename 
        self.filepath = os.path.join(REPORTS_DIR, filename)

    def get_last_metrics(self):
        """Standard interface for Smart Check."""
        return get_last_summary(self.filename)

    def load_existing(self):
        """Load history from CSV if it exists."""
        if not os.path.exists(self.filepath):
            return {}
        
        history = {}
        with open(self.filepath, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                history[row["ID"]] = row
        return history

    def save(self, properties, today, median_sqm=0):
        """Update history and save to cumulative CSV."""
        history = self.load_existing()
        today_str = today.strftime("%Y-%m-%d")
        scraped_ids = {p["ID"] for p in properties}

        # 1. Update existing and mark sold
        for pid, data in history.items():
            if pid not in scraped_ids:
                # Mark as sold if not previously sold
                if data["Status"] not in (STATUS_SOLD, STATUS_SOLD_Q):
                    data["Status"] = STATUS_SOLD
                    data["DateSold"] = today_str
                    # Compute days on market
                    try:
                        fs = datetime.strptime(data["FirstSeen"], "%Y-%m-%d").date()
                        data["DaysMarket"] = (today - fs).days
                    except:
                        pass
            else:
                # Update last seen for active
                data["LastSeen"] = today_str

        # 2. Integrate today's scrape
        for p in properties:
            pid = p["ID"]
            if pid in history:
                # Update price and compute status
                data = history[pid]
                data["Price"] = p["Price"]
                data["PriceSQM"] = p["PriceSQM"]
                data["Broker"] = p.get("Broker", data.get("Broker", ""))
                data["Construction"] = p.get("Construction", data.get("Construction", ""))
                data["Year"] = p.get("Year", data.get("Year", ""))
                data["Status"] = self.compute_status(data["FirstSeen"], today)
                data["LastSeen"] = today_str
            else:
                # New listing
                new_row = {h: "" for h in COLUMN_HEADERS}
                new_row.update(p)
                new_row.update({
                    "Status": STATUS_NEW,
                    "FirstSeen": today_str,
                    "LastSeen": today_str,
                    "DateSold": "",
                    "DaysMarket": "",
                })
                history[pid] = new_row

        # 3. Update vsAvg for all active properties based on current median
        for pid, data in history.items():
            if data["Status"] not in (STATUS_SOLD, STATUS_SOLD_Q):
                try:
                    p_sqm = int(data.get("PriceSQM", 0))
                    if median_sqm > 0 and p_sqm > 0:
                        diff = int(median_sqm - p_sqm)
                        data["vsAvg"] = f"{'+' if diff > 0 else ''}{diff}"
                except:
                    pass

        # Write back to CSV
        with open(self.filepath, mode='w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=COLUMN_HEADERS)
            writer.writeheader()
            # Sort by FirstSeen descending for readability
            sorted_history = sorted(history.values(), key=lambda x: x["FirstSeen"], reverse=True)
            writer.writerows(sorted_history)

    def compute_status(self, first_seen_str, today):
        try:
            fs = datetime.strptime(first_seen_str, "%Y-%m-%d").date()
            days = (today - fs).days
            if days < 7: return STATUS_NEW
            if days < 14: return STATUS_1W
            if days < 21: return STATUS_2W
            if days < 28: return STATUS_3W
            return STATUS_4W
        except:
            return STATUS_NEW

class GoogleSheetsDataStore:
    def __init__(self, spreadsheet_id, sheet_name):
        self.spreadsheet_id = spreadsheet_id
        self.sheet_name = sheet_name
        self.gc = self._authenticate()
        self.spreadsheet = self.gc.open_by_key(self.spreadsheet_id)
        self.worksheet = self._get_or_create_worksheet()

    def _authenticate(self):
        # 1. Try Environment Variable (GitHub Actions)
        creds_json = os.environ.get("GSPREAD_SERVICE_ACCOUNT_JSON")
        if creds_json:
            creds_dict = json.loads(creds_json)
            return gspread.service_account_from_dict(creds_dict)
            
        # 2. Try Local File
        local_creds_path = os.path.join("secrets", "service_account.json")
        if os.path.exists(local_creds_path):
            return gspread.service_account(filename=local_creds_path)
            
        raise ValueError("No Google Sheets credentials found. Set GSPREAD_SERVICE_ACCOUNT_JSON or add secrets/service_account.json")

    def _get_or_create_worksheet(self):
        try:
            return self.spreadsheet.worksheet(self.sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            # Create a larger sheet to accommodate the D-column offset
            ws = self.spreadsheet.add_worksheet(title=self.sheet_name, rows="1000", cols=str(len(COLUMN_HEADERS) + 4))
            return ws

    def get_last_metrics(self):
        """Read metrics from the summary section (B1:B6)."""
        try:
            values = self.worksheet.get("B1:B6")
            if not values or len(values) < 5: return None
            return {
                "ScrapedCount": int(values[1][0]) if len(values[1]) > 0 else 0,
                "TotalPages": int(values[2][0]) if len(values[2]) > 0 else 0,
                "MedianPrice": int(float(values[3][0])) if len(values[3]) > 0 else 0,
                "MedianPriceSQM": int(float(values[4][0])) if len(values[4]) > 0 else 0
            }
        except:
            return None

    def load_existing(self):
        """Load history from Sheets, skipping Columns A-C and starting from Column D."""
        all_values = self.worksheet.get_all_values()
        if not all_values: return {}
        
        # We expect headers at D1
        header_row = all_values[0]
        if len(header_row) < 4 or header_row[3] != "ID":
            # Might be old format or new empty sheet
            return {}

        headers = header_row[3:] # ID, Price, etc.
        history = {}
        for row_values in all_values[1:]:
            if len(row_values) > 3:
                row_data = row_values[3:]
                # Pad if row is shorter than headers
                row_data += [""] * (len(headers) - len(row_data))
                row_dict = {headers[i]: row_data[i] for i in range(len(headers))}
                if row_dict.get("ID"):
                    history[str(row_dict["ID"])] = row_dict
        return history

    def save(self, properties, today, summary_data=None, median_sqm=0):
        """Update history and save to Sheets with integrated summary."""
        history = self.load_existing()
        today_str = today.strftime("%Y-%m-%d")
        scraped_ids = {str(p["ID"]) for p in properties}

        # 1. Update existing/mark sold
        for pid, data in history.items():
            if pid not in scraped_ids:
                if data["Status"] not in (STATUS_SOLD, STATUS_SOLD_Q):
                    data["Status"] = STATUS_SOLD
                    data["DateSold"] = today_str
                    try:
                        fs = datetime.strptime(data["FirstSeen"], "%Y-%m-%d").date()
                        data["DaysMarket"] = str((today - fs).days)
                    except:
                        pass
            else:
                data["LastSeen"] = today_str

        # 2. Integrate today's scrape
        for p in properties:
            pid = str(p["ID"])
            if pid in history:
                data = history[pid]
                data["Price"] = str(p["Price"])
                data["PriceSQM"] = str(p["PriceSQM"])
                data["Broker"] = p.get("Broker", data.get("Broker", ""))
                data["Construction"] = str(p.get("Construction", data.get("Construction", "")))
                data["Year"] = str(p.get("Year", data.get("Year", "")))
                data["Status"] = self.compute_status(data["FirstSeen"], today)
                data["LastSeen"] = today_str
            else:
                new_row = {h: "" for h in COLUMN_HEADERS}
                new_row.update({k: str(v) for k, v in p.items()})
                new_row.update({
                    "Status": STATUS_NEW,
                    "FirstSeen": today_str,
                    "LastSeen": today_str,
                    "DateSold": "",
                    "DaysMarket": "",
                })
                history[pid] = new_row

        # 3. Update vsAvg for all active properties
        for pid, data in history.items():
            if data["Status"] not in (STATUS_SOLD, STATUS_SOLD_Q):
                try:
                    p_sqm = int(float(data.get("PriceSQM", 0)))
                    if median_sqm > 0 and p_sqm > 0:
                        diff = int(median_sqm - p_sqm)
                        data["vsAvg"] = f"{'+' if diff > 0 else ''}{diff}"
                except:
                    pass

        # 4. Prepare full table starting from Column D
        sorted_history = sorted(history.values(), key=lambda x: x["FirstSeen"], reverse=True)
        
        # Prepare Rows
        final_rows = []
        
        # Header Row (Row 1)
        header_row = [""] * 3 + COLUMN_HEADERS
        # Summary Labels and Meta
        if summary_data:
            header_row[0] = "Timestamp"
            header_row[1] = summary_data["Timestamp"]
        final_rows.append(header_row)

        # Body Rows
        summary_labels = ["ScrapedCount", "TotalPages", "MedianPrice", "MedianPriceSQM", "WasSkipped", "URL", "Duration"]
        for i, row in enumerate(sorted_history):
            row_list = [""] * 3 + [row.get(h, "") for h in COLUMN_HEADERS]
            # Add labels in Column A and values in Column B for first few rows
            if summary_data and i < len(summary_labels):
                label = summary_labels[i]
                row_list[0] = label
                row_list[1] = str(summary_data.get(label, ""))
            final_rows.append(row_list)
        
        # Handle cases where summary has more rows than properties (rare but possible)
        if summary_data and len(sorted_history) < len(summary_labels):
            for i in range(len(sorted_history), len(summary_labels)):
                label = summary_labels[i]
                final_rows.append([label, str(summary_data.get(label, "")), "", ""] + [""] * len(COLUMN_HEADERS))

        # Batch update
        self.worksheet.clear()
        self.worksheet.update(values=final_rows, range_name="A1")
        
        # Formatting
        try:
            # Table Header D1:Q1 (or whatever width)
            end_col = chr(ord('A') + len(COLUMN_HEADERS) + 3) if len(COLUMN_HEADERS) + 3 < 26 else "Z"
            self.worksheet.format(f"D1:{end_col}1", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9}})
            # Summary Labels A1:A6
            self.worksheet.format("A1:A8", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.95, "green": 0.95, "blue": 0.95}})
        except:
            pass
            
        print(f"  [Sheets] Updated '{self.sheet_name}' with {len(sorted_history)} listings and execution summary.")

    def compute_status(self, first_seen_str, today):
        # Re-using the same logic as CSV but checking for date format
        try:
            fs = datetime.strptime(first_seen_str, "%Y-%m-%d").date()
            days = (today - fs).days
            if days < 7: return STATUS_NEW
            if days < 14: return STATUS_1W
            if days < 21: return STATUS_2W
            if days < 28: return STATUS_3W
            return STATUS_4W
        except:
            return STATUS_NEW

def save_summary(output_name, scraped_count, total_pages, median_price, median_sqm, was_skipped, search_urls="", duration_seconds=0):
    """Save execution summary to a separate CSV and print to console."""
    summary_filename = output_name.replace(".csv", "") + "_summary.csv"
    summary_path = os.path.join(REPORTS_DIR, summary_filename)

    timestamp = datetime.now(ZoneInfo("Europe/Sofia")).strftime("%Y-%m-%d %H:%M:%S")
    mins, secs = divmod(int(duration_seconds), 60)
    duration_str = f"{mins}m {secs}s"
    headers = ["Timestamp", "ScrapedCount", "TotalPages", "MedianPrice", "MedianPriceSQM", "WasSkipped", "URL", "Duration"]
    row = {
        "Timestamp": timestamp,
        "ScrapedCount": scraped_count,
        "TotalPages": total_pages,
        "MedianPrice": f"{median_price:.0f}" if median_price else "0",
        "MedianPriceSQM": f"{median_sqm:.0f}" if median_sqm else "0",
        "WasSkipped": was_skipped,
        "URL": search_urls,
        "Duration": duration_str
    }

    file_exists = os.path.exists(summary_path)
    needs_headers = not file_exists

    existing_rows = []
    if file_exists:
        with open(summary_path, 'r', encoding='utf-8') as f:
            reader = list(csv.DictReader(f))
            if reader and ("URL" not in reader[0] or "WasSkipped" not in reader[0]):
                needs_headers = True
                existing_rows = reader

    mode = 'w' if needs_headers else 'a'
    with open(summary_path, mode=mode, encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        if needs_headers:
            writer.writeheader()
            for r in existing_rows:
                complete_row = {h: r.get(h, "") for h in headers}
                writer.writerow(complete_row)
        writer.writerow(row)

    return row

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Real Estate Scraper for imot.bg")
    parser.add_argument("--urls", nargs="+", help="List of imot.bg search URLs")
    parser.add_argument("--output", type=str, default=DEFAULT_OUTPUT, help="Output filename in reports/ folder")
    parser.add_argument("--csv", action="store_true", help="Save to local CSV instead of Google Sheets")
    parser.add_argument("--full", action="store_true", help="Force a full scrape, skipping the optimization check")
    args = parser.parse_args()

    # Support both `--urls url1 url2` and `--urls "url1 url2"` (quoted in CI to escape &)
    if args.urls:
        urls = []
        for u in args.urls:
            urls.extend(u.split())
        args.urls = urls

    if not args.urls:
        print("Error: No URLs provided. Use --urls followed by imot.bg links.")
        return

    today = date.today()
    start_time = time.time()
    print(f"Starting Scrape - {today}")

    # Storage selection logic
    sheet_id = os.environ.get("SPREADSHEET_ID")
    if not sheet_id:
        local_id_path = os.path.join("secrets", "spreadsheet_id.txt")
        if os.path.exists(local_id_path):
            with open(local_id_path, "r") as f:
                sheet_id = f.read().strip()

    has_creds = os.environ.get("GSPREAD_SERVICE_ACCOUNT_JSON") or os.path.exists(os.path.join("secrets", "service_account.json"))

    # Default to Google Sheets; fall back to CSV if --csv flag or credentials missing
    use_sheets = not args.csv and bool(sheet_id and has_creds)

    if use_sheets:
        sheet_name = args.output.replace(".csv", "") if args.output else "listings"
        print(f"Target: Google Sheet ID '{sheet_id}' (Tab: '{sheet_name}')")
    else:
        if not args.csv and not (sheet_id and has_creds):
            print("Warning: Google Sheets credentials not found, falling back to CSV.")
        output_file = args.output if args.output.endswith(".csv") else f"{args.output}.csv"
        print(f"Target: Local CSV '{REPORTS_DIR}/{output_file}'")
    
    # Initialize Store early for optimization check
    if use_sheets:
        store = GoogleSheetsDataStore(sheet_id, sheet_name)
    else:
        store = CSVDataStore(output_file)
        
    scraped, total_pages, official_metrics, was_skipped = scrape_all(args.urls, optimized=not args.full, datastore=store)
    if not scraped:
        print("No data found.")
        return
    
    # Use official site metrics for the summary report
    # If official metrics are missing (unlikely), fall back to calculation
    median_price = official_metrics["MedianPrice"] if official_metrics["MedianPrice"] else 0
    median_sqm = official_metrics["MedianSQM"] if official_metrics["MedianSQM"] else 0
    scraped_count = official_metrics["TotalResults"] if official_metrics["TotalResults"] else len(scraped)

    search_urls_str = " ".join(args.urls)
    elapsed = time.time() - start_time
    mins, secs = divmod(int(elapsed), 60)
    duration_str = f"{mins}m {secs}s"

    # Save summary to CSV only in local mode (sheets mode has its own summary tab)
    summary_data = save_summary(args.output, scraped_count, total_pages, median_price, median_sqm, was_skipped, search_urls_str, elapsed) if not use_sheets else {
        "Timestamp": datetime.now(ZoneInfo("Europe/Sofia")).strftime("%Y-%m-%d %H:%M:%S"),
        "ScrapedCount": scraped_count,
        "TotalPages": total_pages,
        "MedianPrice": f"{median_price:.0f}" if median_price else "0",
        "MedianPriceSQM": f"{median_sqm:.0f}" if median_sqm else "0",
        "WasSkipped": was_skipped,
        "URL": search_urls_str,
        "Duration": duration_str
    }
    
    # Update console
    print("\n" + "="*40)
    print("           SCRAPE SUMMARY")
    print("="*40)
    print(f"Timestamp:    {summary_data['Timestamp']}")
    print(f"Scraped:      {summary_data['ScrapedCount']} properties")
    print(f"Total Pages:  {summary_data['TotalPages']}")
    print(f"Median Price: {summary_data['MedianPrice']} EUR")
    print(f"Median SQM:   {summary_data['MedianPriceSQM']} EUR")
    print(f"Skipped:      {summary_data['WasSkipped']}")
    print(f"Duration:     {summary_data['Duration']}")
    if not use_sheets:
        print(f"Report:       reports/{output_file.replace('.csv', '')}_summary.csv")
    else:
        print(f"Report:       Google Sheets (Summary in A:B)")
    print("="*40)

    # Save everything to store
    # For Google Sheets, we pass summary_data for the A:B integration
    if use_sheets:
        store.save(scraped, today, summary_data=summary_data, median_sqm=median_sqm)
    else:
        store.save(scraped, today, median_sqm=median_sqm)
        
    print(f"\n✓ Saved successfully. Captured {len(scraped)} listings.")

if __name__ == "__main__":
    main()
