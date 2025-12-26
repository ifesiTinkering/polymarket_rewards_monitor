#!/usr/bin/env python3
"""
Polymarket Markets Dashboard

Dual-process architecture:
1. Gamma API fetcher - gets all markets with event info
2. Playwright rewards scraper - gets slugs of markets in rewards program

Features:
- Auto-refresh every 5 minutes
- Cached data for instant display during refresh
- Rewards star indicator for markets in rewards program
- Event labels for each market
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
    """Manages market data from Gamma API and rewards scraper."""

    def __init__(self):
        # Main market data
        self.markets = []
        self.cached_markets = []  # Previous data for instant display
        self.last_updated = None

        # Rewards slugs set
        self.rewards_slugs = set()

        # Status flags
        self.is_fetching_markets = False
        self.is_fetching_rewards = False
        self.fetch_progress = {"markets": 0, "rewards": 0, "status": "idle"}

        # Auto-refresh timer
        self.refresh_timer = None
        self.refresh_interval = 300  # 5 minutes

    def start_auto_refresh(self):
        """Start the auto-refresh timer."""
        self.cancel_auto_refresh()
        self.refresh_timer = threading.Timer(self.refresh_interval, self._auto_refresh)
        self.refresh_timer.daemon = True
        self.refresh_timer.start()
        print(f"Auto-refresh scheduled in {self.refresh_interval} seconds")

    def cancel_auto_refresh(self):
        """Cancel any pending auto-refresh."""
        if self.refresh_timer:
            self.refresh_timer.cancel()
            self.refresh_timer = None

    def _auto_refresh(self):
        """Called by timer to trigger refresh."""
        print("Auto-refresh triggered")
        self.start_full_refresh()

    def start_full_refresh(self):
        """Start both fetch processes in parallel."""
        if self.is_fetching_markets or self.is_fetching_rewards:
            print("Refresh already in progress")
            return

        # Cache current data for instant display
        if self.markets:
            self.cached_markets = self.markets.copy()

        # Reset timer
        self.start_auto_refresh()

        # Start both processes
        self.fetch_progress = {"markets": 0, "rewards": 0, "status": "fetching"}

        markets_thread = threading.Thread(target=self._fetch_markets_thread)
        rewards_thread = threading.Thread(target=self._fetch_rewards_thread)

        markets_thread.start()
        rewards_thread.start()

        # Start a thread to wait for both and combine
        def wait_and_combine():
            markets_thread.join()
            rewards_thread.join()
            self._combine_data()

        combine_thread = threading.Thread(target=wait_and_combine)
        combine_thread.start()

    def _fetch_markets_thread(self):
        """Thread wrapper for market fetching."""
        self.is_fetching_markets = True
        try:
            self._fetch_all_markets()
        finally:
            self.is_fetching_markets = False

    def _fetch_rewards_thread(self):
        """Thread wrapper for rewards fetching."""
        self.is_fetching_rewards = True
        try:
            asyncio.run(self._fetch_rewards_slugs())
        finally:
            self.is_fetching_rewards = False

    def _fetch_all_markets(self):
        """Fetch all active markets from the Gamma API."""
        all_markets = []
        offset = 0
        limit = 100

        print("Fetching markets from Gamma API...")

        while True:
            self.fetch_progress["markets"] = len(all_markets)

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
                            # Get Yes/No prices from outcomePrices array
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

                            # Skip placeholder markets without valid prices
                            if yes_price is None or no_price is None:
                                continue

                            # Skip markets with less than $10 volume or liquidity
                            volume = market.get("volumeNum", 0) or 0
                            liquidity = market.get("liquidityNum", 0) or 0
                            if volume < 10 or liquidity < 10:
                                continue

                            market_slug = market.get("slug", "")

                            market_data = {
                                "id": market.get("id"),
                                "question": market.get("question", ""),
                                "slug": market_slug,
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
                                "url": f"https://polymarket.com/event/{event_slug}/{market_slug}",
                                "has_rewards": False  # Will be set after combining
                            }

                            all_markets.append(market_data)

                    print(f"  Markets: {len(all_markets)}...")

                    if len(events) < limit:
                        break

                    offset += limit

            except Exception as e:
                print(f"Error fetching markets: {e}")
                break

        self._temp_markets = all_markets
        print(f"Markets fetch complete: {len(all_markets)} markets")

    async def _fetch_rewards_slugs(self):
        """Fetch just the slugs of markets in the rewards program using Playwright."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            print("Playwright not installed, skipping rewards fetch")
            self._temp_rewards_slugs = set()
            return

        rewards_slugs = set()

        print("Fetching rewards slugs via Playwright...")

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                page.set_default_timeout(30000)

                page_num = 1
                max_pages = 50
                first_page_slugs = None

                while page_num <= max_pages:
                    self.fetch_progress["rewards"] = len(rewards_slugs)

                    try:
                        await page.goto(f"https://polymarket.com/rewards?page={page_num}", wait_until="domcontentloaded")
                        await page.wait_for_timeout(1500)

                        # Extract just the slugs from links
                        slugs = await page.evaluate('''() => {
                            const links = document.querySelectorAll('a[href*="/event/"]');
                            const slugs = [];
                            const seen = new Set();

                            links.forEach(link => {
                                const href = link.href || '';
                                const match = href.match(/\\/event\\/([^?]+)/);
                                if (match) {
                                    const fullSlug = match[1];
                                    const parts = fullSlug.split('/');
                                    const marketSlug = parts[parts.length - 1];
                                    if (marketSlug && !seen.has(marketSlug)) {
                                        seen.add(marketSlug);
                                        slugs.push(marketSlug);
                                    }
                                }
                            });

                            return slugs;
                        }''')

                        if page_num == 1:
                            first_page_slugs = set(slugs)
                        elif first_page_slugs and set(slugs) == first_page_slugs:
                            print(f"  Rewards: detected loop at page {page_num}")
                            break

                        if len(slugs) < 80:  # Partial page = last page
                            for s in slugs:
                                rewards_slugs.add(s)
                            print(f"  Rewards: {len(rewards_slugs)} (final page)")
                            break

                        for s in slugs:
                            rewards_slugs.add(s)

                        print(f"  Rewards: {len(rewards_slugs)} slugs...")
                        page_num += 1

                    except Exception as e:
                        print(f"Error on rewards page {page_num}: {e}")
                        break

                await browser.close()

        except Exception as e:
            print(f"Playwright error: {e}")

        self._temp_rewards_slugs = rewards_slugs
        print(f"Rewards fetch complete: {len(rewards_slugs)} slugs")

    def _combine_data(self):
        """Combine market data with rewards indicators."""
        print("Combining data...")

        markets = getattr(self, '_temp_markets', [])
        rewards_slugs = getattr(self, '_temp_rewards_slugs', set())

        # Update rewards slugs
        if rewards_slugs:
            self.rewards_slugs = rewards_slugs

        # Mark markets with rewards
        for market in markets:
            market["has_rewards"] = market["slug"] in self.rewards_slugs

        rewards_count = sum(1 for m in markets if m["has_rewards"])
        print(f"Combined: {len(markets)} markets, {rewards_count} with rewards")

        self.markets = markets
        self.last_updated = datetime.now().isoformat()
        self.fetch_progress = {"markets": len(markets), "rewards": len(self.rewards_slugs), "status": "ready"}

        # Clean up temp data
        if hasattr(self, '_temp_markets'):
            del self._temp_markets
        if hasattr(self, '_temp_rewards_slugs'):
            del self._temp_rewards_slugs


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

            # Return cached data if refresh in progress, otherwise current data
            is_refreshing = monitor.is_fetching_markets or monitor.is_fetching_rewards
            markets_to_send = monitor.cached_markets if (is_refreshing and monitor.cached_markets) else monitor.markets

            data = {
                "markets": markets_to_send,
                "total_count": len(markets_to_send),
                "last_updated": monitor.last_updated,
                "is_refreshing": is_refreshing,
                "progress": monitor.fetch_progress,
                "rewards_count": len(monitor.rewards_slugs)
            }
            self.wfile.write(json.dumps(data).encode())

        elif parsed.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()

            is_refreshing = monitor.is_fetching_markets or monitor.is_fetching_rewards
            data = {
                "is_refreshing": is_refreshing,
                "progress": monitor.fetch_progress,
                "total_count": len(monitor.markets),
                "rewards_count": len(monitor.rewards_slugs)
            }
            self.wfile.write(json.dumps(data).encode())

        elif parsed.path == "/api/refresh":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()

            is_refreshing = monitor.is_fetching_markets or monitor.is_fetching_rewards
            if not is_refreshing:
                thread = threading.Thread(target=monitor.start_full_refresh)
                thread.start()

            self.wfile.write(json.dumps({"status": "started"}).encode())

        else:
            self.send_error(404)

    def log_message(self, format, *args):
        pass


