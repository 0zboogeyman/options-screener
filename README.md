**English** | [简体中文](README_zh.md)

# Option Scanner

> A multi-strategy options scanner built on real Deribit market data — vertical spreads, cash-secured puts, covered calls, iron condors, strangles, and calendar spreads, with a volatility surface fitted from raw SVI and risk metrics derived from the implied risk-neutral density.

## Table of Contents

- [Project Overview](#project-overview)
- [Core Features](#core-features)
- [Algorithm Highlights](#algorithm-highlights)
- [Directory Structure](#directory-structure)
- [Installation](#installation)
- [Usage Guide](#usage-guide)
- [Configuration](#configuration)
- [API Reference](#api-reference)
- [Frequently Asked Questions](#frequently-asked-questions)
- [Disclaimer](#disclaimer)

## Project Overview

Option Scanner automatically pulls daily BTC/ETH options data from the [Deribit](https://www.deribit.com) public API, persists it to local parquet partitions, fits a per-expiry volatility smile with the raw SVI model, and derives win rates / tail risk from the Breeden-Litzenberger implied risk-neutral density (RND). It scans multiple classic strategies, scores them with a transparent 0–100 composite score, and serves everything through a single-port web UI.

### Architecture

- **Backend** — Python FastAPI (single container, exposes both the API and the frontend static export on one port).
- **Frontend** — Next.js static export (`output: export`), trilingual (English / Simplified Chinese / Traditional Chinese), served by FastAPI itself — no Node.js runtime needed in production.
- **Data pipeline** — An in-container `etl-scheduler` process runs the ETL automatically (default 08:05 UTC = 16:05 Taipei/Beijing time), so **no crontab is required**.
- **One container** — everything (web + API + scheduler) is managed by supervisord inside a single Docker container.

## Core Features

| Feature          | Endpoint                                   | Description                                                                                                             |
| ---------------- | ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| Expiry Scan      | `POST /api/spread/scan`                    | Vertical spreads (CALL/PUT × DEBIT/CREDIT) grouped by expiry; unified reward/risk odds (DEBIT = width ÷ net debit, CREDIT = net credit ÷ width), liquidity-penalized ranking, dual `mid`/`conservative` pricing, USD net max profit/loss |
| Opinion          | `POST /api/spread/opinion`                 | Filter optimal spreads for a target price and directional view (`up`/`down`/`not_up`/`not_down`); strike order never affects break-even/PoP             |
| Cash-Secured Put | `POST /api/strategy/csp`                   | Collect premium; if price drops, buy the coin at a discount. Delta, assignment probability, APR, composite score          |
| Covered Call     | `POST /api/strategy/cc`                    | Collect premium; if price rises, sell the coin at a profit. Upside %, APR, composite score                                |
| Iron Condor      | `POST /api/strategy/iron-condor`           | Short OTM put spread + short OTM call spread; legs placed by SVI-delta, win rate from RND, margin estimated              |
| Strangle         | `POST /api/strategy/strangle`              | OTM put + OTM call, both long-vol and short-vol sides; tail risk as RND 5% expected-shortfall estimate                   |
| Calendar Spread  | `POST /api/strategy/calendar`              | Sell near-term + buy far-term at the same strike; SVI term-structure slope + theta capture + numerical profit zone        |
| Volatility Panel | `GET /api/meta/vol`                        | DVOL, IVP/IVR, SVI term structure (ATM IV / RR25 skew / BF25), 90-day DVOL trend                                         |
| Metadata         | `GET /api/meta/dates` `GET /api/meta/asof` | Available dates, snapshot info (spot price, DVOL index)                                                                  |
| Manual ETL       | `POST /api/etl/run` `GET /api/etl/status`  | One-click data refresh (requires `ADMIN_TOKEN`); the frontend "Refresh Data" button only appears with a valid token      |
| Health Check     | `GET /api/health`                          | Service status, latest data date, stale-data alert                                                                       |
| Geolocation      | `GET /api/geo`                             | IP-based language auto-detection (`zh-CN` / `zh-TW` / `en`) on first visit                                                |
| Telegram Push    | (scheduled)                                | After each scheduled ETL: daily top-strategy picks, DVOL day-over-day jump (>20%) alerts, ETL failure alerts              |

## Algorithm Highlights

### 1. SVI Volatility Surface

Each expiry is fitted independently with the 5-parameter raw SVI model:

```
w(k) = a + b·(ρ·(k−m) + √((k−m)² + σ²))
```

sqrt-OI weighting, 3 multi-start initializations, butterfly no-arbitrage validation, and graceful fallback to `mark_iv` when the fit fails. Results are persisted daily to `vol/history.parquet`.

### 2. RND — Implied Risk-Neutral Density

From the fitted surface, the Breeden-Litzenberger density is built:

```
pdf(k) = g(k)·n(d2(k)) / √w(k)
```

replacing Monte Carlo for win probability (PoP), VaR/CVaR and tail-risk estimates. It captures the volatility smile's fat tails, which a plain lognormal (BS) model systematically underestimates. The density grid auto-expands with ATM total variance (`±max(3, 4·√w_atm+1)`), so high-volatility / long-dated slices never truncate tail risk (ES / tail probabilities stay accurate).

### 3. IVP / IVR

DVOL historical data is backfilled (`backfill_dvol.py`, daily resolution with continuation paging), a 30-day fixed-tenor ATM IV is interpolated in total-variance space, and IV Percentile / IV Rank are computed. IVR returns `null` during the cold-start period (< 30 days of history) instead of a misleading value.

### 4. Vectorized Black-Scholes Greeks

`delta_call_vec` / `vega_vec` / `theta_vec` / `gamma_vec`, plus `prob_between` / `strike_from_delta_vec` — fully numpy-vectorized so a single scan completes in milliseconds.

### 5. Deribit Margin Estimation

Standard-account formulas: naked short Call IM = `max(0.15 − OTM%, 0.10) + mark`; Put IM = `max(same, MM_put)`; MM Call = `0.075 + mark`; Put MM = `max(0.075, 0.075·mark) + mark` (coin units). Portfolio-level functions output both coin and USD fields (marked `estimate`).

### 6. Dual Pricing Modes

- `mid` — theoretical mid-price.
- `conservative` — executable price (buy legs pay ask, sell legs receive bid), closer to actual execution cost.

### 7. Engineering Optimizations

- `max_gap_steps` bounds pair enumeration from `O(n²)` to `O(n·g)`.
- `direction='both'` combines up/down scans into a single request.
- In-process chain cache keyed by `(date, base)` with `asof_ts` versioning; SVI surface / DVOL caches keyed by file mtime.
- Anchored-interval composite scores (fixed reference ranges, not dynamic min-max) filter out candidates below 45 — scores stay comparable across scans and candidates.
- Vertical-spread metrics use a single USD net convention and one reward/risk odds definition, regardless of strike order.
- Parquet appends are guarded by cross-process file locks; partitions older than 30 days are cleaned automatically.

## Directory Structure

```
option-scanner/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI routes (scan, strategy, ETL, geo, meta)
│   │   ├── core/         # settings, logging, rate limiting
│   │   └── services/     # bs, svi, rnd, margin, scanner, single_leg, multi_leg,
│   │                     # loader, vol_history, notify, preprocessing
│   ├── scripts/          # etl_daily.py, etl_scheduler.py, backfill_dvol.py, cleanup_old_data.py
│   └── tests/            # pytest suite (82 tests)
├── frontend/             # Next.js static-export UI (trilingual)
├── ops/                  # deploy helpers, Caddy example
├── Dockerfile.combined   # single-container image (frontend build + backend venv)
├── docker-compose.yml
├── supervisord.conf      # runs uvicorn + etl-scheduler
└── Makefile
```

## Installation

### Prerequisites

- Docker 20+ and Docker Compose v2 (recommended path)
- Node.js 20+ and Python 3.11+ (local development path)
- The server must be able to reach the Deribit API (`www.deribit.com`)

### Option A — Docker Compose (Recommended)

```bash
# 1. Clone
git clone https://github.com/0zboogeyman/option-scanner.git
cd option-scanner

# 2. First deploy: copy the env template (all variables have built-in defaults)
cp .env.example .env

# 3. Build and start
docker compose up -d --build
```

> The service starts even without a `.env` file — `env_file` is `required: false` and the container falls back to built-in source defaults.

On first startup with an empty data directory, the container automatically runs one ETL cycle (~1–3 minutes). Scanning becomes available once it completes. Afterwards, daily data refresh is handled by the in-container scheduler.

**Access**: `http://YOUR_SERVER_IP:3116` (root path). Frontend and API share the same port (container port 3000).

### Option B — Local Development

The frontend is a static export served by FastAPI itself, so the simplest local setup is: build the frontend once, then run the backend (which auto-hosts the static export).

```bash
# 1. Frontend: install and build the static export (out/)
cd frontend
npm ci
npm run build

# 2. Backend: venv + deps
cd ../backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Optional: pre-warm DVOL history so IVP/IVR work immediately
python scripts/backfill_dvol.py --days 365

# 4. Run the backend — it serves both the pages and the API on one port
python -m uvicorn app.main:app --reload --port 8000
# Open http://localhost:8000
```

> For a one-off manual ETL run in development: `python scripts/etl_daily.py`.
>
> Want hot-reload frontend development? Add a `rewrites()` block to `frontend/next.config.js` proxying `/api` to the backend (e.g. `http://localhost:8000`), then run `npm run dev` — see FAQ Q10.

## Usage Guide

### Using the Web UI

1. Open `http://YOUR_SERVER_IP:3116`.
2. Choose BTC or ETH, adjust the filters, and click **Scan**.
3. Switch language with the top-right language selector (English / 简体中文 / 繁體中文).

### Updating Data Manually

1. Set `ADMIN_TOKEN` in `.env` (see [Configuration](#configuration)).
2. Visit `https://your-domain/?admin=YOUR_TOKEN` once — the token is saved to localStorage and removed from the URL.
3. The **Refresh Data** button appears at the top of the page. Visitors without the token cannot see the button, and direct API calls return `401`.

### Telegram Push

After each scheduled ETL, the daily strategy picks are pushed. Alerts are also sent when DVOL jumps >20% day-over-day or when an ETL run fails. Configure `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` in `.env` to enable. Manual ETL triggers do not push (avoids same-day duplicates).

### Make Commands

| Command              | Description                                        |
| -------------------- | -------------------------------------------------- |
| `make up`            | Build and start                                    |
| `make down`          | Stop containers                                    |
| `make restart`       | Restart containers                                 |
| `make logs`          | Tail live logs                                     |
| `make status`        | Container status + port health check               |
| `make etl`           | Manually trigger one ETL run                       |
| `make backup`        | Backup the data volume                             |
| `make clean`         | Stop and remove containers and volumes             |

### Backup & Restore

All data lives in the Docker named volume `option-scanner-data`:

```bash
bash ops/etl_docker.sh backup                                # Backup
bash ops/etl_docker.sh restore backups/data-XXXXXXXX.tar.gz  # Restore
```

## Configuration

All variables have source-code defaults; leaving them blank uses the default. Edit `.env` and restart: `docker compose up -d`.

| Variable                | Description                                                                          | Default           |
| ----------------------- | ------------------------------------------------------------------------------------ | ----------------- |
| `PUBLIC_PORT`           | External port (set to `127.0.0.1:3116` when behind a reverse proxy)                  | `3116`            |
| `CORS_ORIGINS`          | CORS allowlist as a JSON array; never use `["*"]`                                    | `[]`              |
| `LOG_LEVEL`             | `DEBUG` / `INFO` / `WARNING` / `ERROR` (never use `DEBUG` in production)             | `INFO`            |
| `ETL_SCHEDULE`          | ETL schedule (UTC): `08:05` = Taipei 16:05, `@every 6h`, `@every 30m`, or `off`       | `08:05`           |
| `ETL_BASES`             | Bases fetched by ETL                                                                 | `["BTC","ETH"]`   |
| `RATE_LIMIT_PER_MINUTE` | Per-IP rate limit for scan endpoints (don't go below 20)                              | `30/minute`       |
| `API_DOCS_ENABLED`      | Expose `/docs` `/redoc` `/openapi.json` (keep `false` in production)                  | `false`           |
| `DATA_STALE_HOURS`      | Stale-data alert threshold (hours)                                                   | `25`              |
| `ADMIN_TOKEN`           | Manual-ETL token, verified via `X-Admin-Token` header (required on public networks)   | empty (allow all) |
| `TELEGRAM_BOT_TOKEN`    | Telegram bot token (enables push when combined with `chat_id`)                       | empty (disabled)  |
| `TELEGRAM_CHAT_ID`      | Telegram recipient/group chat id                                                      | empty (disabled)  |
| `TELEGRAM_LANG`         | Telegram push language: `zh-CN` / `zh-TW` / `en`                                     | `zh-CN`           |
| `GEO_ENABLED`           | IP geolocation switch (`false` returns the default language directly)                 | `true`            |
| `GEO_DEFAULT_LANG`      | Default language when geolocation fails                                              | `zh-CN`           |

### Production Deployment Checklist

1. **Always set `ADMIN_TOKEN`** on public networks — without it, any visitor can trigger ETL and burn Deribit API quota.
2. **Keep `API_DOCS_ENABLED=false`** and `LOG_LEVEL=INFO` (or higher) in production.
3. **Optional**: configure Telegram push.
4. **Optional**: bind to a domain via reverse proxy (see below) and set `PUBLIC_PORT=127.0.0.1:3116` to block direct IP:port access.

### Domain Binding & Reverse Proxy

A Caddy example config is provided at `ops/Caddyfile.example`. Caddy auto-provisions and renews Let's Encrypt certificates.

```bash
# 1. Bind the container to loopback only
#    .env
PUBLIC_PORT=127.0.0.1:3116

# 2. Configure Caddy
cp ops/Caddyfile.example /etc/caddy/Caddyfile
vi /etc/caddy/Caddyfile          # replace yourdomain.com
systemctl reload caddy

# 3. Restart the container to apply the new port
docker compose up -d
```

## API Reference

| Method | Endpoint                        | Description                                  |
| ------ | ------------------------------- | -------------------------------------------- |
| POST   | `/api/spread/scan`              | Vertical spread buckets by expiry            |
| POST   | `/api/spread/opinion`           | Target-price / directional spreads           |
| POST   | `/api/strategy/csp`             | Cash-secured put scan                        |
| POST   | `/api/strategy/cc`              | Covered call scan                            |
| POST   | `/api/strategy/iron-condor`     | Iron condor scan                             |
| POST   | `/api/strategy/strangle`        | Strangle scan (long/short)                   |
| POST   | `/api/strategy/calendar`        | Calendar spread scan                         |
| GET    | `/api/meta/vol`                 | Volatility panel data                        |
| GET    | `/api/meta/dates`               | Available dates                              |
| GET    | `/api/meta/asof`                | Snapshot info for a date/base                |
| GET    | `/api/expiries`                 | Expiries for a date/base                     |
| POST   | `/api/etl/run`                  | Trigger a manual ETL (needs `ADMIN_TOKEN`)   |
| GET    | `/api/etl/status`               | ETL running status                           |
| GET    | `/api/geo`                      | IP-based language detection                  |
| GET    | `/api/health`                   | Health check                                 |

Enable interactive docs with `API_DOCS_ENABLED=true` (`/docs`).

**API conventions**: `/api/meta/vol` term-structure IVs (`atm_iv` / `rr25` / `bf25`) are decimals (`0.45` = 45%); vertical-spread endpoints return `max_profit` / `max_loss` in USD net terms; inverted `min`/`max` parameter pairs (e.g. `dte_min` > `dte_max`) are rejected with `422`.

## Frequently Asked Questions

### Q1: Why is the data old / marked as stale?
The scheduled ETL runs once a day at 08:05 UTC (16:05 Taipei time), right after Deribit's daily settlement. If the health endpoint reports stale data, check the scheduler logs:
```bash
docker compose logs app | grep etl
```
You can also click **Refresh Data** (requires `ADMIN_TOKEN`) to trigger a run immediately.

### Q2: How do I change the ETL time or disable scheduling?
Edit `ETL_SCHEDULE` in `.env` and restart:
- `08:05` — daily at 08:05 UTC (default)
- `@every 6h` — every 6 hours
- `@every 30m` — every 30 minutes
- `off` — disabled (only the first-startup ETL runs)

### Q3: Why does IVR show "—"?
IVR needs at least 30 days of DVOL history to be statistically meaningful. During the cold-start period the value is intentionally `null` (displayed as "—") instead of a misleading 0%. Once enough history accumulates, IVR appears automatically.

### Q4: I get HTTP 429 (rate limited) during normal use?
The default limit is 30 requests per minute per IP, which already accommodates normal frontend interactions. If you still hit it, raise `RATE_LIMIT_PER_MINUTE` in `.env` (don't go below 20, which would break the UI).

### Q5: Do I have to set ADMIN_TOKEN?
On any public deployment, **yes**. Without it, `POST /api/etl/run` is open to everyone, so any visitor can trigger ETL and consume Deribit API quota. Keep the token out of your git history.

### Q6: Where is the data stored? How do I back it up?
Data lives in the Docker named volume `option-scanner-data` (mounted at `/app/data`), **outside the project directory** — re-cloning or rebuilding never loses data. Use `make backup` / `bash ops/etl_docker.sh backup` to back it up.

### Q7: How do I deploy behind a domain with HTTPS?
See [Domain Binding & Reverse Proxy](#domain-binding--reverse-proxy). Set `PUBLIC_PORT=127.0.0.1:3116`, point Caddy at `127.0.0.1:3116`, and Caddy will handle the Let's Encrypt certificates automatically.

### Q8: Docker build fails with "cannot allocate memory" on a low-RAM VPS?
The multi-stage build (npm ci + Next.js build + pip install) is memory-hungry. On small VPSes, run build and up as separate steps and free the build cache in between:
```bash
docker compose build
docker compose down
docker builder prune -af
docker compose up -d
```

### Q9: What do the `mid` and `conservative` pricing modes mean?
- `mid` — theoretical mid-price (bid/ask midpoint, falling back to mark price).
- `conservative` — executable price: buy legs pay the ask, sell legs receive the bid. Results are closer to real fills but odds/APR look slightly worse.

### Q10: Can I hot-reload the frontend during development?
The static export is served by FastAPI, so `npm run dev` alone won't reach the API. Add a rewrite to `frontend/next.config.js`:

```js
// frontend/next.config.js
async rewrites() {
  return [{ source: "/api/:path*", destination: "http://localhost:8000/api/:path*" }];
}
```

then run the backend on port 8000 and `npm run dev` in the frontend. Remove the rewrite before committing if you keep it.

## Disclaimer

This project is for **educational and research purposes only** and does not constitute investment advice. Options trading involves significant risk; users bear all profits and losses themselves. Market data is sourced from Deribit's public API and may contain delays or errors.

## Acknowledgements

Inspired by [xiaochongkun/option-strategy-finder](https://github.com/xiaochongkun/option-strategy-finder). Thanks to the original author.
