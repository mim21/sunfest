#!/usr/bin/env python3
from pathlib import Path
import hashlib, json, re, shutil

root = Path(__file__).resolve().parents[1]
cal = (root / "calendar.ics").read_text(encoding="utf-8")
blocks = re.findall(r"BEGIN:VEVENT\r?\n.*?\r?\nEND:VEVENT", cal, flags=re.S)
if len(blocks) != 59:
    raise SystemExit(f"expected 59 VEVENT blocks, got {len(blocks)}")

out = root / "events"
if out.exists():
    shutil.rmtree(out)
out.mkdir()

labels = {}
for block in blocks:
    uid = re.search(r"^UID:(.+)$", block, flags=re.M)
    summary = re.search(r"^SUMMARY:(.+)$", block, flags=re.M)
    if not uid or not summary:
        raise SystemExit("VEVENT without UID or SUMMARY")
    stem = hashlib.sha256(uid.group(1).encode("utf-8")).hexdigest()[:16]
    payload = "\r\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//sunfest//public-feed//RU",
        "X-WR-TIMEZONE:Asia/Jerusalem",
        block.replace("\n", "\r\n").replace("\r\r\n", "\r\n"),
        "END:VCALENDAR",
        "",
    ])
    (out / f"{stem}.ics").write_text(payload, encoding="utf-8", newline="")
    labels[stem] = summary.group(1)

(out / "feeds.json").write_text(json.dumps(labels, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(f"wrote {len(blocks)} current event feeds")
