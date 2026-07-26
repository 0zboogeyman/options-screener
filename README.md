**English** | [简体中文](README_zh.md)

# Option Scanner

> A multi-strategy scanner built on Deribit options data — covering vertical spreads, single-leg income strategies, iron condors, strangles, calendar spreads, and more.

## Features

| Feature           | Endpoint                                   | Description                                                                                                                   |
| ----------------- | ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| Expiry Scan       | `POST /api/spread/scan`                    | Scan vertical spreads (CALL/PUT × DEBIT/CREDIT) by expiry, sorted by odds                                                     |
| Opinion           | `POST /api/spread/opinion`                 | Filter optimal spreads based on target price and directional view                                                             |
| Cash-Put (CSP)    | `POST /api/strategy/csp`                   | Cash-secured short Put: acquire at discount if price drops, else keep premium; Delta, assignment prob, APR, composite score   |
| Covered Call (CC) | `POST /api/strategy/cc`                    | Covered short Call: sell at premium if price rises, else keep premium; upside, APR, composite score                           |
| Iron Condor       | `POST /api/strategy/iron-condor`           | Four-leg range strategy: short OTM Put spread + short OTM Call spread; SVI-delta leg placement, RND win-rate, margin estimate |
| Strangle          | `POST /api/strategy/strangle`              | OTM Put + OTM Call combo, both long/short vol sides returned; tail risk via RND 5% ES estimate                                |
| Calendar Spread   | `POST /api/strategy/calendar`              | Sell near-term + buy far-term at same strike; SVI term-structure slope scoring + theta capture + profit zone solver           |
| Volatility Panel  | `GET /api/meta/vol`                        | DVOL + IVP/IVR + SVI term structure (ATM IV / RR25 skew / BF25 kurtosis) + 90-day DVOL trend                                  |
| Metadata          | `GET /api/meta/dates` `GET /api/meta/asof` | Available dates, snapshot info (spot price, DVOL)                                                                             |
| Manual ETL        | `POST /api/etl/run` `GET /api/etl/status`  | One-click data refresh (requires `ADMIN_TOKEN`); frontend "Refresh Data" button only shows with token                         |
| Health Check      | `GET /api/health`                          | Service status, latest data date, stale-data alert                                                                            |
| Geolocation       | `GET /api/geo`                             | IP-based language auto-detection (zh-CN/zh-TW/en); called by frontend on first visit                                          |

# 

## Quick Deploy

**Prerequisites**: Docker 20+ and Docker Compose v2; the server must be able to reach the Deribit API.

```bash
cp .env.example .env          # First deploy; edit .env afterwards as needed
docker compose up -d --build  # Build and start in background
```

> The service starts even without `.env`: `env_file` is set to `required: false`, and the container falls back to built-in source defaults.

On first startup with empty data, the container automatically runs an ETL cycle (~1–3 min). Scanning is available once it completes.

**Access**: `http://YOUR_VPS_IP:3116` (opens at root path). Frontend and API share a single port (container port 8000).

## Configuration (.env)

All variables have source-code defaults; leaving them blank uses the default.

| Variable                | Description                                                                        | Default           |
| ----------------------- | ---------------------------------------------------------------------------------- | ----------------- |
| `PUBLIC_PORT`           | External port (set to `127.0.0.1:3116` when behind a domain)                       | `3116`            |
| `CORS_ORIGINS`          | CORS allowlist JSON array                                                          | `[]`              |
| `ETL_SCHEDULE`          | ETL schedule (UTC): `08:05` = Taipei 16:05 / `@every 6h` / `off`                   | `08:05`           |
| `ETL_BASES`             | Bases fetched by ETL                                                               | `["BTC","ETH"]`   |
| `RATE_LIMIT_PER_MINUTE` | Per-IP rate limit for scan endpoints                                               | `30/minute`       |
| `DATA_STALE_HOURS`      | Stale-data alert threshold (hours)                                                 | `25`              |
| `ADMIN_TOKEN`           | Manual ETL token (verified via `X-Admin-Token` header; required on public network) | empty (allow all) |
| `TELEGRAM_BOT_TOKEN`    | Telegram Bot token (enables push when combined with chat_id)                       | empty (disabled)  |
| `TELEGRAM_CHAT_ID`      | Telegram recipient/group chat_id                                                   | empty (disabled)  |
| `GEO_ENABLED`           | IP geolocation switch (`false` returns the default language directly)              | `true`            |
| `GEO_DEFAULT_LANG`      | Default language when geolocation fails                                            | `zh-CN`           |

Data updates run automatically via the in-container `etl-scheduler` process — **no crontab needed**.
View scheduler logs: `docker compose logs app | grep etl`.

## Production Deployment Checklist

Confirm each item before going live:

### 1. Required: Set ADMIN_TOKEN

`ADMIN_TOKEN` protects `POST /api/etl/run` (manual data refresh). **Without it, any visitor can trigger ETL**.

```bash
# .env — use a sufficiently long random string
ADMIN_TOKEN=your-random-token
```

