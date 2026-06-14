# SunFest «Сила Солнца» — Event Pipeline

Turns the festival website [sunfest.co.il](https://sunfest.co.il/) into a styled,
self-contained HTML programme page with per-event "add to calendar" links and an
`.ics` calendar feed, published to GitHub Pages.

**Live site:** https://mim21.github.io/sunfest/

It is a clone of the [merhav-bari](https://github.com/mim21/merhav-bari) pipeline,
but the data **source is a festival website** (not a WhatsApp chat).

## What it does

1. `build_events.py` transcribes the festival's official schedule + pricing
   (`/`, `/plan.html`, `/payment.html`) into `events.json` (see schema below)
2. `pipeline.py`:
   - **Clean** — drops events whose date has passed, de-duplicates
   - **Validate** — checks `events.json` against the schema
   - **Enrich** *(opt-in, `--enrich`)* — fills any missing price/time/city via Playwright
   - **HTML** — renders a self-contained `index.html` + `calendar.ics`
3. Publishes to GitHub Pages

The festival is one **headline card** (dates, price tiers, lineup) plus an
individual card for **every master-class / concert / ceremony** in the schedule.

The page has client-side **filters by Ведущий (facilitator) and by event type**.
The filter script is inline and allowed by a strict CSP via its sha256 hash
(no `unsafe-inline` for scripts).

## Usage

```bash
python build_events.py        # website schedule  → events.json
python pipeline.py            # events.json        → index.html + calendar.ics
python pipeline.py --push     # also commit + push to GitHub Pages
run.bat                       # Windows: build + pipeline + push in one go
```

Enrichment is **off by default** because `build_events.py` already produces
complete data. Enable it with `--enrich` (needs Playwright):
```bash
pip install playwright && playwright install chromium
python pipeline.py --enrich
```

## When the festival schedule changes

Edit the `SLOTS` / pricing data in [`build_events.py`](build_events.py) (or edit
`events.json` directly — see [CLAUDE.md](CLAUDE.md) for the extraction rules),
then re-run the pipeline.

## events.json schema

Array of events. Each event:

```json
{
  "title": "string",
  "event_type": "festival|workshop|concert|yoga|meditation|dance|ceremony|lecture|other",
  "category": "master-class group label (rendered as a 🏷 mark linking to master-klassy.html)",
  "facilitator": "master / Ведущий name or null (powers the Ведущий filter)",
  "status": "scheduled|updated|postponed|canceled|tentative",
  "date_only": "YYYY-MM-DD",
  "end_date_only": "YYYY-MM-DD or null  (multi-day events only)",
  "start_time_only": "HH:MM or null",
  "end_time_only": "HH:MM or null",
  "raw_date_text": "original date text from the site",
  "location_name": "venue / address or null",
  "city": "city name or null",
  "price_text": "e.g. 'от ₪750' or 'Входит в билет фестиваля' or null",
  "price_unit": "couple|person|null",
  "price_note": "single qualifier string or null",
  "price_details": ["one string per price tier — never include 'истёк', pipeline adds it; put cutoff as 'до DD.MM'"],
  "description": "1-3 sentences",
  "registration_link": "URL or null",
  "image_url": "https://… or null  (event poster; og:image)",
  "contact_info": {
    "phone": [{"number": "05X-XXX-XXXX", "name": "name or null"}],
    "telegram": [],
    "instagram": ["handle"],
    "other": []
  },
  "source_messages": [{
    "line_reference": null,
    "source_excerpt": "short source text",
    "source_message_timestamp": "YYYY-MM-DD"
  }],
  "confidence": 0.95
}
```

### Price tiers
- Put multiple tiers in `price_details`; include the cutoff as `до DD.MM`
  (e.g. `"₪700 — до 30.05"`). The pipeline strikes through and labels expired
  tiers automatically — **never write "истёк" yourself**.

### Images
- `image_url` only — fetched and inlined as a data URI at build time
  (no client-side requests). Prefer the page's `og:image`.

## File structure

```
build_events.py   — transcribes the festival website schedule → events.json
pipeline.py       — clean / validate / enrich / render HTML + ICS / push
events.json       — extracted events
index.html        — generated output (GitHub Pages)
calendar.ics      — generated iCalendar feed
CLAUDE.md         — extraction rules for Claude Code
run.bat           — Windows runner + publish
```
