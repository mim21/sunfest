# SunFest «Сила Солнца»

Interactive GitHub Pages event schedule for the official [SunFest festival](https://sunfest.co.il/).

**Live site:** https://mim21.github.io/sunfest/

Current programme: **15–17 October 2026**, Kinneret. The restored original card-based design includes official presenter portraits where verified, concise event summaries, day/presenter/category/type filters, search, links to detailed workshops and Apple/Google calendar subscription.

The 18–20 June 2026 programme remains preserved at `archive/summer-2026/`.

## Tickets (official published prices checked 2026-10-10)

- Full 3 days: ₪750; 2 days: ₪620; 1+1 for two adults: ₪1400.
- Children under 12: ₪300; ages 12–18: ₪350.

See [official ticket page](https://sunfest.co.il/tickets.html) and [checkout](https://sunfest.co.il/payment.html) for final prices; checkout still includes an outdated textual promotion, so use current selectable rates.

## Publication ownership

The private source repository `mim21/sunfest-src` generates and publishes **`index.html`, `calendar.ics`, `events/`** via SSH deploy key. Edit source `build_events.py` and `october_details.json`, not the generated public site. Public repo retains the June archive and validation. See `AGENTS.md` and `.agents/skills/sunfest-publish/SKILL.md`.
