#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pip install playwright && playwright install chromium   (Playwright optional — only for enrich)
'''
SunFest «Сила Солнца» – Event Pipeline
website (sunfest.co.il) → events.json → index.html + calendar.ics

Steps (run automatically by this script):
  1. Clean    – remove events whose date has passed; de-duplicate
  2. Validate – check events.json against the schema
  3. Enrich   – (optional) fill missing price / time / city via Playwright
  4. HTML     – render events.json → index.html + calendar.ics

NOTE: Event extraction is done by `build_events.py` (transcribes the festival
website schedule) or by Claude Code editing events.json directly. See CLAUDE.md.
'''

import asyncio
import base64
import hashlib
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from html import escape as h
from pathlib import Path
import urllib.request
from urllib.parse import urlparse, quote

sys.stdout.reconfigure(encoding='utf-8')

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG  ← edit only this section
# ─────────────────────────────────────────────────────────────────────────────
EVENTS_JSON = Path(os.environ.get('SUNFEST_EVENTS_JSON', Path(__file__).parent / 'events.json'))
OUTPUT_HTML = Path(os.environ.get('SUNFEST_OUTPUT_HTML', Path(__file__).parent / 'index.html'))
OUTPUT_CAL  = Path(os.environ.get('SUNFEST_OUTPUT_CAL',  Path(__file__).parent / 'calendar.ics'))
EVENTS_DIR  = OUTPUT_CAL.parent / 'events'   # per-event .ics feeds for subscription
SITE_URL         = 'https://mim21.github.io/sunfest'
# Set to your Cloudflare Worker URL if you want ICS subscription counting
CALENDAR_TRACKER = os.environ.get('SUNFEST_CALENDAR_TRACKER', '')

SHOW_DAYS_AGO    = 1     # show events from N days ago (1 = from yesterday)

WAIT_MS          = 3000
TIMEOUT_MS       = 15000
CONCURRENCY      = 5
MAX_URLS         = 2
MAX_SUBLINKS     = 2
PRICE_MIN        = 20
PRICE_MAX        = 5000


def _events_from_json(data):
    '''Safely extract the events list from any JSON shape.'''
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        events = data.get('events', [])
        return events if isinstance(events, list) else []
    return []


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 – CLEAN OLD EVENTS
# ─────────────────────────────────────────────────────────────────────────────
def step_clean():
    print('\n── Step 1: Clean old events ──')
    today         = date.today()
    cutoff_post   = today - timedelta(days=365)   # festival posts stay relevant all year
    cutoff_event  = today - timedelta(days=1)

    with open(EVENTS_JSON, encoding='utf-8') as f:
        data = json.load(f)
    is_list = isinstance(data, list)
    events  = [e for e in _events_from_json(data) if isinstance(e, dict)]
    print(f"  Loaded {len(events)} events")

    def get_event_date(e):
        for field in ('end_date_only', 'date_only', 'event_start'):
            v = e.get(field)
            if v:
                try: return date.fromisoformat(str(v)[:10])
                except: pass
        return None

    def get_post_date(e):
        msgs = e.get('source_messages')
        for msg in (msgs if isinstance(msgs, list) else []):
            ts = msg.get('source_message_timestamp', '') if isinstance(msg, dict) else ''
            try: return date.fromisoformat(ts[:10])
            except: pass
        return None

    kept, removed = [], []
    for e in events:
        post_d  = get_post_date(e)
        event_d = get_event_date(e)
        if post_d and post_d < cutoff_post:
            removed.append((e, f"post {post_d}"))
        elif event_d and event_d < cutoff_event:
            removed.append((e, f"event {event_d}"))
        else:
            kept.append(e)

    for e, reason in removed:
        title = (_str(e.get('title')) or '?')[:55]
        print(f"  Removed [{reason}]: {title}")

    # Deduplication by (title, date, start time)
    seen_keys, unique = set(), []
    for e in kept:
        key = (
            _str(e.get('title')).strip().lower(),
            _str(e.get('date_only') or e.get('event_start') or '')[:10],
            _str(e.get('start_time_only')),
        )
        if key in seen_keys:
            print(f"  Duplicate removed: {(_str(e.get('title')) or '?')[:55]}")
        else:
            seen_keys.add(key)
            unique.append(e)
    if len(unique) < len(kept):
        print(f"  Removed {len(kept) - len(unique)} duplicate(s)")
    kept = unique
    if events and not kept:
        raise RuntimeError('step_clean would drop all events — refusing to publish empty site')
    print(f"  Keeping {len(kept)} events")

    out = kept if is_list else {'events': kept}
    tmp = EVENTS_JSON.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    os.replace(tmp, EVENTS_JSON)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 – ENRICH WITH PLAYWRIGHT  (optional; skipped when data already complete)
# ─────────────────────────────────────────────────────────────────────────────
URL_RE   = re.compile(r'https?://[^\s\]\)\'"<>]+', re.IGNORECASE)
PRICE_RE = re.compile(r'(\d[\d,\.]*)\s*(?:₪|шек|nis|ils)', re.IGNORECASE | re.UNICODE)
TIME_RE  = re.compile(r'\b([01]?\d|2[0-3]):([0-5]\d)\b')
PHONE_RE = re.compile(
    r'(?:05\d[-.\s]?\d{3}[-.\s]?\d{4}|\+972[-.\s]?\d[-.\s]?\d{3}[-.\s]?\d{4}|'
    r'972[-.\s]?\d[-.\s]?\d{3}[-.\s]?\d{4})')
SKIP_DOMAINS = {'wa.me', 'instagram.com', 'twitter.com', 't.me', 'facebook.com', 'bit.ly'}


def _should_skip(url):
    try:
        host = urlparse(url).netloc.lower().removeprefix('www.')
        return any(d in host for d in SKIP_DOMAINS)
    except: return False


def _collect_urls(event):
    urls, seen = [], set()
    link = _safe_url(event.get('registration_link') or '')
    if link and not _should_skip(link):
        urls.append(link); seen.add(link)
    return urls[:MAX_URLS]


def _best_price(text):
    vals = []
    for m in PRICE_RE.finditer(text):
        try:
            v = float(m.group(1).replace(',', ''))
            if PRICE_MIN <= v <= PRICE_MAX:
                vals.append(int(v))
        except: pass
    vals = sorted(set(vals))
    if not vals: return None
    return f"₪{vals[0]}" if len(vals) == 1 else f"₪{vals[0]}–₪{vals[-1]}"


