# SunFest agent workflow

Read `.agents/skills/sunfest-publish/SKILL.md` before any site or festival update.

- **Preserve the original rich, interactive June-style event-card interface.** The site owner explicitly requested restoration of the old interface with new festival data only. Never replace it with a minimal static list.
- The private repository `mim21/sunfest-src` is authoritative for generated `index.html`, `calendar.ics` and `events/`; do not hand-edit generated root artifacts in public, except emergency fixes mirrored to source.
- Interface invariants: facilitator photos (from official pages, never misidentified), one-line session descriptions, workshop detail links, text search, day/master/category/type filters, calendar subscription/download, responsive cards.
- Preserve archived June 2026 material under `archive/summer-2026/`. Never bring June logistics, session descriptions or schedules into current October data.
- Use only the official SunFest website for timetable, artists, photographs and tickets. Keep unverified facts unverified and retain source attribution.
- Validate changes and confirm the deployed GitHub Pages output. Preserve unrelated repository changes.
