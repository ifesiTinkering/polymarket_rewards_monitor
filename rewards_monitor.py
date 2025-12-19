#!/usr/bin/env python3
"""
Polymarket Rewards Monitor

Scrapes all Polymarket rewards pages using Playwright and serves data via local web server.
"""

import json
import time
import asyncio
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse
from datetime import datetime
from playwright.async_api import async_playwright


class RewardsMonitor:
    """Scrapes Polymarket rewards pages using Playwright."""

    def __init__(self):
        self.markets = []
        self.last_updated = None
        self.is_scraping = False
        self.scrape_progress = {"current": 0, "total": "?"}

    async def scrape_all_pages(self):
        """Scrape all rewards pages dynamically until we reach the end."""
        self.is_scraping = True
        all_markets = []
        seen_ids = set()
        first_page_first_market = None

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            page.set_default_timeout(60000)

            print("Starting scrape...")

            page_num = 1
            max_pages = 100  # Safety limit

            while page_num <= max_pages:
                self.scrape_progress = {"current": page_num, "total": "?"}
                print(f"Scraping page {page_num}...")

                try:
                    # Navigate to page
                    await page.goto(f"https://polymarket.com/rewards?page={page_num}", wait_until="domcontentloaded")
                    await page.wait_for_timeout(2000)

                    # Extract market data from DOM
                    markets_data = await page.evaluate('''() => {
                        const markets = [];
                        const seen = new Set();

                        // Get markets from DOM links
                        const links = document.querySelectorAll('a[href*="/event/"]');

                        links.forEach(link => {
                            const href = link.href || '';
                            const match = href.match(/\\/event\\/([^?]+)/);
                            const fullSlug = match ? match[1] : '';

                            if (!fullSlug || seen.has(fullSlug)) return;
                            seen.add(fullSlug);

                            // Extract market slug
                            const slugParts = fullSlug.split('/');
                            const marketSlug = slugParts[slugParts.length - 1];

                            // Find the market row/container
                            let container = link;
                            for (let i = 0; i < 10; i++) {
                                const parent = container.parentElement;
                                if (!parent) break;
                                container = parent;
                                const text = container.textContent || '';
                                if (text.includes('¢') && (text.includes('Yes') || text.includes('No'))) break;
                            }

                            // Get image
                            const img = link.querySelector('img') || container.querySelector('img');
                            const imgSrc = img?.src || null;

                            // Get question from link text
                            const linkText = link.textContent || '';
                            let question = linkText;
                            const cutoffs = ['Max Spread', 'Min', 'Total', 'Earnings', 'Price', 'Yes', 'No', '±'];
                            for (const cutoff of cutoffs) {
                                const idx = question.indexOf(cutoff);
                                if (idx > 0) question = question.slice(0, idx);
                            }
                            question = question.trim();

                            // Get data from DOM
                            const containerText = container.textContent || '';

                            // Max Spread from DOM
                            const spreadMatch = containerText.match(/±([0-9]+\\.?[0-9]*)¢/);
                            const maxSpread = spreadMatch ? parseFloat(spreadMatch[1]) : null;

                            // Yes/No prices from DOM
                            const yesMatch = containerText.match(/Yes\\s*([0-9]+\\.?[0-9]*)¢/i);
                            const noMatch = containerText.match(/No\\s*([0-9]+\\.?[0-9]*)¢/i);
                            const yesPrice = yesMatch ? parseFloat(yesMatch[1]) : null;
                            const noPrice = noMatch ? parseFloat(noMatch[1]) : null;

                            if (fullSlug && question && question.length > 5) {
                                markets.push({
                                    market_slug: fullSlug,
                                    question: question,
                                    condition_id: fullSlug,
                                    url: href,
                                    image: imgSrc,
                                    max_spread: maxSpread,
                                    yes_price: yesPrice,
                                    no_price: noPrice
                                });
                            }
                        });

                        return markets;
                    }''')

                    # Store first market from page 1 to detect looping
                    if page_num == 1 and markets_data:
                        first_page_first_market = markets_data[0].get('condition_id')

                    # Check if we've looped back to page 1 (invalid page returns page 1 data)
                    if page_num > 1 and markets_data and first_page_first_market:
                        current_first = markets_data[0].get('condition_id') if markets_data else None
                        if current_first == first_page_first_market:
                            print(f"  Detected loop back to page 1 - stopping")
                            break

                    # Add new markets
                    new_count = 0
                    for market in markets_data:
                        market_id = market.get('condition_id')
                        if market_id and market_id not in seen_ids:
                            seen_ids.add(market_id)
                            all_markets.append(market)
                            new_count += 1

                    print(f"  Found {len(markets_data)} on page, {new_count} new, {len(all_markets)} total")

                    # Check if this is a partial page (last page with data)
                    if len(markets_data) < 90:  # Less than ~100 means last page
                        print(f"  Partial page detected - this is the last page")
                        break

                    page_num += 1

                except Exception as e:
                    print(f"  Error on page {page_num}: {e}")
                    break

            await browser.close()

        self.markets = all_markets
        self.last_updated = datetime.now().isoformat()
        self.is_scraping = False
        self.scrape_progress = {"current": page_num, "total": page_num}

        print(f"Scrape complete: {len(all_markets)} unique markets found across {page_num} pages")
        return all_markets

    def get_data(self):
        """Return current market data."""
        return {
            "markets": self.markets,
            "total_count": len(self.markets),
            "last_updated": self.last_updated,
            "is_scraping": self.is_scraping,
            "progress": self.scrape_progress
        }