def _best_times(text):
    times = [f"{int(m.group(1)):02d}:{m.group(2)}" for m in TIME_RE.finditer(text) if 6 <= int(m.group(1)) <= 23]
    if len(times) >= 2: return times[0], times[-1]
    if times: return times[0], None
    return None, None


def _enrich_from_text(event, text):
    changed = False
    if not event.get('price_text'):
        p = _best_price(text)
        if p:
            event['price_text'] = p
            print(f"    price  → {p}")
            changed = True
    if not event.get('start_time_only'):
        s, e = _best_times(text)
        if s:
            event['start_time_only'] = s
            if e and not event.get('end_time_only') and e > s:
                event['end_time_only'] = e
            print(f"    time   → {s}" + (f"–{e}" if e else ''))
            changed = True
    return changed


async def _fetch_text(page, url):
    try:
        await page.goto(url, timeout=TIMEOUT_MS, wait_until='domcontentloaded')
        await page.wait_for_timeout(WAIT_MS)
        return (await page.inner_text('body') or '')[:200_000]
    except Exception as ex:
        print(f"      error: {ex}")
        return ''


async def step_enrich(force=False):
    print('\n── Step 3: Enrich with Playwright ──')
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print('  playwright not installed — skipping')
        return

    with open(EVENTS_JSON, encoding='utf-8') as f:
        data = json.load(f)
    is_list = isinstance(data, list)
    events  = [e for e in _events_from_json(data) if isinstance(e, dict)]
    if not is_list:
        if not isinstance(data, dict): data = {}
        data['events'] = events

    def _needs_enrich(e):
        if force: return True
        return any(not _str(e.get(k)) for k in ['price_text', 'start_time_only', 'city'])
    to_enrich = [(i, e) for i, e in enumerate(events, 1) if _needs_enrich(e) and _collect_urls(e)]
    print(f"  Enriching {len(to_enrich)}/{len(events)} events ({CONCURRENCY} parallel pages)")
    if not to_enrich:
        return

    sem, lock = asyncio.Semaphore(CONCURRENCY), asyncio.Lock()
    total = [0]

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(locale='ru-RU')

        async def worker(idx, event):
            async with sem:
                page = await ctx.new_page()
                try:
                    for url in _collect_urls(event):
                        print(f"  [{idx:02d}] → {url[:70]}")
                        text = await _fetch_text(page, url)
                        if text and _enrich_from_text(event, text):
                            async with lock: total[0] += 1
                            break
                except Exception as ex:
                    print(f"  [{idx:02d}] FAILED: {ex}")
                finally:
                    await page.close()

        await asyncio.gather(*[worker(i, e) for i, e in to_enrich])
        await browser.close()

    print(f"  Enriched {total[0]}/{len(events)} events")
    tmp = EVENTS_JSON.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, EVENTS_JSON)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 – GENERATE HTML
# ─────────────────────────────────────────────────────────────────────────────
RU_MONTHS = ['', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
             'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
RU_DAYS   = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

TYPE_LABELS = {
    'festival':   ('☀️', 'Фестиваль'),
    'workshop':   ('🧘', 'Мастер-класс'),
    'concert':    ('🎵', 'Концерт'),
    'yoga':       ('🧘', 'Йога'),
    'meditation': ('🕉', 'Медитация'),
    'dance':      ('💃', 'Танец'),
    'ceremony':   ('🔥', 'Церемония'),
    'lecture':    ('🎤', 'Лекция'),
    'other':      ('✨', 'Событие'),
}
STATUS_STYLES = {
    'scheduled': ('',             'white'),
    'updated':   ('🔄 Обновлено',  '#e8f4fd'),
    'postponed': ('⏸ Перенесено', '#fff3cd'),
    'canceled':  ('❌ Отменено',   '#fde8e8'),
    'tentative': ('❓ Под вопросом', '#f9f9f9'),
}


def _safe_url(url):
    if not isinstance(url, str) or not url: return ''
    try:
        p = urlparse(url.strip())
        if p.scheme.lower() not in ('http', 'https') or not p.netloc: return ''
        return url.strip()
    except: return ''


def _is_ip_private(ip):
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None  # block all redirects — redirect targets are not re-validated


_no_redirect_opener = urllib.request.build_opener(_NoRedirectHandler())


def _img_uri_remote(url):
    '''Fetch a remote HTTPS image at build time and return a data URI.
    Inlining avoids client-side requests to attacker-controlled hosts.'''
    if not _safe_url(url):
        return None
    try:
        host = urlparse(url).hostname or ''
        if not host or host.lower() in ('localhost',) or host.lower().endswith('.localhost'):
            return None
        try:
            ip = ipaddress.ip_address(host)
            if _is_ip_private(ip):
                return None
            if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
                if _is_ip_private(ip.ipv4_mapped):
                    return None
        except ValueError:
            if host.replace('.', '').replace(':', '').isdigit():
                return None
            try:
                for *_, sockaddr in socket.getaddrinfo(host, None):
                    try:
                        ip = ipaddress.ip_address(sockaddr[0])
                        if _is_ip_private(ip):
                            return None
                        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
                            if _is_ip_private(ip.ipv4_mapped):
                                return None
                    except ValueError:
                        return None
            except OSError:
                return None  # DNS resolution failed — fail closed
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with _no_redirect_opener.open(req, timeout=15) as resp:
            ct = (resp.headers.get_content_type() or '').split(';')[0].strip()
            if not ct.startswith('image/'):
                return None
            data = resp.read(10_000_001)
            if len(data) > 10_000_000:
                return None
            return f'data:{ct};base64,{base64.b64encode(data).decode("ascii")}'
    except Exception:
        return None


def _format_date(event):
    d = event.get('date_only') or event.get('event_start')
    if not d: return _str(event.get('raw_date_text'))
    try:
        dt = date.fromisoformat(str(d)[:10])
        end = event.get('end_date_only')
        if end:
            try:
                dt_end = date.fromisoformat(str(end))
                if dt_end != dt:
                    if dt.month == dt_end.month and dt.year == dt_end.year:
                        return f"{dt.day}–{dt_end.day} {RU_MONTHS[dt.month]} {dt.year}"
                    return f"{dt.day} {RU_MONTHS[dt.month]} – {dt_end.day} {RU_MONTHS[dt_end.month]} {dt_end.year}"
            except: pass
        return f"{RU_DAYS[dt.weekday()]}, {dt.day} {RU_MONTHS[dt.month]} {dt.year}"
    except: return str(d)


# Russian price-tier cutoff: "до 30.04" / "до 17.06"
_TIER_DATE_RE = re.compile(r'до\s+(\d{1,2})[./](\d{1,2})', re.IGNORECASE | re.UNICODE)


def _str(v):
    return v if isinstance(v, str) else ''


def _list(v):
    return v if isinstance(v, list) else []


def _render_price_tier(tier_text):
    tier_text = _str(tier_text)
    today = date.today()
    m = _TIER_DATE_RE.search(tier_text)
    escaped = h(tier_text)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        try:
            tier_date = date(today.year, month, day)
            if tier_date < today:
                return f"<div class='price-tier expired'><s>{escaped}</s> <span class='expired-label'>истёк</span></div>"
        except ValueError:
            pass
    return f"<div class='price-tier'>{escaped}</div>"


def _git_short_hash():
    try:
        kwargs = {'cwd': Path(__file__).parent, 'stderr': subprocess.DEVNULL, 'text': True}
        if sys.platform == 'win32':
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
        return subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], **kwargs).strip()
    except Exception:
        return ''