HTML_PAGE = '''<!DOCTYPE html>
<html>
<head>
    <title>Polymarket Markets Dashboard</title>
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
        h1 { font-size: 20px; font-weight: 600; color: #fff; }
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
        .status.refreshing { color: #f59e0b; }
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

        /* Filter bar */
        .filter-bar {
            display: flex;
            align-items: center;
            gap: 16px;
            padding: 12px 24px;
            background: #0d0d0d;
            border-bottom: 1px solid #1a1a1a;
            flex-wrap: wrap;
        }
        .filter-group {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .filter-label { font-size: 13px; color: #888; }
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
        .table-container { overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; }
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

        .col-market { width: 45%; }
        .col-price { width: 10%; text-align: center; }
        .col-volume { width: 12%; text-align: right; }
        .col-liquidity { width: 10%; text-align: right; }
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
        .market-info { flex: 1; min-width: 0; }
        .market-name {
            font-size: 14px;
            line-height: 1.4;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .market-name a { color: #fff; text-decoration: none; }
        .market-name a:hover { text-decoration: underline; }
        .event-tag {
            display: inline-block;
            font-size: 10px;
            font-weight: 500;
            margin-top: 4px;
            padding: 2px 8px;
            border-radius: 10px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 300px;
            cursor: pointer;
            text-decoration: none;
            transition: opacity 0.15s;
        }
        .event-tag:hover {
            opacity: 0.8;
            text-decoration: none;
            text-overflow: ellipsis;
        }
        .col-rewards {
            width: 36px;
            text-align: center;
            padding: 8px 4px !important;
        }
        .rewards-icon {
            width: 20px;
            height: 20px;
            display: inline-block;
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

        .refresh-indicator {
            font-size: 11px;
            color: #f59e0b;
            margin-left: 8px;
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-top">
            <h1>Polymarket Markets Dashboard</h1>
            <div class="header-controls">
                <span id="status" class="status">Loading...</span>
                <span id="refreshIndicator" class="refresh-indicator" style="display:none">Refreshing in background...</span>
                <button id="refreshBtn" class="btn-primary" onclick="refresh()">Refresh</button>
                <input type="text" class="search-box" id="search" placeholder="Search markets..." oninput="applyFilters()">
            </div>
        </div>
        <div class="stats-bar">
            <div>Total: <span id="totalCount">-</span></div>
            <div>Showing: <span id="displayedCount">-</span></div>
            <div>Rewards: <span id="rewardsCount">-</span></div>
            <div>Updated: <span id="lastUpdated">-</span></div>
        </div>
    </div>

    <div class="filter-bar">
        <div class="toggle-container">
            <span class="filter-label">Price threshold</span>
            <div class="toggle" id="thresholdToggle" onclick="toggleThresholdFilter()"></div>
        </div>
        <div class="filter-group">
            <span class="filter-label">Min (cents):</span>
            <input type="number" class="filter-input" id="minPrice" value="90" min="0" max="100" onchange="applyFilters()">
        </div>
        <div class="toggle-container" style="margin-left: 24px;">
            <span class="filter-label">Rewards only</span>
            <div class="toggle" id="rewardsToggle" onclick="toggleRewardsFilter()"></div>
        </div>
    </div>

    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th class="col-rewards"></th>
                    <th class="col-market">Market</th>
                    <th class="col-price sortable" data-sort="yes" onclick="sortBy('yes')">Yes <span class="sort-arrow">^^</span></th>
                    <th class="col-price sortable" data-sort="no" onclick="sortBy('no')">No <span class="sort-arrow">^^</span></th>
                    <th class="col-volume sortable" data-sort="volume" onclick="sortBy('volume')">Volume <span class="sort-arrow">^^</span></th>
                    <th class="col-liquidity sortable" data-sort="liquidity" onclick="sortBy('liquidity')">Liquidity <span class="sort-arrow">^^</span></th>
                    <th class="col-link">Link</th>
                </tr>
            </thead>
            <tbody id="markets">
                <tr><td colspan="7" class="loading">
                    <div class="spinner"></div>
                    <p>Loading markets...</p>
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
        let rewardsFilterEnabled = false;
        let sortField = null;
        let sortDir = 'asc';
        let isRefreshing = false;

        async function fetchMarkets() {
            try {
                const res = await fetch('/api/markets');
                const data = await res.json();

                if (data.markets && data.markets.length > 0) {
                    allMarkets = data.markets;
                }

                document.getElementById('totalCount').textContent = data.total_count || 0;
                document.getElementById('rewardsCount').textContent = data.rewards_count || 0;
                document.getElementById('lastUpdated').textContent = data.last_updated
                    ? new Date(data.last_updated).toLocaleTimeString()
                    : 'Never';

                updateStatus(data.is_refreshing, data.progress);
                applyFilters(false);  // Don't reset page on background polling
            } catch (err) {
                console.error('Error fetching markets:', err);
            }
        }

        function updateStatus(refreshing, progress) {
            const status = document.getElementById('status');
            const btn = document.getElementById('refreshBtn');
            const indicator = document.getElementById('refreshIndicator');

            isRefreshing = refreshing;

            if (refreshing) {
                status.className = 'status refreshing';
                status.textContent = `Fetching... (${progress?.markets || 0} markets)`;
                indicator.style.display = 'inline';
                // Don't disable button - user can still view cached data
            } else {
                status.className = 'status ready';
                status.textContent = 'Ready';
                indicator.style.display = 'none';
            }
        }

        async function refresh() {
            try {
                await fetch('/api/refresh');
                pollStatus();
            } catch (err) {
                console.error('Error starting refresh:', err);
            }
        }

        async function pollStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                updateStatus(data.is_refreshing, data.progress);

                if (data.is_refreshing) {
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

        function toggleRewardsFilter() {
            rewardsFilterEnabled = !rewardsFilterEnabled;
            document.getElementById('rewardsToggle').classList.toggle('active', rewardsFilterEnabled);
            applyFilters();
        }

        function applyFilters(resetPage = true) {
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

                // Rewards filter
                let matchesRewards = true;
                if (rewardsFilterEnabled) {
                    matchesRewards = m.has_rewards === true;
                }

                return matchesSearch && matchesThreshold && matchesRewards;
            });

            if (sortField) {
                doSort();
            }

            if (resetPage) {
                currentPage = 1;
            }
            // Ensure current page is valid after filtering
            const totalPages = Math.ceil(filteredMarkets.length / pageSize) || 1;
            if (currentPage > totalPages) {
                currentPage = totalPages;
            }
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
                sortDir = 'desc';
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
                    case 'yes': aVal = a.yes_price || 0; bVal = b.yes_price || 0; break;
                    case 'no': aVal = a.no_price || 0; bVal = b.no_price || 0; break;
                    case 'volume': aVal = a.volume || 0; bVal = b.volume || 0; break;
                    case 'liquidity': aVal = a.liquidity || 0; bVal = b.liquidity || 0; break;
                    default: return 0;
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
            if (currentPage > 1) { currentPage--; renderMarkets(); }
        }

        function nextPage() {
            const totalPages = Math.ceil(filteredMarkets.length / pageSize);
            if (currentPage < totalPages) { currentPage++; renderMarkets(); }
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
                tbody.innerHTML = '<tr><td colspan="7" class="loading"><div class="spinner"></div><p>Loading markets...</p></td></tr>';
                return;
            }
            if (filteredMarkets.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" class="no-results">No markets match your filters.</td></tr>';
                return;
            }

            const start = (currentPage - 1) * pageSize;
            const pageMarkets = filteredMarkets.slice(start, start + pageSize);

            // USDC-style rewards icon SVG
            const rewardsIcon = '<svg class="rewards-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="12" cy="12" r="11" fill="#2775CA"/><path d="M12 6.5V8M12 16v1.5M9.5 12H8M16 12h-1.5" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/><path d="M14.5 10.5c0-1.1-.9-2-2.5-2s-2.5.9-2.5 2c0 1.1.9 1.5 2.5 2s2.5.9 2.5 2c0 1.1-.9 2-2.5 2s-2.5-.9-2.5-2" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/></svg>';

            tbody.innerHTML = pageMarkets.map(m => {
                const image = m.image || '';

                return `
                <tr>
                    <td class="col-rewards">
                        ${m.has_rewards ? rewardsIcon : ''}
                    </td>
                    <td>
                        <div class="market-cell">
                            ${image ? `<img src="${image}" class="market-img" alt="" loading="lazy">` : '<div class="market-img"></div>'}
                            <div class="market-info">
                                <div class="market-name">
                                    ${m.url ? `<a href="${m.url}" target="_blank">${escapeHtml(m.question || 'Unknown')}</a>` : escapeHtml(m.question || 'Unknown')}
                                </div>
                                ${m.event_title ? (() => {
                                    const colors = getEventColor(m.event_slug);
                                    const eventUrl = m.event_slug ? 'https://polymarket.com/event/' + m.event_slug : '';
                                    return eventUrl
                                        ? '<a href="' + eventUrl + '" target="_blank" class="event-tag" style="background:' + colors.bg + ';color:' + colors.text + '">' + escapeHtml(m.event_title) + '</a>'
                                        : '<span class="event-tag" style="background:' + colors.bg + ';color:' + colors.text + '">' + escapeHtml(m.event_title) + '</span>';
                                })() : ''}
                            </div>
                        </div>
                    </td>
                    <td class="col-price">
                        ${m.yes_price != null ? `<span class="price-yes">${m.yes_price.toFixed(1)}c</span>` : '-'}
                    </td>
                    <td class="col-price">
                        ${m.no_price != null ? `<span class="price-no">${m.no_price.toFixed(1)}c</span>` : '-'}
                    </td>
                    <td class="col-volume">$${formatNumber(m.volume || 0)}</td>
                    <td class="col-liquidity">$${formatNumber(m.liquidity || 0)}</td>
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

        // Event color management - generates consistent colors per event
        const eventColorCache = new Map();
        const usedHues = [];

        function getEventColor(eventSlug) {
            if (!eventSlug) return { bg: '#333', text: '#888' };

            if (eventColorCache.has(eventSlug)) {
                return eventColorCache.get(eventSlug);
            }

            // Generate a hash from the event slug for consistent colors
            let hash = 0;
            for (let i = 0; i < eventSlug.length; i++) {
                hash = ((hash << 5) - hash) + eventSlug.charCodeAt(i);
                hash = hash & hash;
            }

            // Generate hue from hash, trying to space out from used hues
            let hue = Math.abs(hash) % 360;

            // Adjust hue to avoid too-similar colors
            const minDistance = 25;
            for (let attempts = 0; attempts < 12; attempts++) {
                const tooClose = usedHues.some(usedHue => {
                    const diff = Math.abs(usedHue - hue);
                    return Math.min(diff, 360 - diff) < minDistance;
                });
                if (!tooClose) break;
                hue = (hue + 31) % 360; // Golden angle-ish offset
            }

            usedHues.push(hue);
            if (usedHues.length > 50) usedHues.shift(); // Keep cache bounded

            // Create color with good saturation and lightness for dark theme
            const bg = `hsl(${hue}, 45%, 25%)`;
            const text = `hsl(${hue}, 60%, 75%)`;

            const colors = { bg, text };
            eventColorCache.set(eventSlug, colors);
            return colors;
        }

        // Initial load
        fetchMarkets();
        // Poll for updates every 5 seconds
        setInterval(fetchMarkets, 5000);
    </script>
</body>
</html>
'''


def main():
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080

    # Start initial refresh
    print("Starting initial data fetch...")
    monitor.start_full_refresh()

    server = HTTPServer(("", port), RequestHandler)
    print(f"Server running at http://localhost:{port}")
    print("Auto-refresh every 5 minutes")
    print("Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        monitor.cancel_auto_refresh()
        server.shutdown()


if __name__ == "__main__":
    main()
