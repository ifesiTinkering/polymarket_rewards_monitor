# Polymarket Rewards Dashboard

A local web dashboard that monitors and displays all markets with active rewards programs from Polymarket.

## Quick Start

```bash
./start.sh
```

This will:
1. Kill any existing process on port 8080
2. Start the rewards monitor server
3. Open your browser to http://localhost:8080

## Requirements

- Python 3.9+
- Playwright (for browser automation)

### Install Dependencies

```bash
pip3 install playwright
playwright install chromium
```

## Architecture

### Overview

The system scrapes the Polymarket rewards page using a headless browser, then serves the data through a local HTTP server with an embedded web frontend.

```
+-------------------+     +------------------+     +----------------+
|   Polymarket      |     |  Rewards Monitor |     |    Browser     |
|   /rewards page   | --> |  (Python server) | --> |   Dashboard    |
+-------------------+     +------------------+     +----------------+
                                |
                                v
                          localhost:8080
```

### Components

**rewards_monitor.py**
- Playwright-based scraper that navigates through all rewards pages
- Extracts market data from the DOM (question, prices, spread, images)
- HTTP server with REST API endpoints
- Embedded HTML/CSS/JS frontend

**start.sh**
- Startup script that handles port cleanup and launches the server

### How It Works

1. **Scraping**: When you click "Refresh", the server launches a headless Chromium browser via Playwright
2. **Pagination**: It scrapes pages starting from page=1, detecting the end by either:
   - Finding a partial page (fewer than ~90 markets)
   - Detecting a loop back to page 1 data
3. **Data Extraction**: For each market, it extracts from the DOM:
   - Market question/title
   - Yes/No prices (in cents)
   - Max spread
   - Market image
   - Link URL
4. **Serving**: Data is served via JSON API at `/api/markets`
5. **Frontend**: The embedded HTML page fetches and displays the data in a sortable, filterable table

### API Endpoints

| Endpoint | Description |
|----------|-------------|
| GET / | Serves the HTML dashboard |
| GET /api/markets | Returns all scraped markets as JSON |
| GET /api/status | Returns scraping status and progress |
| GET /api/refresh | Triggers a new scrape |

### Frontend Features

- **Near close filter**: Toggle to show only markets where Yes or No price is above 90 cents
- **Sorting**: Click column headers (Yes, No, Spread) to sort ascending/descending
- **Search**: Filter markets by name
- **Pagination**: Browse through results 100 at a time
- **Auto-refresh**: Data refreshes every 60 seconds

## Files

```
rewards_dashboard/
  rewards_monitor.py    # Main application (scraper + server + frontend)
  start.sh              # Startup script
  fetch_rewards_markets.py  # Standalone API fetcher (for reference)
  README.md             # This file
```

## Why Playwright?

The Polymarket rewards page uses client-side rendering and pagination. The official rewards API has broken pagination (returns duplicate data). Playwright allows us to:
- Execute JavaScript to render the full page
- Navigate through paginated results as a real browser would
- Extract data from the fully rendered DOM

## Troubleshooting

**Port already in use**
The start.sh script automatically kills any process on port 8080. If issues persist:
```bash
lsof -ti:8080 | xargs kill -9
```

**Scraping takes too long**
Each page takes about 2 seconds to load and scrape. With 30+ pages, a full refresh takes 1-2 minutes.

**Missing data**
Some fields may show "-" if the DOM structure changes or data is not present for that market.

## API Reference

For direct API access (separate from this dashboard), see the Polymarket documentation:
- [Polymarket API Docs](https://docs.polymarket.com/)
- [Gamma Markets API](https://docs.polymarket.com/developers/gamma-markets-api/get-markets)