_ICS_CTRL_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

def _ics_escape(s):
    s = _ICS_CTRL_RE.sub('', _str(s).replace('\r\n', '\n').replace('\r', '\n'))
    return s.replace('\\', '\\\\').replace('\n', '\\n').replace(',', '\\,').replace(';', '\\;')


def _ics_fold(line):
    '''RFC 5545 content-line folding: wrap to ≤75 octets without splitting a
    multi-byte UTF-8 char; continuation lines begin with one space. Google
    Calendar (unlike Apple) drops over-long unfolded DESCRIPTION/URL lines.'''
    if len(line.encode('utf-8')) <= 75:
        return line
    parts, cur, limit = [], bytearray(), 75
    for ch in line:
        cb = ch.encode('utf-8')
        if len(cur) + len(cb) > limit:
            parts.append(cur.decode('utf-8'))
            cur, limit = bytearray(), 74   # continuation lines carry a leading space
        cur += cb
    parts.append(cur.decode('utf-8'))
    return '\r\n '.join(parts)


def _ics_join(lines):
    '''Join ICS content lines (CRLF), folding each to RFC 5545 length, + trailing CRLF.'''
    return '\r\n'.join(_ics_fold(l) for l in lines) + '\r\n'


def _event_slug(event):
    title = _str(event.get('title')) or 'event'
    d = _str(event.get('date_only') or event.get('event_start') or '')[:10].replace('-', '')
    t = _str(event.get('start_time_only')).replace(':', '')
    slug = re.sub(r'[^\w]+', '-', title, flags=re.UNICODE).strip('-') or 'untitled'
    suffix = f'-{d}-{t}' if d and t else f'-{d}' if d else ''
    return f'event-{slug}{suffix}'


def _event_ics_name(event):
    '''ASCII filename for an event's per-event .ics feed (the slug has Cyrillic).'''
    return hashlib.md5(_event_slug(event).encode('utf-8')).hexdigest()[:16] + '.ics'


def _event_cal_data(event, event_url=''):
    '''Return (gs, ge, timed, gcal_url, vevent_lines) or None if event has no date.'''
    title     = _str(event.get('title')) or 'Событие'
    desc      = _str(event.get('description'))
    loc_name_cal = _str(event.get('location_name'))
    loc_city_cal = _str(event.get('city'))
    loc_parts = [p for p in [loc_name_cal,
                              loc_city_cal if loc_city_cal not in loc_name_cal else ''] if p]
    location  = ' · '.join(loc_parts)

    d_raw = event.get('date_only') or event.get('event_start')
    if not d_raw:
        return None
    try:
        start_date = date.fromisoformat(str(d_raw)[:10])
    except ValueError:
        return None

    start_t = _str(event.get('start_time_only'))
    end_t   = _str(event.get('end_time_only'))
    end_d   = _str(event.get('end_date_only'))
    timed   = bool(re.match(r'^\d{2}:\d{2}$', start_t)) and not end_d

    if timed:
        gs = start_date.strftime('%Y%m%d') + 'T' + start_t.replace(':', '') + '00'
        if re.match(r'^\d{2}:\d{2}$', end_t):
            end_date = start_date + timedelta(days=1) if end_t <= start_t else start_date
            ge = end_date.strftime('%Y%m%d') + 'T' + end_t.replace(':', '') + '00'
        else:
            try:
                total = int(start_t[:2]) * 60 + int(start_t[3:]) + 120
                h2, m2 = divmod(total, 60)
                end_date = start_date + timedelta(days=1) if h2 >= 24 else start_date
                ge = end_date.strftime('%Y%m%d') + f'T{h2 % 24:02d}{m2:02d}00'
            except Exception:
                ge = gs
    else:
        gs = start_date.strftime('%Y%m%d')
        try:
            ge = (date.fromisoformat(end_d) + timedelta(days=1)).strftime('%Y%m%d') if end_d else (start_date + timedelta(days=1)).strftime('%Y%m%d')
        except Exception:
            ge = (start_date + timedelta(days=1)).strftime('%Y%m%d')

    details_str = (desc[:400] + '\n' + event_url if desc else event_url) if event_url else desc
    gcal_url = (
        'https://calendar.google.com/calendar/render?action=TEMPLATE'
        '&text=' + quote(title)
        + '&dates=' + gs + '/' + ge
        + ('&details=' + quote(details_str) if details_str else '')
        + ('&location=' + quote(location) if location else '')
    )

    uid   = hashlib.md5('|'.join([title, gs, location]).encode('utf-8')).hexdigest() + '@sunfest'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    vevent = [
        'BEGIN:VEVENT', 'UID:' + uid, 'DTSTAMP:' + stamp,
        ('DTSTART:' + gs) if timed else ('DTSTART;VALUE=DATE:' + gs),
        ('DTEND:'   + ge) if timed else ('DTEND;VALUE=DATE:'   + ge),
        'SUMMARY:' + _ics_escape(title),
    ]
    if desc:
        vevent.append('DESCRIPTION:' + _ics_escape(desc[:500]))
    if location:
        vevent.append('LOCATION:' + _ics_escape(location))
    if event_url:
        vevent.append('URL:' + quote(event_url, safe=':/?=&#-._~@'))
    vevent.append('END:VEVENT')

    return gs, ge, timed, gcal_url, vevent


