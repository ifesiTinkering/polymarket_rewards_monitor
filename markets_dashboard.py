#!/usr/bin/env python3
"""
Polymarket Markets Monitor

Fetches all markets from Polymarket's Gamma API and serves via local web server.
Allows filtering by token price threshold.
"""

import json
import time
import asyncio
import threading
import urllib.request
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse
from datetime import datetime


class MarketsMonitor:
    """Fetches markets from Polymarket Gamma API."""

    def __init__(self):
        self.markets = []
        self.last_updated = None
        self.is_fetching = False
        self.fetch_progress = {"current": 0, "total": "?"}

    def fetch_all_markets(self):
        """Fetch all active markets from the Gamma API."""
        self.is_fetching = True
        all_markets = []
        offset = 0
        limit = 100

        print("Fetching markets from Gamma API...")

        while True:
            self.fetch_progress = {"current": len(all_markets), "total": "?"}

            params = urllib.parse.urlencode({
                "limit": limit,
                "offset": offset,
                "active": "true",
                "closed": "false"
            })

            url = f"https://gamma-api.polymarket.com/events?{params}"

            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "Accept": "application/json"
                })
                with urllib.request.urlopen(req, timeout=30) as response:
                    events = json.loads(response.read().decode())

                    if not events:
                        break

                    for event in events:
                        event_title = event.get("title", "")
                        event_slug = event.get("slug", "")
                        event_image = event.get("image", "")

                        for market in event.get("markets", []):
                            # Parse outcomes and prices
                            outcomes = json.loads(market.get("outcomes", "[]"))
                            prices = json.loads(market.get("outcomePrices", "[]"))

                            yes_price = None
                            no_price = None

                            if len(prices) >= 2 and len(outcomes) >= 2:
                                for i, outcome in enumerate(outcomes):
                                    price_cents = float(prices[i]) * 100
                                    if outcome == "Yes":
                                        yes_price = round(price_cents, 2)
                                    elif outcome == "No":
                                        no_price = round(price_cents, 2)

                            market_data = {
                                "id": market.get("id"),
                                "question": market.get("question", ""),
                                "slug": market.get("slug", ""),
                                "event_title": event_title,
                                "event_slug": event_slug,
                                "image": market.get("image") or event_image,
                                "yes_price": yes_price,
                                "no_price": no_price,
                                "spread": market.get("spread"),
                                "volume": market.get("volumeNum", 0),
                                "volume_24hr": market.get("volume24hr", 0),
                                "liquidity": market.get("liquidityNum", 0),
                                "end_date": market.get("endDate"),
                                "url": f"https://polymarket.com/event/{event_slug}/{market.get('slug', '')}"
                            }

                            all_markets.append(market_data)

                    print(f"  Fetched {len(all_markets)} markets...")

                    if len(events) < limit:
                        break

                    offset += limit

            except Exception as e:
                print(f"Error fetching markets: {e}")
                break

        self.markets = all_markets
        self.last_updated = datetime.now().isoformat()
        self.is_fetching = False
        self.fetch_progress = {"current": len(all_markets), "total": len(all_markets)}

        print(f"Completed: {len(all_markets)} total markets")

        return all_markets


# Global monitor instance
monitor = MarketsMonitor()


class RequestHandler(SimpleHTTPRequestHandler):
    """HTTP request handler with API endpoints."""

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/" or parsed.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode())

        elif parsed.path == "/api/markets":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            data = {
                "markets": monitor.markets,
                "total_count": len(monitor.markets),
                "last_updated": monitor.last_updated,
                "is_fetching": monitor.is_fetching,
                "progress": monitor.fetch_progress
            }
            self.wfile.write(json.dumps(data).encode())

        elif parsed.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()

            data = {
                "is_fetching": monitor.is_fetching,
                "progress": monitor.fetch_progress,
                "total_count": len(monitor.markets)
            }
            self.wfile.write(json.dumps(data).encode())

        elif parsed.path == "/api/refresh":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()

            if not monitor.is_fetching:
                thread = threading.Thread(target=monitor.fetch_all_markets)
                thread.start()

            self.wfile.write(json.dumps({"status": "started"}).encode())

        else:
            self.send_error(404)

    def log_message(self, format, *args):
        pass  # Suppress logging


