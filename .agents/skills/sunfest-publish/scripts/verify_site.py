#!/usr/bin/env python3
"""Deterministic structural checks for the SunFest GitHub Pages artifacts."""
from __future__ import annotations
import argparse,json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
class P(HTMLParser):
    def __init__(self):super().__init__();self.links=[];self.classes=[];self.title=[];self.t=False
    def handle_starttag(self,tag,attrs):
        v=dict(attrs)
        if tag=="a" and v.get("href"):self.links.append(v["href"] or "")
        if v.get("class"):self.classes.extend((v["class"] or "").split())
        if tag=="title":self.t=True
    def handle_endtag(self,tag):
        if tag=="title":self.t=False
    def handle_data(self,data):
        if self.t:self.title.append(data)
def parse(path):t=path.read_text(encoding="utf-8");p=P();p.feed(t);p.close();return t,p
def ilinks(page,p,root):
    e=[]
    for href in p.links:
        u=urlparse(href)
        if u.scheme or u.netloc or href.startswith("#"):continue
        target=(page.parent/u.path).resolve()
        if u.path.endswith("/"):target/="index.html"
        if root not in target.parents and target!=root:e.append(f"{page}: internal link escapes repository: {href}")
        elif not target.exists():e.append(f"{page}: missing internal link target: {href}")
    return e
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[4]);root=ap.parse_args().root.resolve()
    home=root/"index.html";archive=root/"archive"/"summer-2026"/"index.html";cal=root/"calendar.ics";edir=root/"events";errors=[]
    for x in (home,archive,cal,edir):
        if not x.exists():errors.append(f"missing required artifact: {x.relative_to(root)}")
    if errors:print(json.dumps({"ok":False,"errors":errors},ensure_ascii=False,indent=2));return 1
    ht,hp=parse(home);at,ar=parse(archive);ct=cal.read_text(encoding="utf-8")
    for m in ("15–17 октября 2026","Расписание опубликовано",'href="calendar.ics"',"archive/summer-2026/","https://wa.me/972556617297"):
        if m not in ht:errors.append(f"index.html: missing marker: {m}")
    if "Точное расписание готовится" in ht:errors.append("index.html: stale pending-program marker found")
    if "202606" in ct:errors.append("calendar.ics: stale June current feed found")
    for m in ("20261015","20261016","20261017"):
        if m not in ct:errors.append(f"calendar.ics: missing October date {m}")
    if ar.classes.count("card")<1:errors.append("archive: no event cards found")
    errors+=ilinks(home,hp,root)+ilinks(archive,ar,root)
    print(json.dumps({"ok":not errors,"homepage_title":"".join(hp.title).strip(),"archive_event_cards":ar.classes.count("card"),"calendar_files":len(list(edir.glob("*.ics"))),"errors":errors},ensure_ascii=False,indent=2));return 0 if not errors else 1
if __name__=="__main__":raise SystemExit(main())
