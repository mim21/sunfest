# Claude Code – SunFest «Сила Солнца»

See README.md for full project docs and the event schema.

## Source
The data source is the festival website: **https://sunfest.co.il/**
Key pages:
- `/`            — about, lineup, pricing summary, og:image poster
- `/plan.html`   — full day-by-day schedule (master + practice per time slot)
- `/payment.html` — ticket tiers with cutoff dates

## How to run
1. Update `events.json` — either edit `build_events.py` (the `SLOTS` table +
   pricing) and run `python build_events.py`, or edit `events.json` directly
   following the schema in README.md.
2. Run `python pipeline.py` (or `python pipeline.py --push`, or `run.bat`).

## Extraction accuracy rules (MANDATORY)

For EVERY event, cross-check BOTH the homepage AND the schedule/payment pages.
Known gaps:

- **end_time_only** — the schedule lists time ranges (e.g. `16:30-18:00`); always
  capture both ends. Use `end_time_only: null` only for open-ended slots like the
  late-night bonfire/jam.
- **Price tiers with cutoff dates** — `/payment.html` lists early-bird tiers with
  ranges like "С 01.06 до 17.06". Put each tier in `price_details` as
  `"₪750 — до 17.06"` so the pipeline auto-marks expired tiers.
- **Master ↔ practice pairing** — on `/plan.html` each slot lists `Мастер` then
  `Практика`. Pair them exactly; do not shuffle facilitators between workshops.
- **Hybrid structure** — keep ONE headline `festival` event (dates 18–20 June,
  all price tiers, lineup summary) PLUS one card per individual workshop / concert
  / ceremony.

## Conflict rules — when pages disagree
Prefer `/payment.html` for prices and cutoff dates; prefer `/plan.html` for the
schedule (days, times, facilitators); prefer `/` for lineup and the poster image.
If sources conflict, use the more specific value and lower `confidence` to ≤0.6.

## price_details vs price_note
- `price_details` (array): multiple tiers → replaces the price display. Include
  cutoff dates as `до DD.MM`. **Never add "истёк" — the pipeline adds it when the
  cutoff has passed.**
- `price_note` (single string): one simple qualifier on a single price.
- For workshops included in the festival ticket, set
  `price_text: "Входит в билет фестиваля"` (no `price_unit`).

## image_url
- Set `image_url` to the event poster, preferring the `og:image` meta tag.
  The festival poster is `https://sunfest.co.il/images/og-share.jpg`.
- The pipeline fetches and inlines it as a data URI at build time. Must be
  `https://`. If none is suitable, omit the field.
- Individual workshops normally have no own poster — leave `image_url: null`.

## Time rules
- 24-hour `HH:MM`. Do not confuse camp arrival (`заезд`) or meals/breaks
  (`ужин`, `обед`, `перерыв`) with a workshop slot — those are not events.
- If end < start (e.g. 22:30 bonfire), it crosses midnight — that is valid.

## Mandatory second pass before saving events.json
Re-open the site and verify for every event: `date_only`, `start/end_time_only`,
`price_text`/`price_details`, `location_name`/`city`, `contact_info.phone`,
`image_url` on the headline.

## When compacting
Focus on: event schema, the `SLOTS` table in build_events.py, pipeline step order,
price-tier cutoff format (`до DD.MM`), any errors encountered.