def _make_cal_links(event, event_url=''):
    if not _event_cal_data(event, event_url):
        return ''
    # Per-event SUBSCRIPTION (auto-updating): points at the hosted per-event feed
    # events/<hash>.ics, rebuilt from the same data as the full calendar — so it
    # tracks changes just like the full subscription, scoped to this one event.
    feed   = (CALENDAR_TRACKER.rstrip('/') or SITE_URL) + '/events/' + _event_ics_name(event)
    webcal = re.sub(r'^https?://', 'webcal://', feed)
    gcal   = 'https://calendar.google.com/calendar/r?cid=' + quote(webcal, safe='')
    return (
        f'<a class="cal-link gcal" href="{h(gcal)}" target="_blank" rel="noopener noreferrer">📅 Google</a>'
        f'<a class="cal-link apple" href="{h(webcal)}">📅 Apple</a>'
    )


def _make_full_cal(events):
    '''Returns (html_buttons, ics_content). Caller must write ics_content to OUTPUT_CAL.'''
    lines = [
        'BEGIN:VCALENDAR', 'VERSION:2.0',
        'PRODID:-//sunfest//pipeline//RU',
        'X-WR-CALNAME:SunFest «Сила Солнца»',
        'X-WR-TIMEZONE:Asia/Jerusalem',
    ]
    for event in events:
        result = _event_cal_data(event, f'{SITE_URL}/#{_event_slug(event)}')
        if result:
            lines.extend(result[4])
    lines.append('END:VCALENDAR')
    ics_content = _ics_join(lines)

    tracker    = CALENDAR_TRACKER.rstrip('/')
    apple_ics  = (tracker + '/calendar.ics?src=apple')  if tracker else (SITE_URL + '/calendar.ics')

    webcal_url = apple_ics.replace('https://', 'webcal://')
    # Google "add by URL" needs a webcal:// feed as the (fully-encoded) cid; an
    # https:// cid is misread as a Google calendar ID → "Unable to add calendar".
    gcal_feed  = (tracker + '/calendar.ics?src=google') if tracker else (SITE_URL + '/calendar.ics')
    gcal_url   = 'https://calendar.google.com/calendar/r?cid=' + quote(
        gcal_feed.replace('https://', 'webcal://'), safe=''
    )

    apple_sub  = f'<a class="cal-link full-cal-apple" href="{h(webcal_url)}">📅 Apple</a>'
    google_sub = f'<a class="cal-link full-cal-gcal" href="{h(gcal_url)}" target="_blank" rel="noopener noreferrer">📅 Google</a>'
    label      = '<span class="sub-all-label">Подписаться на все мероприятия:</span>'
    return label + apple_sub + google_sub, ics_content


def _write_event_cals(events):
    '''Write one .ics feed per event into EVENTS_DIR for per-event subscription.
    Each is a single-VEVENT VCALENDAR named after the event and rebuilt from the
    same data as the full calendar, so subscribers auto-update. Prunes stale files.'''
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    keep = set()
    for e in events:
        result = _event_cal_data(e, f'{SITE_URL}/#{_event_slug(e)}')
        if not result:
            continue
        name = _event_ics_name(e)
        keep.add(name)
        title = _str(e.get('title')) or 'Событие'
        lines = [
            'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//sunfest//pipeline//RU',
            'X-WR-CALNAME:' + _ics_escape(title),
            'X-WR-TIMEZONE:Asia/Jerusalem',
            'REFRESH-INTERVAL;VALUE=DURATION:PT12H', 'X-PUBLISHED-TTL:PT12H',
        ] + result[4] + ['END:VCALENDAR']
        (EVENTS_DIR / name).write_bytes(_ics_join(lines).encode('utf-8'))
    for stale in EVENTS_DIR.glob('*.ics'):
        if stale.name not in keep and not stale.name.startswith('filter-'):
            stale.unlink()
    return len(keep)


def _filter_label(e):
    return TYPE_LABELS.get(_str(e.get('event_type')) or 'other', ('✨', 'Событие'))[1]


def _write_filter_cals(events):
    '''Pre-generate a feed for every reachable filter combination, so the
    "subscribe to visible" button always has a real, auto-updating feed to point
    at. Returns {set-key: absolute feed URL}, where set-key is the sorted
    per-event feed names of the matching events — exactly what the page JS builds
    from the currently-visible cards. Distinct result-sets are deduplicated:
    the full set → calendar.ics, a single event → its per-event feed, otherwise
    a shared filter-<hash>.ics.'''
    dated = [e for e in events if _event_cal_data(e, '')]
    if not dated:
        return {}
    masters = sorted({_str(e.get('facilitator')) for e in dated if _str(e.get('facilitator'))})
    cats    = sorted({_str(e.get('category')) for e in dated if _str(e.get('category'))})
    types   = sorted({_filter_label(e) for e in dated})
    base    = CALENDAR_TRACKER.rstrip('/') or SITE_URL
    all_key = '|'.join(sorted(_event_ics_name(e) for e in dated))

    feed_map, written = {}, set()
    for m in [''] + masters:
        for c in [''] + cats:
            for t in [''] + types:
                sel = [e for e in dated
                       if (not m or _str(e.get('facilitator')) == m)
                       and (not c or _str(e.get('category')) == c)
                       and (not t or _filter_label(e) == t)]
                if not sel:
                    continue
                key = '|'.join(sorted(_event_ics_name(e) for e in sel))
                if key in feed_map:
                    continue
                if key == all_key:
                    feed_map[key] = base + '/calendar.ics'
                elif len(sel) == 1:
                    feed_map[key] = base + '/events/' + _event_ics_name(sel[0])
                else:
                    fname = 'filter-' + hashlib.md5(key.encode('utf-8')).hexdigest()[:16] + '.ics'
                    if fname not in written:
                        written.add(fname)
                        lines = [
                            'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//sunfest//pipeline//RU',
                            'X-WR-CALNAME:SunFest — подборка',
                            'X-WR-TIMEZONE:Asia/Jerusalem',
                            'REFRESH-INTERVAL;VALUE=DURATION:PT12H', 'X-PUBLISHED-TTL:PT12H',
                        ]
                        for e in sel:
                            r = _event_cal_data(e, f'{SITE_URL}/#{_event_slug(e)}')
                            if r:
                                lines += r[4]
                        lines.append('END:VCALENDAR')
                        (EVENTS_DIR / fname).write_bytes(_ics_join(lines).encode('utf-8'))
                    feed_map[key] = base + '/events/' + fname
    for stale in EVENTS_DIR.glob('filter-*.ics'):
        if stale.name not in written:
            stale.unlink()
    return feed_map


