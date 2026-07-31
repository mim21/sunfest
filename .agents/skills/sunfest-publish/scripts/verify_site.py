#!/usr/bin/env python3
"""Deterministic structural checks for the SunFest GitHub Pages artifacts."""

from __future__ import annotations

import argparse
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.classes: list[str] = []
        self.title_parts: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a" and values.get("href"):
            self.links.append(values["href"] or "")
        if values.get("class"):
            self.classes.extend((values["class"] or "").split())
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)


def parse_page(path: Path) -> tuple[str, PageParser]:
    text = path.read_text(encoding="utf-8")
    parser = PageParser()
    parser.feed(text)
    parser.close()
    return text, parser


def validate_internal_links(page: Path, parser: PageParser, root: Path) -> list[str]:
    errors: list[str] = []
    for href in parser.links:
        parsed = urlparse(href)
        if parsed.scheme or parsed.netloc or href.startswith("#"):
            continue
        target = (page.parent / parsed.path).resolve()
        if parsed.path.endswith("/"):
            target /= "index.html"
        if root not in target.parents and target != root:
            errors.append(f"{page}: internal link escapes repository: {href}")
        elif not target.exists():
            errors.append(f"{page}: missing internal link target: {href}")
    return errors


def main() -> int:
    default_root = Path(__file__).resolve().parents[4]
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--root", type=Path, default=default_root)
    args = arg_parser.parse_args()
    root = args.root.resolve()
    homepage = root / "index.html"
    archive = root / "archive" / "summer-2026" / "index.html"
    errors: list[str] = []

    for required in (homepage, archive, root / "calendar.ics", root / "events"):
        if not required.exists():
            errors.append(f"missing required artifact: {required.relative_to(root)}")

    if errors:
        print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 1

    home_text, home_parser = parse_page(homepage)
    archive_text, archive_parser = parse_page(archive)
    required_home = (
        "15–17 октября 2026",
        "Точное расписание готовится",
        "archive/summer-2026/",
        "https://wa.me/972556617297",
    )
    required_archive = (
        "Архив программы 18–20 июня 2026",
        'href="../../"',
    )

    for marker in required_home:
        if marker not in home_text:
            errors.append(f"index.html: missing marker: {marker}")
    for marker in required_archive:
        if marker not in archive_text:
            errors.append(f"archive: missing marker: {marker}")
    if "18–20 июня 2026" in home_text:
        errors.append("index.html: old June dates must not appear as current content")

    event_cards = archive_parser.classes.count("card")
    if event_cards < 1:
        errors.append("archive: no event cards found")
    if "file://" in home_text or "localhost" in home_text or "127.0.0.1" in home_text:
        errors.append("index.html: local URL found")

    errors.extend(validate_internal_links(homepage, home_parser, root))
    errors.extend(validate_internal_links(archive, archive_parser, root))
    report = {
        "ok": not errors,
        "homepage_title": "".join(home_parser.title_parts).strip(),
        "archive_title": "".join(archive_parser.title_parts).strip(),
        "archive_event_cards": event_cards,
        "calendar_files": len(list((root / "events").glob("*.ics"))),
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