# Global monitor instance
monitor = RewardsMonitor()


def run_scrape():
    """Run the async scrape in a new event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(monitor.scrape_all_pages())
    loop.close()


class APIHandler(SimpleHTTPRequestHandler):
    """HTTP request handler with API endpoints."""

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/api/markets':
            self.send_json_response(monitor.get_data())

        elif parsed.path == '/api/refresh':
            if not monitor.is_scraping:
                thread = threading.Thread(target=run_scrape)
                thread.daemon = True
                thread.start()
                self.send_json_response({"status": "started", "message": "Scraping started"})
            else:
                self.send_json_response({"status": "busy", "message": "Already scraping"})

        elif parsed.path == '/api/status':
            self.send_json_response({
                "is_scraping": monitor.is_scraping,
                "total_markets": len(monitor.markets),
                "last_updated": monitor.last_updated,
                "progress": monitor.scrape_progress
            })

        elif parsed.path == '/' or parsed.path == '/index.html':
            self.serve_frontend()

        else:
            super().do_GET()

    def send_json_response(self, data):
        """Send JSON response with CORS headers."""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def serve_frontend(self):
        """Serve the frontend HTML."""
        html = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Polymarket Rewards Monitor</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0a0a;
            color: #e0e0e0;
            min-height: 100vh;
        }
        .header {
            background: #111;
            padding: 16px 24px;
            border-bottom: 1px solid #222;
        }
        .header-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }
        .header h1 {
            font-size: 20px;
            font-weight: 600;
            color: #fff;
        }
        .header-controls {
            display: flex;
            gap: 12px;
            align-items: center;
        }
        .status {
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 500;
            background: #1a1a1a;
        }
        .status.scraping { background: #362600; color: #f59e0b; }
        .status.ready { background: #14291a; color: #22c55e; }
        button {
            padding: 8px 16px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 500;
            transition: all 0.15s;
        }
        .btn-primary { background: #2563eb; color: white; }
        .btn-primary:hover { background: #1d4ed8; }
        .btn-primary:disabled { background: #333; color: #666; cursor: not-allowed; }
        .search-box {
            padding: 8px 12px;
            border: 1px solid #333;
            border-radius: 6px;
            background: #0a0a0a;
            color: #e0e0e0;
            font-size: 13px;
            width: 280px;
        }
        .search-box:focus { outline: none; border-color: #2563eb; }
        .stats-bar {
            display: flex;
            gap: 24px;
            font-size: 13px;
            color: #888;
        }
        .stats-bar span { color: #fff; font-weight: 500; }
        .progress-bar {
            width: 120px;
            height: 4px;
            background: #222;
            border-radius: 2px;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%;
            background: #2563eb;
            transition: width 0.3s;
        }

        /* Table Styles */
        .table-container {
            padding: 0 24px 24px;
            overflow-x: auto;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }
        thead {
            background: #0a0a0a;
        }
        th {
            background: #111;
            padding: 12px 16px;
            text-align: left;
            font-weight: 500;
            color: #888;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 1px solid #222;
            white-space: nowrap;
        }
        td {
            padding: 14px 16px;
            border-bottom: 1px solid #1a1a1a;
            vertical-align: middle;
        }
        tr:hover td { background: #111; }

        .market-cell {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .market-img {
            width: 40px;
            height: 40px;
            border-radius: 8px;
            object-fit: cover;
            flex-shrink: 0;
            background: #222;
        }
        .market-name {
            font-weight: 500;
            color: #fff;
        }
        .market-name a {
            color: inherit;
            text-decoration: none;
        }
        .market-name a:hover { color: #60a5fa; }

        .badge {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 500;
        }
        .badge-reward { background: #14291a; color: #22c55e; }
        .badge-spread { background: #362600; color: #f59e0b; }
        .badge-size { background: #1e1e2e; color: #a78bfa; }

        .col-market { width: 50%; }
        .col-price { width: 12%; text-align: center; }
        .col-spread { width: 12%; text-align: center; }
        .col-link { width: 10%; text-align: center; }

        .price-yes { color: #22c55e; }
        .price-no { color: #ef4444; }

        .view-link {
            color: #60a5fa;
            text-decoration: none;
            font-size: 13px;
        }
        .view-link:hover { text-decoration: underline; }

        .loading, .no-results {
            text-align: center;
            padding: 60px;
            color: #666;
        }
        .spinner {
            width: 32px;
            height: 32px;
            border: 2px solid #222;
            border-top-color: #2563eb;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin: 0 auto 16px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }

        /* Pagination */
        .pagination {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 8px;
            padding: 20px;
            border-top: 1px solid #1a1a1a;
        }
        .pagination button {
            padding: 6px 12px;
            background: #1a1a1a;
            border: 1px solid #333;
            color: #888;
        }
        .pagination button:hover:not(:disabled) { background: #222; color: #fff; }
        .pagination button:disabled { opacity: 0.5; cursor: not-allowed; }
        .pagination .page-info { color: #888; font-size: 13px; }

        /* Toggle switch */
        .toggle-container {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-right: 16px;
        }
        .toggle-label {
            color: #888;
            font-size: 13px;
        }
        .toggle {
            position: relative;
            width: 44px;
            height: 24px;
            background: #333;
            border-radius: 12px;
            cursor: pointer;
            transition: background 0.2s;
        }
        .toggle.active { background: #2563eb; }
        .toggle::after {
            content: '';
            position: absolute;
            top: 3px;
            left: 3px;
            width: 18px;
            height: 18px;
            background: #fff;
            border-radius: 50%;
            transition: transform 0.2s;
        }
        .toggle.active::after { transform: translateX(20px); }

        /* Sortable columns */
        th.sortable { cursor: pointer; user-select: none; }
        th.sortable:hover { color: #fff; }
        th .sort-arrow { margin-left: 4px; opacity: 0.5; font-size: 10px; }
        th.sorted-asc .sort-arrow, th.sorted-desc .sort-arrow { opacity: 1; }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-top">
            <h1>Polymarket Rewards Monitor</h1>
            <div class="header-controls">
                <span id="status" class="status">Loading...</span>
                <div id="progressContainer" style="display:none">
                    <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
                </div>
                <div class="toggle-container">
                    <span class="toggle-label">Near close (&gt;90¢)</span>
                    <div class="toggle" id="nearCloseToggle" onclick="toggleNearClose()"></div>
                </div>
                <button id="refreshBtn" class="btn-primary" onclick="refresh()">Refresh</button>
                <input type="text" class="search-box" id="search" placeholder="Search markets..." oninput="filterMarkets()">
            </div>
        </div>
        <div class="stats-bar">
            <div>Total: <span id="totalCount">-</span></div>
            <div>Showing: <span id="displayedCount">-</span></div>
            <div>Updated: <span id="lastUpdated">-</span></div>
        </div>
    </div>

    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th class="col-market">Market</th>
                    <th class="col-price sortable" data-sort="yes" onclick="sortBy('yes')">Yes <span class="sort-arrow">▲▼</span></th>
                    <th class="col-price sortable" data-sort="no" onclick="sortBy('no')">No <span class="sort-arrow">▲▼</span></th>
                    <th class="col-spread sortable" data-sort="spread" onclick="sortBy('spread')">Spread <span class="sort-arrow">▲▼</span></th>
                    <th class="col-link">Link</th>
                </tr>
            </thead>
            <tbody id="markets">
                <tr><td colspan="5" class="loading">
                    <div class="spinner"></div>
                    <p>Click "Refresh" to fetch data from Polymarket</p>
                </td></tr>
            </tbody>
        </table>
    </div>

    <div class="pagination">
        <button onclick="prevPage()" id="prevBtn" disabled>Previous</button>
        <span class="page-info">Page <span id="currentPage">1</span> of <span id="totalPages">1</span></span>
        <button onclick="nextPage()" id="nextBtn" disabled>Next</button>
    </div>

    <script>
        let allMarkets = [];
        let filteredMarkets = [];
        let currentPage = 1;
        const pageSize = 100;
        let nearCloseFilter = false;
        let sortField = null;
        let sortDir = 'asc';

        async function fetchMarkets() {
            try {
                const res = await fetch('/api/markets');
                const data = await res.json();
                allMarkets = data.markets || [];
                filteredMarkets = [...allMarkets];

                document.getElementById('totalCount').textContent = data.total_count || 0;
                document.getElementById('lastUpdated').textContent = data.last_updated
                    ? new Date(data.last_updated).toLocaleTimeString()
                    : 'Never';

                updateStatus(data.is_scraping, data.progress);
                currentPage = 1;
                renderMarkets();
            } catch (err) {
                console.error('Error fetching markets:', err);
            }
        }

        function updateStatus(isScraping, progress) {
            const status = document.getElementById('status');
            const btn = document.getElementById('refreshBtn');
            const progressContainer = document.getElementById('progressContainer');
            const progressFill = document.getElementById('progressFill');

            if (isScraping) {
                status.className = 'status scraping';
                const pct = progress ? Math.round((progress.current / progress.total) * 100) : 0;
                status.textContent = `Scraping ${progress?.current || 0}/${progress?.total || 33}`;
                btn.disabled = true;
                progressContainer.style.display = 'block';
                progressFill.style.width = pct + '%';
            } else {
                status.className = 'status ready';
                status.textContent = 'Ready';
                btn.disabled = false;
                progressContainer.style.display = 'none';
            }
        }

        async function refresh() {
            try {
                await fetch('/api/refresh');
                updateStatus(true, {current: 0, total: 33});
                pollStatus();
            } catch (err) {
                console.error('Error starting refresh:', err);
            }
        }

        async function pollStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                updateStatus(data.is_scraping, data.progress);

                if (data.is_scraping) {
                    setTimeout(pollStatus, 1000);
                } else {
                    fetchMarkets();
                }
            } catch (err) {
                console.error('Error polling status:', err);
            }
        }

        function filterMarkets() {
            const query = document.getElementById('search').value.toLowerCase();
            filteredMarkets = allMarkets.filter(m => {
                // Text search filter
                const matchesSearch = (m.question || '').toLowerCase().includes(query) ||
                    (m.market_slug || '').toLowerCase().includes(query);

                // Near close filter (>90¢ on either Yes or No)
                const matchesNearClose = !nearCloseFilter ||
                    (m.yes_price && m.yes_price > 90) ||
                    (m.no_price && m.no_price > 90);

                return matchesSearch && matchesNearClose;
            });

            // Apply current sort if any
            if (sortField) {
                applySort();
            }

            currentPage = 1;
            renderMarkets();
        }

        function toggleNearClose() {
            nearCloseFilter = !nearCloseFilter;
            const toggle = document.getElementById('nearCloseToggle');
            toggle.classList.toggle('active', nearCloseFilter);
            filterMarkets();
        }

        function sortBy(field) {
            // If clicking same field, toggle direction; if new field, start with asc
            if (sortField === field) {
                if (sortDir === 'asc') {
                    sortDir = 'desc';
                } else {
                    // Third click resets to default order
                    sortField = null;
                    sortDir = 'asc';
                    filterMarkets();
                    updateSortIndicators();
                    return;
                }
            } else {
                sortField = field;
                sortDir = 'asc';
            }

            applySort();
            updateSortIndicators();
            renderMarkets();
        }

        function applySort() {
            if (!sortField) return;

            filteredMarkets.sort((a, b) => {
                let aVal, bVal;
                switch(sortField) {
                    case 'yes':
                        aVal = a.yes_price || 0;
                        bVal = b.yes_price || 0;
                        break;
                    case 'no':
                        aVal = a.no_price || 0;
                        bVal = b.no_price || 0;
                        break;
                    case 'spread':
                        aVal = a.max_spread || 0;
                        bVal = b.max_spread || 0;
                        break;
                    default:
                        return 0;
                }
                if (aVal < bVal) return sortDir === 'asc' ? -1 : 1;
                if (aVal > bVal) return sortDir === 'asc' ? 1 : -1;
                return 0;
            });
        }

        function updateSortIndicators() {
            // Remove all sort classes
            document.querySelectorAll('th.sortable').forEach(th => {
                th.classList.remove('sorted-asc', 'sorted-desc');
                th.querySelector('.sort-arrow').textContent = '▲▼';
            });

            // Add class to current sorted column
            if (sortField) {
                const th = document.querySelector(`th[data-sort="${sortField}"]`);
                if (th) {
                    th.classList.add(sortDir === 'asc' ? 'sorted-asc' : 'sorted-desc');
                    th.querySelector('.sort-arrow').textContent = sortDir === 'asc' ? '▲' : '▼';
                }
            }
        }

        function prevPage() {
            if (currentPage > 1) {
                currentPage--;
                renderMarkets();
            }
        }

        function nextPage() {
            const totalPages = Math.ceil(filteredMarkets.length / pageSize);
            if (currentPage < totalPages) {
                currentPage++;
                renderMarkets();
            }
        }

        function renderMarkets() {
            const tbody = document.getElementById('markets');
            const totalPages = Math.ceil(filteredMarkets.length / pageSize) || 1;

            document.getElementById('displayedCount').textContent = filteredMarkets.length;
            document.getElementById('currentPage').textContent = currentPage;
            document.getElementById('totalPages').textContent = totalPages;
            document.getElementById('prevBtn').disabled = currentPage <= 1;
            document.getElementById('nextBtn').disabled = currentPage >= totalPages;

            if (filteredMarkets.length === 0 && allMarkets.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" class="no-results">No markets loaded. Click "Refresh" to fetch data.</td></tr>';
                return;
            }
            if (filteredMarkets.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" class="no-results">No markets match your search.</td></tr>';
                return;
            }

            const start = (currentPage - 1) * pageSize;
            const pageMarkets = filteredMarkets.slice(start, start + pageSize);

            tbody.innerHTML = pageMarkets.map(m => {
                const url = m.url || (m.market_slug ? `https://polymarket.com/event/${m.market_slug}` : '');
                const image = m.image || '';

                return `
                <tr>
                    <td>
                        <div class="market-cell">
                            ${image ? `<img src="${image}" class="market-img" alt="" loading="lazy">` : '<div class="market-img"></div>'}
                            <span class="market-name">
                                ${url ? `<a href="${url}" target="_blank">${escapeHtml(m.question || 'Unknown')}</a>` : escapeHtml(m.question || 'Unknown')}
                            </span>
                        </div>
                    </td>
                    <td class="col-price">
                        ${m.yes_price ? `<span class="price-yes">${m.yes_price}¢</span>` : '-'}
                    </td>
                    <td class="col-price">
                        ${m.no_price ? `<span class="price-no">${m.no_price}¢</span>` : '-'}
                    </td>
                    <td class="col-spread">
                        ${m.max_spread ? `±${m.max_spread}¢` : '-'}
                    </td>
                    <td class="col-link">
                        ${url ? `<a href="${url}" target="_blank" class="view-link">View</a>` : '-'}
                    </td>
                </tr>
            `}).join('');
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // Initial load
        fetchMarkets();
        // Auto-refresh every 60 seconds
        setInterval(fetchMarkets, 60000);
    </script>
</body>
</html>'''

        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        pass


def run_server(port=8080):
    """Start the web server."""
    server = HTTPServer(('localhost', port), APIHandler)
    print(f"Server running at http://localhost:{port}")
    print("Press Ctrl+C to stop")
    server.serve_forever()


if __name__ == '__main__':
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_server(port)