def _make_card(event):
    img_tag = ''
    image_url = _safe_url(_str(event.get('image_url') or ''))
    if image_url:
        uri = _img_uri_remote(image_url)
        if uri:
            img_tag = f'<div class="card-img"><img src="{uri}" alt="" loading="lazy"/></div>'

    etype = _str(event.get('event_type')) or 'other'
    icon, label = TYPE_LABELS.get(etype, ('✨', h(etype)))
    status = _str(event.get('status')) or 'scheduled'
    status_label, card_bg = STATUS_STYLES.get(status, ('', 'white'))
    status_html = f'<div class="status-banner">{status_label}</div>' if status_label else ''

    category = _str(event.get('category'))
    cat_mark = (f'<a class="cat-mark" href="#" data-catf="{h(category)}" title="Фильтровать: {h(category)}">🏷 {h(category)}</a>'
                if category else '')

    title    = h(_str(event.get('title')) or 'Событие')
    date_str = h(_format_date(event))
    s, e     = _str(event.get('start_time_only')), _str(event.get('end_time_only'))
    time_str = h(f"{s} – {e}" if s and e else s)

    loc_name = _str(event.get('location_name'))
    loc_city = _str(event.get('city'))
    loc_parts = [p for p in [loc_name, loc_city if loc_city not in loc_name else ''] if p]
    location = h(' · '.join(loc_parts))

    price_raw     = _str(event.get('price_text'))
    price_unit    = event.get('price_unit') or ''
    unit_label    = ' за пару' if price_unit == 'couple' else ' за человека' if price_unit == 'person' else ''
    price         = h(f"{price_raw}{unit_label}") if price_raw else ''
    price_note    = h(_str(event.get('price_note')))
    price_details = _list(event.get('price_details'))

    desc = h(_str(event.get('description')))
    safe_link = h(_safe_url(event.get('registration_link') or ''))
    link_label = 'О фестивале →' if etype == 'festival' else 'Подробнее →'
    link_html = f'<a class="reg-link" href="{safe_link}" target="_blank" rel="noopener noreferrer">{link_label}</a>' if safe_link else ''

    contacts = []
    ci = event.get('contact_info') or {}
    if isinstance(ci, dict):
        wa_svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="14" height="14" fill="#25d366" style="vertical-align:middle;margin-right:3px"><path d="M16 0C7.163 0 0 7.163 0 16c0 2.833.742 5.488 2.042 7.788L0 32l8.418-2.01A15.938 15.938 0 0016 32c8.837 0 16-7.163 16-16S24.837 0 16 0zm0 29.333a13.27 13.27 0 01-6.784-1.857l-.486-.29-5.001 1.194 1.227-4.865-.317-.5A13.267 13.267 0 012.667 16C2.667 8.636 8.636 2.667 16 2.667S29.333 8.636 29.333 16 23.364 29.333 16 29.333zm7.27-9.778c-.398-.199-2.354-1.162-2.718-1.294-.364-.133-.629-.199-.894.199-.265.398-1.028 1.294-1.26 1.56-.232.265-.464.298-.862.1-.398-.2-1.681-.62-3.203-1.976-1.184-1.056-1.983-2.36-2.215-2.758-.232-.398-.025-.613.174-.811.179-.178.398-.464.597-.696.199-.232.265-.398.398-.663.133-.265.066-.497-.033-.696-.1-.199-.894-2.155-1.225-2.95-.322-.775-.649-.67-.894-.682l-.762-.013c-.265 0-.696.1-1.061.497-.364.398-1.393 1.361-1.393 3.317s1.426 3.847 1.625 4.112c.199.265 2.807 4.285 6.802 6.01.951.41 1.693.655 2.271.839.954.304 1.823.261 2.51.158.766-.114 2.354-.962 2.686-1.891.332-.929.332-1.725.232-1.891-.099-.166-.364-.265-.762-.464z"/></svg>'
        for p in _list(ci.get('phone')):
            num  = p.get('number', p) if isinstance(p, dict) else p
            if not isinstance(num, str): continue
            name = _str(p.get('name')) if isinstance(p, dict) else ''
            digits = re.sub(r'\D', '', num)
            if digits.startswith('972'): digits = '0' + digits[3:]
            if len(digits) != 10 or not digits.startswith('05'): continue
            wa_digits = '972' + digits[1:]
            display_num = f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
            wa_url = f"https://wa.me/{wa_digits}"
            contact_label = h(f"{name} {display_num}" if name else display_num)
            contacts.append(f'<a href="{wa_url}" target="_blank" rel="noopener noreferrer" class="contact-wa">{wa_svg}{contact_label}</a>')
        for t in _list(ci.get('telegram')): contacts.append(f'<span class="contact">✈️ {h(_str(t))}</span>')
        for i in _list(ci.get('instagram')):
            handle = _str(i).lstrip('@')
            contacts.append(f'<a class="contact-ig" href="https://instagram.com/{h(handle)}" target="_blank" rel="noopener noreferrer">📷 {h(handle)}</a>')
    contact_html = ''.join(contacts)

    slug = _event_slug(event)
    event_url = f'{SITE_URL}/#{slug}'
    featured = ' featured' if etype == 'festival' else ''
    # Headline festival card already has the full subscribe/download buttons in
    # the header, so skip the redundant per-event Google/Apple links there.
    cal_html = '' if etype == 'festival' else _make_cal_links(event, event_url)
    master = _str(event.get('facilitator'))
    cat_filter = category

    return f"""<div class="card{featured}" id="{slug}" data-master="{h(master)}" data-cat="{h(cat_filter)}" data-type="{h(label)}" data-feed="{_event_ics_name(event)}" style="background:{card_bg}">
  {status_html}
  {img_tag}
  <div class="card-body">
    <div class="card-header-row">
      <span class="badge">{icon} {label}</span>
    </div>
    <h2 class="card-title">{title}</h2>
    {cat_mark}
    {"<div class='card-date'>📅 " + date_str + '</div>' if date_str else ''}
    {"<div class='card-time'>🕐 " + time_str + '</div>' if time_str else ''}
    {"<div class='card-location'>📍 " + location + '</div>' if location else ''}
    {"<div class='card-price'>💰 " + ''.join(_render_price_tier(t) for t in price_details) + '</div>' if price_details else ("<div class='card-price'>💰 " + price + ("  <span class='price-note'>(" + price_note + ')</span>' if price_note else '') + '</div>' if price else '')}
    {"<div class='card-desc'>" + desc + '</div>' if desc else ''}
    <div class="card-footer">{link_html}{contact_html}</div>
    {'<div class="cal-links">' + cal_html + '</div>' if cal_html else ''}
  </div>
</div>"""


