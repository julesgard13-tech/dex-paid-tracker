#!/usr/bin/env python3
"""Free, best-effort DEX Paid observer. No wallet, no trades, no API key."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "docs" / "data.json"
BASE = "https://api.dexscreener.com"
CHAIN = "solana"
MAX_TOKENS = 500
MAX_SNAPSHOTS_PER_TOKEN = 120  # 30 hours at 15-minute cadence
ACTIVE_HOURS = 24
LATE_MINUTES = 30
USER_AGENT = "DEX-Paid-Tracker/1.0 (free research dashboard)"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_timestamp(value):
    if value is None:
        return None
    try:
        n = float(value)
        if n > 10_000_000_000:  # milliseconds
            n /= 1000
        return datetime.fromtimestamp(n, timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def api_get(path: str):
    url = BASE + path
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 or 500 <= exc.code < 600:
                time.sleep(2 * (attempt + 1))
                continue
            print(f"HTTP {exc.code} for {path}")
            return None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"API error for {path}: {exc}")
            time.sleep(2 * (attempt + 1))
    return None


def load_data():
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("tokens"), dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "schema_version": 1,
        "updated_at": None,
        "source": "DEX Screener public API",
        "notes": [
            "entry_mc is the first observed market cap after detection, not a guaranteed exact payment-time market cap.",
            "Only post-entry snapshots contribute to post-entry high and low."
        ],
        "tokens": {}
    }


def get_order_payment(token_address: str):
    payload = api_get(f"/orders/v1/{CHAIN}/{urllib.parse.quote(token_address, safe='')}")

    # L'API peut renvoyer une liste ou un objet contenant "orders".
    if isinstance(payload, dict):
        orders = payload.get("orders", [])
    elif isinstance(payload, list):
        orders = payload
    else:
        return None

    if not isinstance(orders, list):
        return None

    valid = []
    for order in orders:
        if not isinstance(order, dict):
            continue
        if order.get("type") == "tokenProfile" and order.get("status") == "approved":
            ts = parse_timestamp(order.get("paymentTimestamp"))
            if ts:
                valid.append(ts)

    return max(valid) if valid else None


def get_pairs_for_tokens(addresses):
    """DEX Screener batch endpoint accepts up to 30 token addresses."""
    result = {}
    for start in range(0, len(addresses), 30):
        batch = addresses[start:start + 30]
        path = f"/tokens/v1/{CHAIN}/" + ",".join(urllib.parse.quote(a, safe="") for a in batch)
        payload = api_get(path)
        if isinstance(payload, list):
            for pair in payload:
                if not isinstance(pair, dict):
                    continue
                base = (pair.get("baseToken") or {}).get("address")
                quote = (pair.get("quoteToken") or {}).get("address")
                token_addr = base if base in batch else (quote if quote in batch else None)
                if not token_addr:
                    continue
                # Prefer the pair with the greatest reported USD liquidity.
                liquidity = (pair.get("liquidity") or {}).get("usd") or 0
                try:
                    liquidity = float(liquidity)
                except (TypeError, ValueError):
                    liquidity = 0
                old = result.get(token_addr)
                if old is None or liquidity > old[0]:
                    mc = pair.get("marketCap")
                    try:
                        mc = float(mc) if mc is not None else None
                    except (TypeError, ValueError):
                        mc = None
                    result[token_addr] = (liquidity, {
                        "market_cap": mc,
                        "price_usd": pair.get("priceUsd"),
                        "liquidity_usd": liquidity,
                        "pair_address": pair.get("pairAddress"),
                        "pair_url": pair.get("url"),
                        "symbol": (pair.get("baseToken") or {}).get("symbol"),
                        "name": (pair.get("baseToken") or {}).get("name"),
                    })
        time.sleep(0.15)
    return {k: v[1] for k, v in result.items()}


def main():
    now = utc_now()
    now_s = iso(now)
    data = load_data()
    tokens = data["tokens"]

    # This endpoint is a rolling/recent discovery list, not a historical archive.
    profiles = api_get("/token-profiles/latest/v1")
    if isinstance(profiles, list):
        candidates = {}
        for item in profiles:
            if not isinstance(item, dict) or item.get("chainId") != CHAIN:
                continue
            address = item.get("tokenAddress")
            if address:
                candidates[address] = item
        print(f"Found {len(candidates)} recent Solana profile candidates.")

        # Verify that the profile payment is approved and retain its payment timestamp.
        for address, profile in candidates.items():
            if address in tokens and tokens[address].get("payment_timestamp"):
                continue
            paid_at = get_order_payment(address)
            if not paid_at:
                continue
            tokens[address] = {
                "address": address,
                "name": profile.get("description") or profile.get("tokenAddress", "")[:8],
                "symbol": None,
                "profile_url": profile.get("url") or f"https://dexscreener.com/solana/{address}",
                "payment_timestamp": iso(paid_at),
                "first_detected_at": now_s,
                "detection_delay_minutes": round(max(0, (now - paid_at).total_seconds() / 60), 1),
                "entry_mc": None,
                "entry_observed_at": None,
                "entry_quality": "pending",
                "last_mc": None,
                "max_mc_post_entry": None,
                "min_mc_post_entry": None,
                "max_gain_pct_observed": None,
                "max_loss_pct_observed": None,
                "snapshots": [],
                "status": "waiting_for_market_cap",
            }
            time.sleep(0.12)
    else:
        print("Could not read latest token profiles; continuing with existing tokens.")

    # Update active tokens and keep collecting price snapshots for 24 hours.
    addresses_to_update = []
    for address, token in tokens.items():
        entry_time = parse_timestamp(token.get("entry_observed_at") or token.get("first_detected_at"))
        if entry_time and (now - entry_time).total_seconds() <= ACTIVE_HOURS * 3600:
            addresses_to_update.append(address)
        elif entry_time and token.get("entry_mc") is not None:
            token["status"] = "completed_24h"

    # Include newly discovered tokens even if there is no entry snapshot yet.
    for address, token in tokens.items():
        if token.get("entry_mc") is None and address not in addresses_to_update:
            addresses_to_update.append(address)

    pair_data = get_pairs_for_tokens(addresses_to_update)
    for address in addresses_to_update:
        token = tokens.get(address)
        pair = pair_data.get(address)
        if not token or not pair:
            continue
        mc = pair.get("market_cap")
        if mc is None or mc <= 0:
            continue

        token["last_mc"] = mc
        token["symbol"] = pair.get("symbol") or token.get("symbol")
        token["name"] = pair.get("name") or token.get("name")
        token["pair_url"] = pair.get("pair_url") or token.get("pair_url")
        token["liquidity_usd"] = pair.get("liquidity_usd")

        if token.get("entry_mc") is None:
            token["entry_mc"] = mc
            token["entry_observed_at"] = now_s
            delay = token.get("detection_delay_minutes")
            token["entry_quality"] = "near_signal" if delay is not None and delay <= LATE_MINUTES else "late"
            token["status"] = "tracking"
            token["max_mc_post_entry"] = mc
            token["min_mc_post_entry"] = mc
        else:
            token["max_mc_post_entry"] = max(token.get("max_mc_post_entry") or mc, mc)
            token["min_mc_post_entry"] = min(token.get("min_mc_post_entry") or mc, mc)

        entry = token.get("entry_mc")
        if entry:
            token["max_gain_pct_observed"] = round((token["max_mc_post_entry"] / entry - 1) * 100, 2)
            token["max_loss_pct_observed"] = round((token["min_mc_post_entry"] / entry - 1) * 100, 2)

        snaps = token.setdefault("snapshots", [])
        # Avoid duplicate snapshots when a workflow is manually rerun in the same minute.
        if not snaps or snaps[-1].get("observed_at") != now_s:
            snaps.append({
                "observed_at": now_s,
                "market_cap": mc,
                "price_usd": pair.get("price_usd"),
                "liquidity_usd": pair.get("liquidity_usd"),
            })
        token["snapshots"] = snaps[-MAX_SNAPSHOTS_PER_TOKEN:]

        entry_dt = parse_timestamp(token.get("entry_observed_at"))
        if entry_dt and (now - entry_dt).total_seconds() > ACTIVE_HOURS * 3600:
            token["status"] = "completed_24h"

    # Keep the newest 500 records.
    ordered = sorted(
        tokens.items(),
        key=lambda kv: kv[1].get("payment_timestamp") or kv[1].get("first_detected_at") or "",
        reverse=True
    )[:MAX_TOKENS]
    data["tokens"] = dict(ordered)
    data["updated_at"] = now_s
    data["last_run"] = {
        "at": now_s,
        "profile_candidates": len(profiles) if isinstance(profiles, list) else None,
        "tokens_stored": len(data["tokens"]),
        "tokens_with_entry": sum(1 for t in data["tokens"].values() if t.get("entry_mc") is not None),
    }
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps(data["last_run"], ensure_ascii=False))


if __name__ == "__main__":
    main()
