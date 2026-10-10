---
name: sunfest-publish
description: Maintain the restored interactive SunFest schedule on GitHub Pages, based on the original June event-card design.
---

# SunFest publication workflow

1. Check repository status and existing project instructions. Current source is `mim21/sunfest-src`.
2. Update `build_events.py` for the official schedule and `october_details.json` for official portraits, one-line summaries and verified workshop detail URLs. Run `python build_events.py && python pipeline.py`.
3. Preserve the original design, responsive event cards, presenter photos, event summaries, details, search, day/presenter/category/type filters, filter subscriptions, and full-calendar links. Avoid structural redesign unless expressly requested.
4. Cross-repo GitHub Actions deploys generated `index.html`, `calendar.ics` and `events/` to public `mim21/sunfest` using the dedicated write-only-to-this-repo SSH deploy key. The public `archive/` remains untouched.
5. Validate with `python3 .agents/skills/sunfest-publish/scripts/verify_site.py` and test filter/search JS. Confirm GitHub Actions and the live Pages site after publication.
6. Only use official `https://sunfest.co.il/program.html` for Oct 15–17 schedule and official ticket/payment pages for prices. Never fill unknown facts with stale June information or attach a photo to an inconsistent presenter identity.

Avoid unnecessary broad file scans. Do not change credentials or deploy secrets without permission.