def step_html():
    print('\n── Step 4: Generate HTML ──')
    with open(EVENTS_JSON, encoding='utf-8') as f:
        all_events = json.load(f)
    all_events = [e for e in _events_from_json(all_events) if isinstance(e, dict)]

    show_from = (date.today() - timedelta(days=SHOW_DAYS_AGO)).isoformat()
    def _display_end(e):
        for field in ('end_date_only', 'date_only', 'event_start'):
            v = e.get(field)
            if v: return str(v)[:10]
        return ''
    events = [e for e in all_events if _display_end(e) >= show_from]
    # festival headline first, then chronological by date + start time
    events.sort(key=lambda e: (
        0 if e.get('event_type') == 'festival' else 1,
        str(e.get('date_only') or e.get('event_start') or ''),
        str(e.get('start_time_only') or ''),
    ))
    print(f"  Showing {len(events)} events (from {show_from})")

    cards_html              = '\n'.join(_make_card(e) for e in events)
    full_cal_html, ics_content = _make_full_cal(events)
    OUTPUT_CAL.write_bytes(ics_content.encode('utf-8'))  # binary: keep CRLF verbatim (text mode doubles CR on Windows)
    n_feeds = _write_event_cals(events)
    feed_map = _write_filter_cals(events)
    n_filter = len(list(EVENTS_DIR.glob('filter-*.ics')))
    feed_map_json = json.dumps(feed_map, ensure_ascii=True, separators=(',', ':'))
    print(f"  Wrote {n_feeds} per-event + {n_filter} filter .ics feeds → {EVENTS_DIR}")

    # ── Filter controls: by facilitator (Ведущий), category (Категория), event type ──
    facilitators = sorted({_str(e.get('facilitator')) for e in events if _str(e.get('facilitator'))})
    categories   = sorted({_str(e.get('category')) for e in events if _str(e.get('category'))})
    type_labels  = sorted({TYPE_LABELS.get(_str(e.get('event_type')) or 'other', ('✨', 'Событие'))[1] for e in events})
    master_opts  = ''.join(f'<option value="{h(m)}">{h(m)}</option>' for m in facilitators)
    cat_opts     = ''.join(f'<option value="{h(c)}">{h(c)}</option>' for c in categories)
    type_opts    = ''.join(f'<option value="{h(t)}">{h(t)}</option>' for t in type_labels)
    filter_html = (
        '<div class="filters">'
        f'<label>Ведущий: <select id="f-master"><option value="">Все</option>{master_opts}</select></label>'
        f'<label>Категория: <select id="f-cat"><option value="">Все</option>{cat_opts}</select></label>'
        f'<label>Формат: <select id="f-type"><option value="">Все</option>{type_opts}</select></label>'
        '<span id="f-count"></span>'
        '<span id="vis-sub">Подписаться на видимые: '
        '<a id="sub-va" class="cal-link apple" href="#">📅 Apple</a>'
        '<a id="sub-vg" class="cal-link gcal" href="#" target="_blank" rel="noopener noreferrer">📅 Google</a>'
        '</span>'
        '</div>'
    )
    # Inline filter script — CSP allows it via its sha256 hash (script-src stays strict).
    # The two dropdowns cascade: each lists only values valid for the other's selection.
    filter_js = (
        "(function(){"
        "var fm=document.getElementById('f-master'),fc=document.getElementById('f-cat'),"
        "ft=document.getElementById('f-type'),cn=document.getElementById('f-count'),"
        "sva=document.getElementById('sub-va'),svg=document.getElementById('sub-vg'),"
        "svs=document.getElementById('vis-sub');"
        "var FEEDMAP=" + feed_map_json + ";"
        "var cards=Array.prototype.slice.call(document.querySelectorAll('.grid .card'));"
        "var data=cards.map(function(c){return {el:c,m:c.getAttribute('data-master'),"
        "c:c.getAttribute('data-cat'),t:c.getAttribute('data-type'),f:c.getAttribute('data-feed')};});"
        "function updateSub(){var vis=data.filter(function(d){return d.el.style.display!=='none';})"
        ".map(function(d){return d.f;}).sort();var u=FEEDMAP[vis.join('|')];"
        "if(u){var w=u.replace('https://','webcal://');sva.href=w;"
        "svg.href='https://calendar.google.com/calendar/r?cid='+encodeURIComponent(w);"
        "svs.style.display='';}else{svs.style.display='none';}}"
        "function uniq(a){return a.filter(function(v,i){return v&&a.indexOf(v)===i;})"
        ".sort(function(x,y){return x.localeCompare(y,'ru');});}"
        "function fill(sel,vals){var cur=sel.value;sel.length=1;vals.forEach(function(v){"
        "var o=document.createElement('option');o.value=v;o.textContent=v;sel.appendChild(o);});"
        "sel.value=vals.indexOf(cur)>=0?cur:'';}"
        "function match(d,ex){"
        "if(ex!=='m'&&fm.value&&d.m!==fm.value)return false;"
        "if(ex!=='c'&&fc.value&&d.c!==fc.value)return false;"
        "if(ex!=='t'&&ft.value&&d.t!==ft.value)return false;return true;}"
        "function refresh(){"
        "fill(fm,uniq(data.filter(function(d){return match(d,'m');}).map(function(d){return d.m;})));"
        "fill(fc,uniq(data.filter(function(d){return match(d,'c');}).map(function(d){return d.c;})));"
        "fill(ft,uniq(data.filter(function(d){return match(d,'t');}).map(function(d){return d.t;})));}"
        "function apply(){var n=0;data.forEach(function(d){var ok=match(d,null);"
        "d.el.style.display=ok?'':'none';if(ok)n++;});"
        "cn.textContent='Показано: '+n+' из '+cards.length;updateSub();}"
        "function onChange(){refresh();apply();}"
        "fm.addEventListener('change',onChange);fc.addEventListener('change',onChange);"
        "ft.addEventListener('change',onChange);"
        "Array.prototype.forEach.call(document.querySelectorAll('.cat-mark'),function(a){"
        "a.addEventListener('click',function(e){e.preventDefault();"
        "fm.value='';ft.value='';refresh();fc.value=a.getAttribute('data-catf');onChange();"
        "window.scrollTo({top:0,behavior:'smooth'});});});"
        "refresh();apply();"
        "})();"
    )
    js_hash = base64.b64encode(hashlib.sha256(filter_js.encode('utf-8')).digest()).decode('ascii')
    csp = (
        "default-src 'self'; script-src 'sha256-" + js_hash + "'; style-src 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    )

    _ver = _git_short_hash()
    _ver_str = f' · {_ver}' if _ver else ''

    html = f"""<!DOCTYPE html>
<html lang="ru" dir="ltr">
<head>
  <meta charset="UTF-8"/>
  <meta http-equiv="Content-Security-Policy" content="{csp}"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>SunFest «Сила Солнца» 2026 — программа</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Segoe UI', Arial, sans-serif;
      background: linear-gradient(135deg, #fff7e6 0%, #ffe8c2 100%);
      min-height: 100vh; padding: 24px 16px;
    }}
    header {{ text-align: center; margin-bottom: 32px; }}
    header h1 {{ font-size: 2.1rem; color: #c2410c; margin-bottom: 4px; }}
    header p {{ color: #92633a; font-size: 0.95rem; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 20px; max-width: 1400px; margin: 0 auto;
    }}
    .card {{
      border-radius: 16px; box-shadow: 0 4px 16px rgba(0,0,0,0.08);
      overflow: hidden; display: flex; flex-direction: column;
      transition: transform 0.2s, box-shadow 0.2s;
    }}
    .card:hover {{ transform: translateY(-4px); box-shadow: 0 8px 24px rgba(0,0,0,0.14); }}
    .card.featured {{ grid-column: 1 / -1; border: 2px solid #f59e0b; }}
    .card.featured .card-img img {{ max-height: 460px; }}
    .card.featured .card-title {{ font-size: 1.5rem; }}
    .status-banner {{ background: #e74c3c; color: white; font-size: 0.8rem; font-weight: 700; padding: 4px 12px; text-align: center; }}
    .card-img {{ background: #f0f0f0; }}
    .card-img img {{ width: 100%; max-height: 380px; object-fit: contain; display: block; }}
    .card-body {{ padding: 16px; flex: 1; display: flex; flex-direction: column; gap: 6px; }}
    .card-header-row {{ display: flex; justify-content: space-between; align-items: center; }}
    .badge {{ font-size: 0.75rem; padding: 3px 10px; border-radius: 999px; background: #fff0db; color: #c2410c; font-weight: 600; }}
    .card-title {{ font-size: 1.1rem; font-weight: 700; color: #1a202c; margin: 4px 0; line-height: 1.3; }}
    .cat-mark {{ display: inline-block; align-self: flex-start; font-size: 0.72rem; font-weight: 600; padding: 3px 10px; border-radius: 999px; background: #f59e0b; color: #fff; text-decoration: none; }}
    .cat-mark:hover {{ background: #d97706; }}
    .card-date   {{ color: #2d6a4f; font-size: 0.9rem; font-weight: 600; }}
    .card-time   {{ color: #457b9d; font-size: 0.85rem; }}
    .card-location {{ color: #6b7280; font-size: 0.85rem; }}
    .card-price  {{ color: #b45309; font-size: 0.85rem; font-weight: 600; }}
    .price-note  {{ font-size: 0.78rem; font-weight: 400; color: #92400e; }}
    .price-tier  {{ font-size: 0.8rem; color: #92400e; margin-top: 2px; }}
    .price-tier.expired {{ color: #aaa; }}
    .expired-label {{ font-size: 0.72rem; color: #aaa; font-weight: 400; margin-left: 4px; }}
    .card-desc   {{ color: #374151; font-size: 0.85rem; line-height: 1.5; margin-top: 4px; flex: 1; }}
    .card-footer {{ margin-top: 10px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
    .reg-link {{ display: inline-block; padding: 6px 14px; background: #f59e0b; color: white; border-radius: 8px; font-size: 0.8rem; font-weight: 600; text-decoration: none; }}
    .reg-link:hover {{ background: #d97706; }}
    .contact {{ font-size: 0.78rem; color: #6b7280; }}
    .contact-wa {{ font-size: 0.78rem; color: #25d366; text-decoration: none; font-weight: 500; }}
    .contact-wa:hover {{ text-decoration: underline; }}
    .contact-ig {{ font-size: 0.78rem; color: #c13584; text-decoration: none; font-weight: 500; }}
    .contact-ig:hover {{ text-decoration: underline; }}
    .cal-links {{ margin-top: 6px; display: flex; gap: 6px; flex-wrap: wrap; }}
    .cal-link {{ display: inline-block; padding: 4px 10px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; text-decoration: none; }}
    .cal-link.gcal {{ background: #fff0db; color: #c2410c; }}
    .cal-link.gcal:hover {{ background: #ffe1b8; }}
    .cal-link.apple {{ background: #f0f0f0; color: #333; }}
    .cal-link.apple:hover {{ background: #e0e0e0; }}
    .cal-link.full-cal-apple {{ background: #2d6a4f; color: white; padding: 8px 20px; border-radius: 8px; font-size: 0.85rem; font-weight: 600; text-decoration: none; }}
    .cal-link.full-cal-apple:hover {{ background: #1b4332; }}
    .cal-link.full-cal-gcal {{ background: #f59e0b; color: white; padding: 8px 20px; border-radius: 8px; font-size: 0.85rem; font-weight: 600; text-decoration: none; }}
    .cal-link.full-cal-gcal:hover {{ background: #d97706; }}
    .header-actions {{ margin-top: 14px; display: flex; gap: 10px; justify-content: center; flex-wrap: wrap; align-items: center; }}
    .sub-all-label {{ font-size: 0.9rem; color: #92633a; font-weight: 600; }}
    .filters {{ margin-top: 16px; display: flex; gap: 16px; justify-content: center; flex-wrap: wrap; align-items: center; }}
    .filters label {{ font-size: 0.85rem; color: #92633a; font-weight: 600; }}
    .filters select {{ font-size: 0.85rem; padding: 6px 10px; border-radius: 8px; border: 1px solid #f0c98a; background: #fff; color: #1a202c; max-width: 280px; margin-left: 4px; }}
    #f-count {{ font-size: 0.8rem; color: #b08d63; }}
    #vis-sub {{ font-size: 0.85rem; color: #92633a; font-weight: 600; display: inline-flex; gap: 6px; align-items: center; flex-wrap: wrap; }}
    footer {{ text-align: center; margin-top: 40px; color: #b08d63; font-size: 0.8rem; }}
    .last-updated {{ font-size: 0.8rem; color: #b08d63; margin-top: 4px; }}
  </style>
</head>
<body>
  <header>
    <h1>☀️ SunFest «Сила Солнца» 2026</h1>
    <p>Фестиваль духовных практик · 18–20 июня 2026 &nbsp;|&nbsp; {len(events)} событий</p>
    <p class="last-updated">Обновлено: {datetime.now().strftime('%d.%m.%Y %H:%M')}{_ver_str}</p>
    <div class="header-actions">{full_cal_html}</div>
    {filter_html}
  </header>
  <div class="grid">
    {cards_html}
  </div>
  <footer>Источник: sunfest.co.il · {datetime.now().strftime('%d.%m.%Y %H:%M')}{_ver_str}</footer>
  <script>{filter_js}</script>
</body>
</html>"""

    OUTPUT_HTML.write_text(html, encoding='utf-8')
    print(f"  Written: {OUTPUT_HTML}")
    for e in events:
        print(f"    {_str(e.get('date_only')) or '?'}  {_str(e.get('start_time_only')) or '--:--'}  {(_str(e.get('title')) or '')[:50]}")


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 – VALIDATE SCHEMA
# ─────────────────────────────────────────────────────────────────────────────
class ValidationError(Exception):
    pass

_VALID_STATUSES = {'scheduled', 'updated', 'postponed', 'canceled', 'tentative'}


def step_validate():
    print('\n── Step 2: Validate schema ──')
    try:
        with open(EVENTS_JSON, encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as ex:
        raise ValidationError(f'events.json is not valid JSON: {ex}')
    events = [e for e in _events_from_json(data) if isinstance(e, dict)]
    errors = 0
    for i, e in enumerate(events, 1):
        title = _str(e.get('title')) or f'[event {i}]'
        d = e.get('date_only') or e.get('event_start')
        if not d:
            print(f'  [{i}] "{title}": missing date_only')
            errors += 1
        else:
            try:
                date.fromisoformat(str(d)[:10])
            except ValueError:
                print(f'  [{i}] "{title}": invalid date: {d}')
                errors += 1
        etype = e.get('event_type')
        if etype and etype not in TYPE_LABELS:
            print(f'  [{i}] "{title}": unknown event_type "{etype}"')
            errors += 1
        status = e.get('status')
        if status and status not in _VALID_STATUSES:
            print(f'  [{i}] "{title}": unknown status "{status}"')
            errors += 1
        conf = e.get('confidence')
        if conf is not None:
            try:
                if not 0.0 <= float(conf) <= 1.0:
                    print(f'  [{i}] "{title}": confidence out of range: {conf}')
                    errors += 1
            except (TypeError, ValueError):
                print(f'  [{i}] "{title}": invalid confidence: {conf}')
                errors += 1
    if errors:
        print(f'  {errors} error(s) — fix events.json before continuing')
        raise ValidationError(f'{errors} validation error(s) in events.json')
    print(f'  {len(events)} events valid')


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 – GIT PUSH
# ─────────────────────────────────────────────────────────────────────────────
def step_push():
    print('\n── Step 5: Push to GitHub ──')
    cwd = Path(__file__).parent
    try:
        subprocess.run(
            ['git', '-C', str(cwd), 'pull', '--rebase', '--autostash'],
            check=True, capture_output=True, text=True, timeout=30
        )
    except subprocess.CalledProcessError as ex:
        print(f'  Warning: pull --rebase skipped ({ex.stderr.strip()[:100]})')
    subprocess.run(
        ['git', '-C', str(cwd), 'add', '-f', 'index.html', 'calendar.ics', 'events.json'],
        check=True
    )
    result = subprocess.run(
        ['git', '-C', str(cwd), 'commit', '-m', 'Update events'],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        if 'nothing to commit' in result.stdout + result.stderr:
            print('  Nothing to commit.')
            return
        raise RuntimeError(f'git commit failed: {result.stderr.strip()}')
    subprocess.run(['git', '-C', str(cwd), 'push'], check=True)
    print(f'  Published → {SITE_URL}')


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='SunFest event pipeline')
    ap.add_argument('--enrich', action='store_true', help='Scrape registration links to fill missing price/time/city (off by default — build_events.py is authoritative)')
    ap.add_argument('--force', action='store_true', help='With --enrich, re-enrich all events, not just incomplete ones')
    ap.add_argument('--push',  action='store_true', help='Git-push after generating HTML')
    args = ap.parse_args()

    step_clean()
    try:
        step_validate()
    except ValidationError as ex:
        print(f'\nAborted: {ex}')
        sys.exit(1)
    if args.enrich:
        asyncio.run(step_enrich(force=args.force))
    else:
        print('\n── Step 3: Enrich skipped (use --enrich to scrape registration links) ──')
    step_html()
    if args.push:
        step_push()
    print('\nDone.')
