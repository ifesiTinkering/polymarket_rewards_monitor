# Polymarket Markets Dashboard

A local web dashboard that monitors and displays all markets from Polymarket with price threshold filtering.

## Quick Start

```bash
./start.sh
```

This will:
1. Kill any existing process on port 8080
2. Start the markets dashboard server
3. Open your browser to http://localhost:8080

## Requirements

- Python 3.9+
- No additional dependencies (uses standard library only)

## Architecture

### Overview

The system fetches market data from Polymarket's Gamma API and serves it through a local HTTP server with an embedded web frontend.

```
+-------------------+     +-------------------+     +----------------+
|   Gamma API       |     |  Markets Dashboard|     |    Browser     |
|   (Polymarket)    | --> |  (Python server)  | --> |   Dashboard    |
+-------------------+     +-------------------+     +----------------+
                                 |
                                 v
                           localhost:8080
```

### How It Works

1. **Data Fetching**: When you click "Refresh", the server fetches all active events from the Gamma API
2. **Pagination**: It fetches events in batches of 100 until all are retrieved
3. **Market Extraction**: For each event, it extracts all nested markets with their prices
4. **Price Calculation**: Yes/No prices are extracted from `outcomePrices` array and converted to cents
5. **Serving**: Data is served via JSON API at `/api/markets`
6. **Frontend**: The embedded HTML page displays data in a sortable, filterable table

### API Used

**Gamma API Endpoint**: `https://gamma-api.polymarket.com/events`

Parameters:
- `limit`: Number of events per request (max 100)
- `offset`: Pagination offset
- `active`: Filter for active events
- `closed`: Filter for closed status

Response includes events with nested `markets` array containing:
- `question`: Market question
- `outcomes`: JSON string of outcome names (e.g., `["Yes", "No"]`)
- `outcomePrices`: JSON string of prices (e.g., `["0.75", "0.25"]`)
- `volumeNum`: Total volume
- `liquidityNum`: Current liquidity

### Local API Endpoints

| Endpoint | Description |
|----------|-------------|
| GET / | Serves the HTML dashboard |
| GET /api/markets | Returns all fetched markets as JSON |
| GET /api/status | Returns fetching status and progress |
| GET /api/refresh | Triggers a new data fetch |

### Frontend Features

- **Price threshold filter**: Toggle to show only markets where Yes OR No price is above a threshold (default 90 cents)
- **Configurable threshold**: Set the minimum price in cents
- **Sorting**: Click column headers (Yes, No, Volume, Liquidity) to sort
- **Search**: Filter markets by question or event name
- **Pagination**: Browse through results 100 at a time
- **Auto-refresh**: Data refreshes every 60 seconds

## Files

```
polymarket_rewards_monitor/
  markets_dashboard.py    # Main application (current version)
  start.sh                # Startup script (current version)
  v1_rewards_scraper.py   # Version 1: Playwright-based rewards scraper
  v1_start.sh             # Version 1: Startup script
  README.md               # This file
```

## Version History

### Version 2 (Current) - API-based Dashboard
- Uses Gamma API directly (no browser automation)
- Shows ALL markets, not just rewards markets
- Much faster data fetching
- Price threshold filter for finding markets near resolution
- No external dependencies beyond Python standard library

### Version 1 - Playwright-based Rewards Scraper
- Used Playwright to scrape the /rewards page
- Only showed markets with active rewards programs
- Required Playwright and Chromium installation
- Slower due to browser automation

To run Version 1:
```bash
./v1_start.sh
```

## Use Cases

### Finding Markets Near Resolution
Enable the price threshold filter and set it to 90+ to find markets where either Yes or No is trading above 90 cents - these are markets the crowd believes are likely to resolve soon.

### Market Discovery
Browse all active markets sorted by volume or liquidity to find popular trading opportunities.

### Research
Search for specific topics or events to find related prediction markets.

## Troubleshooting

**Port already in use**
The start.sh script automatically kills any process on port 8080. If issues persist:
```bash
lsof -ti:8080 | xargs kill -9
```

**API errors**
The Gamma API is public and does not require authentication. If you see errors, check your internet connection or try again later.

## API Reference

For more information about the Polymarket API:
- [Polymarket API Docs](https://docs.polymarket.com/)
- [Gamma Markets API](https://docs.polymarket.com/developers/gamma-markets-api/get-markets)
- [Events API](https://docs.polymarket.com/api-reference/events/list-events)
