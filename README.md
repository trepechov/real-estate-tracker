# Real Estate Tracker 🏘️

A flexible, high-performance Python scraper for `imot.bg`. Designed for daily automation via GitHub Actions or local monitoring. It tracks price changes, listing status (new/sold), and maintains a multi-area historical database.

## ✨ Key Features
- **Smart Tracking**: Detects when listings are sold or removed and tracks "Days on Market."
- **Multiple Areas**: Pass custom search URLs to track disparate neighborhoods.
- **Dual Storage**: Save reports locally to CSV or sync directly with **Google Sheets**.
- **Automated Summary**: Generates a summary report with median prices and market trends.
- **Stealth Mode**: Uses Playwright with stealth plugins to avoid detection.
- **Optimization**: By default, it skips pages where all listings have already been seen (unless `--full` is used).

---

## 🚀 Getting Started

### 1. Installation
Ensure you have Python 3.9+ installed.

```bash
# Clone the repository (if not already done)
git clone https://github.com/trepechov/real-estate-tracker.git
cd real-estate-tracker

# Install dependencies
pip install -r requirements.txt

# Install Playwright browser
playwright install chromium
```

### 2. Local Usage Examples

#### basic Scrape (CSV)
Scrapes the specified URLs and saves them to `reports/iztok.csv`.
```bash
python tracker.py --urls "https://www.imot.bg/obiava-search-link..." --output "iztok"
```

#### Full Scrape
Forces the scraper to visit ALL pages even if historical data exists.
```bash
python tracker.py --urls "https://www.imot.bg/obiava-search-link..." --output "iztok" --full
```

#### Google Sheets Sync
Uploads and merges data directly into a Google Sheet tab named `iztok`.
```bash
# Requires SPREADSHEET_ID and service_account.json setup
python tracker.py --urls "LINK" --output "iztok" --mode sheets
```

### 3. Command Arguments
| Argument | Description | Default |
| :--- | :--- | :--- |
| `--urls` | One or more `imot.bg` search results URLs. | (Required) |
| `--output` | Filename (for CSV) or Tab Name (for Sheets). | `listings.csv` |
| `--mode` | Choice of `csv` or `sheets`. | `csv` |
| `--full` | Skips optimization; scrapes every single page result. | `False` |

---

## 📊 Data & Reports
All output is stored in the `/reports` directory:
- **`{area}.csv`**: The cumulative database of properties for that area.
- **`{area}_summary.csv`**: A historical log of scrape metrics (median price, count, etc.).

### Column Definitions
- `Status`: `new`, `1 week`, `sold`, etc.
- `vsAvg`: Difference between listing PriceSQM and the area median.
- `DaysMarket`: Number of days since the listing was first detected.
- `Broker`: The agency or private seller name.

---

## 🤖 GitHub Actions Automation
The project is pre-configured to run daily at 00:00 UTC. To customize:
1. Edit `.github/workflows/daily_scrape.yml`.
2. Add your areas to the `matrix` strategy.
3. (Optional) Add `SPREADSHEET_ID` and `GSPREAD_SERVICE_ACCOUNT_JSON` to your Repository Secrets for auto-sync.

---

## 🛠 Google Sheets Setup
To use `--mode sheets`:
1. Create a Google Cloud Project and enable the **Google Sheets API**.
2. Create a **Service Account**, download the JSON key, and save it as `secrets/service_account.json`.
3. Create a Google Sheet and share it with your Service Account email.
4. Save the Sheet ID in `secrets/spreadsheet_id.txt` or as an environment variable `SPREADSHEET_ID`.
