# Real Estate Tracker

A flexible Python-based tool to track real estate listings from `imot.bg`. It supports custom areas, multiple search URLs, and automated daily execution via GitHub Actions.

## Features
- **CSV Reports**: Data is stored in standard CSV format for high compatibility.
- **Organized Storage**: All results are saved in the `reports/` folder.
- **Cumulative History**: Maintains property history, status changes (new/sold), and days on market within a single CSV per area.
- **Stealth & Scrolling**: Uses Playwright to simulate real user behavior.

## Local Setup

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Install Playwright Browsers**:
   ```bash
   playwright install chromium
   ```

3. **Run for a Specific Area**:
   ```bash
   python tracker.py --urls "LINK1" "LINK2" --output "my_area.csv"
   ```
   *Note: Files are automatically saved into the `reports/` directory.*

## GitHub Actions

### Daily Scrapes (Scheduled)
The script runs daily at 00:00 UTC using a **Matrix strategy**. Define areas in `.github/workflows/daily_scrape.yml`:
```yaml
matrix:
  area: 
    - name: "krasna_polyana"
      urls: "URL1 URL2"
```

### Manual Scrapes (On-Demand)
Start a scrape for any area manually from the **Actions** tab by providing the URLs and area name.

## Google Sheets Integration (Future)
The project architecture is ready for Google Sheets. The `DataStore` class can be extended to write directly to Sheets using a service account.
