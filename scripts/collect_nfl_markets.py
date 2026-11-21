#!/usr/bin/env python3
"""One-request NFL market snapshot collector. Opt-in only; no prediction or grading."""
from __future__ import annotations
import datetime as dt
import json
import os
from pathlib import Path
import sys
import urllib.parse
import urllib.request

API = 'https://api.sportsgameodds.com/v2/events'
ALLOWED = {'passing_yards', 'rushing_yards', 'receiving_yards'}
BOOKS = {'draftkings', 'fanduel'}
ROOT = Path('data/markets')
MAX_EVENTS = 2
MAX_QUOTES = 100
MAX_BYTES = 3 * 1024 * 1024

def now_utc():
    return dt.datetime.now(dt.timezone.utc)

def iso_time(value):
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.astimezone(dt.timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None

def extract(payload, timestamp):
    if not isinstance(payload, dict) or payload.get('success') is not True:
        raise ValueError('Provider returned an unsuccessful or unrecognized response')
    events = payload.get('data')
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise ValueError('Unexpected event count; refusing unbounded archive')
    accepted = []
    for event in events:
        if not isinstance(event, dict) or event.get('leagueID') != 'NFL':
            continue
        status = event.get('status') or {}
        starts = iso_time(status.get('startsAt'))
        if starts is None or starts <= timestamp or status.get('started') is True:
            continue
        event_id = str(event.get('eventID') or '').strip()
        if not event_id:
            continue
        odds = event.get('odds') or {}
        if not isinstance(odds, dict):
            continue
        for odd in odds.values():
            if not isinstance(odd, dict):
                continue
            stat = odd.get('statID')
            if stat not in ALLOWED or odd.get('periodID') != 'game' or odd.get('betTypeID') != 'ou':
                continue
            side = odd.get('sideID')
            player_id = str(odd.get('playerID') or odd.get('statEntityID') or '').strip()
            if side not in ('over', 'under') or not player_id:
                continue
            by_book = odd.get('byBookmaker') or {}
            if not isinstance(by_book, dict):
                continue
            for book, quote in by_book.items():
                if book not in BOOKS or not isinstance(quote, dict) or quote.get('available') is not True:
                    continue
                try:
                    line = float(quote.get('overUnder'))
                except (TypeError, ValueError):
                    continue
                if not (0 <= line <= 1000) or line != line:
                    continue
                odds_price = str(quote.get('odds') or '').strip()
                if not odds_price or len(odds_price) > 20:
                    continue
                updated = iso_time(quote.get('lastUpdatedAt'))
                if updated is not None and (updated > timestamp + dt.timedelta(minutes=5) or updated >= starts):
                    continue
                accepted.append({
                    'event_id': event_id, 'player_id': player_id, 'stat': stat,
                    'side': side, 'line': line, 'bookmaker': book, 'price': odds_price,
                    'game_start_utc': starts.isoformat(), 'captured_at_utc': timestamp.isoformat(),
                    'provider_updated_at_utc': updated.isoformat() if updated else None,
                    'provider': 'SportsGameOdds', 'graded_outcome': None,
                    'verified_player_mapping': False, 'pregame': True
                })
    if len(accepted) > MAX_QUOTES:
        raise ValueError('Quote cap exceeded; no partial archive written')
    return accepted

def save(rows, timestamp):
    if not rows:
        print('No valid pregame NFL props in bounded response; nothing written.')
        return
    ROOT.mkdir(parents=True, exist_ok=True)
    destination = ROOT / (timestamp.strftime('%Y-%m-%d') + '.jsonl')
    # Idempotent for identical event/player/stat/side/book/time, preserves distinct snapshots.
    existing = []
    if destination.exists():
        existing = [json.loads(line) for line in destination.read_text().splitlines() if line.strip()]
    all_rows = existing + rows
    keys = set(); unique = []
    for row in all_rows:
        key = tuple(row.get(k) for k in ('event_id', 'player_id', 'stat', 'side', 'bookmaker', 'captured_at_utc'))
        if key not in keys:
            keys.add(key);unique.append(row)
    if len(unique) > 500:
        raise ValueError('Daily archive limit reached; refusing to extend')
    tmp = destination.with_suffix('.tmp')
    tmp.write_text(''.join(json.dumps(r, separators=(',', ':'))+'\n' for r in unique), encoding='utf-8')
    tmp.replace(destination)
    print(f'Archived {len(rows)} new quotes; {len(unique)} total on {destination.name}')

def collect():
    if os.getenv('PROP_LOCK_MARKET_ENABLED') != 'true':
        print('Market collection disabled. Set repo variable PROP_LOCK_MARKET_ENABLED=true to opt in.')
        return 0
    token = os.getenv('SPORTSGAMEODDS_API_KEY', '').strip()
    if not token:
        print('Market collection disabled: SPORTSGAMEODDS_API_KEY secret not set.')
        return 0
    timestamp = now_utc()
    params = urllib.parse.urlencode({'leagueID':'NFL','started':'false','oddsAvailable':'true','limit':str(MAX_EVENTS),'includeAltLines':'false'})
    request = urllib.request.Request(API+'?'+params, headers={'X-Api-Key':token,'Accept':'application/json','User-Agent':'PropLockResearch/2.6'})
    # Exactly one provider call per run. Do not follow pagination or automatically retry.
    with urllib.request.urlopen(request, timeout=18) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Provider response too large; refusing to archive')
    rows = extract(json.loads(raw.decode('utf-8')), timestamp)
    save(rows, timestamp)
    return 0

if __name__ == '__main__':
    try:
        sys.exit(collect())
    except Exception as exc:
        print('Market collection failed safely: '+str(exc).split('?',1)[0], file=sys.stderr)
        sys.exit(1)
