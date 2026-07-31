---
name: sunfest-publish
description: Efficiently update and publish the manually maintained SunFest static information page and archived calendars. Use for SunFest facts, schedule, archive, GitHub Pages, or publication changes in mim21/sunfest.
---

# SunFest publish workflow

Keep this workflow low-token and user-triggered. The site is a compact reference,
not a promotional redesign. Never schedule research, ingest messages, monitor
sources, or fetch Unsplash images.

## Minimal context

1. Run `git status -sb` and `git log -1 --oneline`. Read only changed files.
2. Use `rg` for known facts. Never read the full archive, all ICS files, or
   large generated HTML; the validator supplies counts.
3. Do no web research when existing facts are not being refreshed. For a manual
   refresh, open the official SunFest homepage once, then only a specific page
   needed for a missing or conflicting fact. Stop after one authoritative answer.

## Content rules

- Keep `index.html` concise: what, date, place, program/status, price, practical
  details, contact, and archive link. Match the simple calendar-page style.
- Use a timetable only when its printed dates match the future festival.
- Move superseded pages to `archive/<season-year>/`. Do not change `calendar.ics`
  or `events/` until a matching timetable is official.
- Time-qualify prices and leave unknown facts unknown.

## Validate and publish

1. Run `python3 .agents/skills/sunfest-publish/scripts/verify_site.py`.
2. Skip browser/visual QA unless requested or the structural check fails.
3. Inspect the exact diff, stage explicit paths, commit, and push the verified
   commit to `origin/main` when publication is requested.
4. Use existing SSH access. Never change global Git/GitHub credentials or
   settings. Retry a sandbox-blocked network command once with narrow escalation.
5. Make one live homepage/archive request after publication. Query GitHub APIs
   only if push or live verification fails; never poll or monitor.

Report only changed facts, validator result, commit, and live URLs.