HTML_PAGE = '''<!DOCTYPE html>
<html>
<head>
    <title>Polymarket Markets Monitor</title>
    <meta charset="UTF-8">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #0a0a0a;
            color: #e0e0e0;
            min-height: 100vh;
        }
        .header {
            background: #111;
            border-bottom: 1px solid #222;
            padding: 16px 24px;
        }
        .header-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
        }
        h1 {
            font-size: 20px;
            font-weight: 600;
            color: #fff;
        }
        .header-controls {
            display: flex;
            align-items: center;
            gap: 12px;
            flex-wrap: wrap;
        }
        .status {
            font-size: 12px;
            padding: 4px 10px;
            border-radius: 4px;
            background: #1a1a1a;
        }
        .status.ready { color: #22c55e; }
        .status.fetching { color: #f59e0b; }
        .btn-primary {
            background: #2563eb;
            color: #fff;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 500;
        }
        .btn-primary:hover { background: #1d4ed8; }
        .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
        .search-box {
            background: #1a1a1a;
            border: 1px solid #333;
            color: #fff;
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 13px;
            width: 200px;
        }
        .search-box:focus { outline: none; border-color: #2563eb; }
        .stats-bar {
            display: flex;
            gap: 24px;
            padding: 12px 24px;
            background: #0d0d0d;
            border-bottom: 1px solid #1a1a1a;
            font-size: 13px;
            color: #888;
        }
        .progress-bar {
            width: 100px;
            height: 6px;
            background: #222;
            border-radius: 3px;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%;
            background: #2563eb;
            transition: width 0.3s;
        }

        /* Filter controls */
        .filter-bar {
            display: flex;
            align-items: center;
            gap: 16px;
            padding: 12px 24px;
            background: #0d0d0d;
            border-bottom: 1px solid #1a1a1a;
        }
        .filter-group {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .filter-label {
            font-size: 13px;
            color: #888;
        }
        .filter-input {
            background: #1a1a1a;
            border: 1px solid #333;
            color: #fff;
            padding: 6px 10px;
            border-radius: 4px;
            font-size: 13px;
            width: 70px;
        }
        .toggle-container {
            display: flex;
            align-items: center;
            gap: 8px;
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

        /* Table */
        .table-container {
            overflow-x: auto;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th {
            position: sticky;
            top: 0;
            background: #111;
            padding: 12px 16px;
            text-align: left;
            font-size: 11px;
            font-weight: 600;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 1px solid #222;
            white-space: nowrap;
        }
        th.sortable { cursor: pointer; user-select: none; }
        th.sortable:hover { color: #fff; }
        th .sort-arrow { margin-left: 4px; opacity: 0.5; font-size: 10px; }
        th.sorted-asc .sort-arrow, th.sorted-desc .sort-arrow { opacity: 1; }
        td {
            padding: 14px 16px;
            border-bottom: 1px solid #1a1a1a;
            vertical-align: middle;
        }
        tr:hover td { background: #111; }

        .col-market { width: 40%; }
        .col-price { width: 10%; text-align: center; }
        .col-volume { width: 12%; text-align: right; }
        .col-liquidity { width: 12%; text-align: right; }
        .col-link { width: 8%; text-align: center; }

        .market-cell {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .market-img {
            width: 40px;
            height: 40px;
            border-radius: 6px;
            object-fit: cover;
            background: #222;
            flex-shrink: 0;
        }
        .market-name {
            font-size: 14px;
            line-height: 1.4;
        }
        .market-name a {
            color: #fff;
            text-decoration: none;
        }
        .market-name a:hover { text-decoration: underline; }
        .event-name {
            font-size: 11px;
            color: #666;
            margin-top: 2px;
        }

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
            padding: 48px 24px;
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
            border-radius: 4px;
            cursor: pointer;
        }
        .pagination button:hover:not(:disabled) { background: #222; color: #fff; }
        .pagination button:disabled { opacity: 0.5; cursor: not-allowed; }
        .pagination .page-info { color: #888; font-size: 13px; }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-top">
            <h1>Polymarket Markets Monitor</h1>
            <div class="header-controls">
                <span id="status" class="status">Loading...</span>
                <div id="progressContainer" style="display:none">
                    <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
                </div>
                <button id="refreshBtn" class="btn-primary" onclick="refresh()">Refresh</button>
                <input type="text" class="search-box" id="search" placeholder="Search markets..." oninput="applyFilters()">
            </div>
        </div>
        <div class="stats-bar">
            <div>Total: <span id="totalCount">-</span></div>
            <div>Showing: <span id="displayedCount">-</span></div>
            <div>Updated: <span id="lastUpdated">-</span></div>
        </div>
    </div>

    <div class="filter-bar">
        <div class="toggle-container">
            <span class="filter-label">Price threshold filter</span>
            <div class="toggle" id="thresholdToggle" onclick="toggleThresholdFilter()"></div>
        </div>
        <div class="filter-group">
            <span class="filter-label">Min price (cents):</span>
            <input type="number" class="filter-input" id="minPrice" value="90" min="0" max="100" onchange="applyFilters()">
        </div>
        <span class="filter-label" style="color: #666;">Shows markets where Yes OR No is above threshold</span>
    </div>

    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th class="col-market">Market</th>
                    <th class="col-price sortable" data-sort="yes" onclick="sortBy('yes')">Yes <span class="sort-arrow">^^</span></th>
                    <th class="col-price sortable" data-sort="no" onclick="sortBy('no')">No <span class="sort-arrow">^^</span></th>
                    <th class="col-volume sortable" data-sort="volume" onclick="sortBy('volume')">Volume <span class="sort-arrow">^^</span></th>
                    <th class="col-liquidity sortable" data-sort="liquidity" onclick="sortBy('liquidity')">Liquidity <span class="sort-arrow">^^</span></th>
                    <th class="col-link">Link</th>
                </tr>
            </thead>
            <tbody id="markets">
                <tr><td colspan="6" class="loading">
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
        let thresholdFilterEnabled = false;
        let sortField = null;
        let sortDir = 'asc';

        async function fetchMarkets() {
            try {
                const res = await fetch('/api/markets');
                const data = await res.json();
                allMarkets = data.markets || [];

                document.getElementById('totalCount').textContent = data.total_count || 0;
                document.getElementById('lastUpdated').textContent = data.last_updated
                    ? new Date(data.last_updated).toLocaleTimeString()
                    : 'Never';

                updateStatus(data.is_fetching, data.progress);
                applyFilters();
            } catch (err) {
                console.error('Error fetching markets:', err);
            }
        }

        function updateStatus(isFetching, progress) {
            const status = document.getElementById('status');
            const btn = document.getElementById('refreshBtn');
            const progressContainer = document.getElementById('progressContainer');
            const progressFill = document.getElementById('progressFill');

            if (isFetching) {
                status.className = 'status fetching';
                status.textContent = `Fetching ${progress?.current || 0} markets...`;
                btn.disabled = true;
                progressContainer.style.display = 'block';
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
                updateStatus(true, {current: 0});
                pollStatus();
            } catch (err) {
                console.error('Error starting refresh:', err);
            }
        }

        async function pollStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                updateStatus(data.is_fetching, data.progress);

                if (data.is_fetching) {
                    setTimeout(pollStatus, 1000);
                } else {
                    fetchMarkets();
                }
            } catch (err) {
                console.error('Error polling status:', err);
            }
        }

        function toggleThresholdFilter() {
            thresholdFilterEnabled = !thresholdFilterEnabled;
            document.getElementById('thresholdToggle').classList.toggle('active', thresholdFilterEnabled);
            applyFilters();
        }

        function applyFilters() {
            const query = document.getElementById('search').value.toLowerCase();
            const minPrice = parseFloat(document.getElementById('minPrice').value) || 0;

            filteredMarkets = allMarkets.filter(m => {
                // Text search
                const matchesSearch = (m.question || '').toLowerCase().includes(query) ||
                    (m.event_title || '').toLowerCase().includes(query);

                // Price threshold filter
                let matchesThreshold = true;
                if (thresholdFilterEnabled) {
                    const yesAbove = m.yes_price && m.yes_price >= minPrice;
                    const noAbove = m.no_price && m.no_price >= minPrice;
                    matchesThreshold = yesAbove || noAbove;
                }

                return matchesSearch && matchesThreshold;
            });

            // Apply sort if any
            if (sortField) {
                doSort();
            }

            currentPage = 1;
            renderMarkets();
        }

        function sortBy(field) {
            if (sortField === field) {
                if (sortDir === 'asc') {
                    sortDir = 'desc';
                } else {
                    sortField = null;
                    sortDir = 'asc';
                    applyFilters();
                    updateSortIndicators();
                    return;
                }
            } else {
                sortField = field;
                sortDir = 'desc'; // Default to descending for numbers
            }

            doSort();
            updateSortIndicators();
            renderMarkets();
        }

        function doSort() {
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
                    case 'volume':
                        aVal = a.volume || 0;
                        bVal = b.volume || 0;
                        break;
                    case 'liquidity':
                        aVal = a.liquidity || 0;
                        bVal = b.liquidity || 0;
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
            document.querySelectorAll('th.sortable').forEach(th => {
                th.classList.remove('sorted-asc', 'sorted-desc');
                th.querySelector('.sort-arrow').textContent = '^^';
            });

            if (sortField) {
                const th = document.querySelector(`th[data-sort="${sortField}"]`);
                if (th) {
                    th.classList.add(sortDir === 'asc' ? 'sorted-asc' : 'sorted-desc');
                    th.querySelector('.sort-arrow').textContent = sortDir === 'asc' ? '^' : 'v';
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

        function formatNumber(num) {
            if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
            if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
            return num.toFixed(0);
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
                tbody.innerHTML = '<tr><td colspan="6" class="no-results">No markets loaded. Click "Refresh" to fetch data.</td></tr>';
                return;
            }
            if (filteredMarkets.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" class="no-results">No markets match your filters.</td></tr>';
                return;
            }

            const start = (currentPage - 1) * pageSize;
            const pageMarkets = filteredMarkets.slice(start, start + pageSize);

            tbody.innerHTML = pageMarkets.map(m => {
                const image = m.image || '';

                return `
                <tr>
                    <td>
                        <div class="market-cell">
                            ${image ? `<img src="${image}" class="market-img" alt="" loading="lazy">` : '<div class="market-img"></div>'}
                            <div>
                                <div class="market-name">
                                    ${m.url ? `<a href="${m.url}" target="_blank">${escapeHtml(m.question || 'Unknown')}</a>` : escapeHtml(m.question || 'Unknown')}
                                </div>
                                <div class="event-name">${escapeHtml(m.event_title || '')}</div>
                            </div>
                        </div>
                    </td>
                    <td class="col-price">
                        ${m.yes_price != null ? `<span class="price-yes">${m.yes_price.toFixed(1)}c</span>` : '-'}
                    </td>
                    <td class="col-price">
                        ${m.no_price != null ? `<span class="price-no">${m.no_price.toFixed(1)}c</span>` : '-'}
                    </td>
                    <td class="col-volume">
                        $${formatNumber(m.volume || 0)}
                    </td>
                    <td class="col-liquidity">
                        $${formatNumber(m.liquidity || 0)}
                    </td>
                    <td class="col-link">
                        ${m.url ? `<a href="${m.url}" target="_blank" class="view-link">View</a>` : '-'}
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
</html>
'''


def main():
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080

    server = HTTPServer(("", port), RequestHandler)
    print(f"Server running at http://localhost:{port}")
    print("Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