For personal use: visit `https://your-domain/?admin=your-random-token` in a browser. The token is auto-saved to localStorage, and a "Refresh Data" button appears at the top of the page (the token param in the URL is auto-removed). Visitors without the token **cannot see the button, and direct API calls return 401**.

### 2. Optional: Daily Telegram Push

After each scheduled ETL run, the top strategies are auto-pushed. Alerts are also sent when DVOL day-over-day jumps >20% or ETL fails:

```bash
# .env
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...   # Get from @BotFather /newbot
TELEGRAM_CHAT_ID=123456789             # Send any message to the bot first, then visit
                                       # https://api.telegram.org/bot<TOKEN>/getUpdates to find chat.id
```

Both fields must be filled to enable; if either is empty, push is silently skipped. Manual ETL triggers do not push (avoids same-day duplicates).

### 3. Optional: Analytics

Example config at `ops/site-config.example.js`, injected via a **runtime config file** — takes effect on page refresh, **no image rebuild needed**:

```bash
cp ops/site-config.example.js ops/site-override/site-config.js
vi ops/site-override/site-config.js
```

## Domain Binding & Reverse Proxy

A Caddy example config is provided at [ops/Caddyfile.example](ops/Caddyfile.example). Usage:

1. Edit `.env` to bind the container to loopback only:
   
   ```bash
   PUBLIC_PORT=127.0.0.1:3116
   ```

2. Copy and edit the Caddyfile, replacing `yourdomain.com` with your real domain:
   
   ```bash
   cp ops/Caddyfile.example /etc/caddy/Caddyfile
   vi /etc/caddy/Caddyfile
   systemctl reload caddy
   ```

3. Restart the container to apply the new `PUBLIC_PORT`:
   
   ```bash
   docker compose up -d
   ```

Caddy auto-provisions and renews Let's Encrypt certificates — no extra steps required. After setup, `https://yourdomain.com` is accessible; `http://VPS_IP:3116` refuses connections.

## Backup & Restore

Data is stored in the Docker named volume `option-scanner-data`:

```bash
bash ops/etl_docker.sh backup                                # Backup
bash ops/etl_docker.sh restore backups/data-XXXXXXXX.tar.gz  # Restore
```

## Make Commands

| Command                          | Description                            |
| -------------------------------- | -------------------------------------- |
| `make up`                        | Build and start                        |
| `make down` / `restart` / `logs` | Stop / Restart / Live logs             |
| `make status`                    | Container status + port health         |
| `make etl`                       | Manually trigger one ETL run           |
| `make backup`                    | Backup data volume                     |
| `make clean`                     | Stop and remove containers and volumes |

## Algorithms & Pricing Models

Key algorithmic design decisions in this project:

### 1. SVI Parameterized Volatility Surface

Raw SVI 5-parameter model fitting `w(k) = a + b(ρ(k−m) + √((k−m)² + σ²))`, with sqrt-OI weighting, 3 sets of multi-start optimizers, and butterfly no-arbitrage checks. Falls back to mark_iv on fit failure. Daily ETL auto-persists to `vol/history.parquet`.

### 2. RND Risk-Neutral Density (Breeden-Litzenberger)

Builds implied density from the SVI surface: `pdf(k)=g(k)·n(d2(k))/√w(k)`, replacing Monte Carlo for PoP / VaR / CVaR. Captures smile fat tails, closer to real risk than BS lognormal.

### 3. IV Percentile / IV Rank

DVOL historical backfill (`backfill_dvol.py`, resolution=1D, continuation paging) → 30d fixed-tenor total variance interpolation → IVP/IVR percentile. Cold-start period supported by the DVOL series.

### 4. Black-Scholes Greeks Vectorization

`delta_call_vec` / `vega_vec` / `theta_vec` / `gamma_vec` + `prob_between` / `strike_from_delta_vec`, fully numpy-vectorized — single scan ~10ms.

### 5. Deribit Margin Estimation

Standard account naked Call IM=max(0.15−max((K−S)/S,0),0.10)+mark; Put IM=max(same structure, MM); MM Call=0.075+mark, Put=max(0.075, 0.075·mark)+mark (in coin units). Portfolio-level aggregation outputs both `im_standard` and `max_loss`.

### 6. pricing_mode Dual Quotes

`mid` = mid-price (theoretical); `conservative` = executable price (ask for buy legs, bid for sell legs), closer to actual execution cost.

### 7. Other Engineering Optimizations

- `max_gap_steps` bounds combo enumeration complexity from `O(n²)` to `O(n·g)`
- numpy vectorization replaces `iterrows` loops
- In-process cache + `asof_ts` versioning eliminates redundant disk I/O
- SVI surface mtime cache avoids repeated reads on hot scan paths

## Acknowledgements

This project is inspired by [xiaochongkun/option-strategy-finder](https://github.com/xiaochongkun/option-strategy-finder). Thanks to the original author.

## Disclaimer

This project is for educational and research purposes only and does not constitute investment advice. Options trading involves high risk; users bear all profits and losses. Data is sourced from Deribit's public API.
