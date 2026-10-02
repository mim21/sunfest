# SunFest «Сила Солнца»

GitHub Pages reference site for the official [SunFest festival](https://sunfest.co.il/).

## Live site
**https://mim21.github.io/sunfest/**

- Current festival: **15–17 October 2026**, Kinneret
- The exact October timetable is now published and reflected on the homepage
- Root `calendar.ics` contains the current October 2026 programme
- The 18–20 June 2026 programme remains under `archive/summer-2026/`

## Current ticket snapshot — checked 2026-10-02
- 3 days: ₪700
- 2 days: ₪590
- 1+1 (two adults, 3 days): ₪1300
- under 12: ₪300
- age 12–18: ₪350

The official homepage still contains an older “₪750 from 1 October” line, so the site records the discrepancy and gives checkout/payment precedence.

## Publication ownership
This repository owns the manually maintained compact homepage. The private source pipeline (`mim21/sunfest-src`) owns structured event data and generated calendar feeds; its deploy workflow must not overwrite this repository's `index.html`.

See `AGENTS.md` and `.agents/skills/sunfest-publish/SKILL.md` before updating.
