#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import shutil
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "data" / "events.json"
INDEX = ROOT / "records" / "index.html"
SITEMAP = ROOT / "sitemap.xml"

def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)

def time_value(record: dict) -> str:
    return record.get("eventDate") or record.get("eventMonth") or str(record.get("eventYear") or record.get("displayDate") or "")

def primary_source(record: dict) -> dict:
    sources = record.get("sources") or []
    for source in sources:
        if source.get("primary") is True:
            return source
    return sources[0] if sources else {}

def historical_events(payload: dict):
    events = [
        r for r in payload.get("events", [])
        if r.get("recordType") in {"event", "entry_point"} and r.get("verification", {}).get("state") == "verified"
    ]
    return sorted(events, key=time_value)

def card(record: dict) -> str:
    return (
        f'<article class="card"><small>{esc(record.get("displayDate"))}</small>'
        f'<h2><a href="/record/{esc(record.get("id"))}/">{esc(record.get("title"))}</a></h2>'
        f'<p>{esc(record.get("summary", ""))}</p></article>'
    )

def update_records_index(events) -> None:
    if not INDEX.exists():
        return
    text = INDEX.read_text(encoding="utf-8")
    text = re.sub(r"<span>\d+\s+HISTORICAL</span>", f"<span>{len(events)} HISTORICAL</span>", text, count=1)
    replacement = "<h2>Verified historical records</h2><div class=\"grid\">" + "".join(card(r) for r in events) + "</div><h2>Learning"
    updated, count = re.subn(
        r"<h2>Verified historical records</h2><div class=\"grid\">.*?</div><h2>Learning",
        replacement, text, count=1, flags=re.S
    )
    if count == 1 and updated != text:
        INDEX.write_text(updated, encoding="utf-8")

def record_page(record: dict) -> str:
    source = primary_source(record)
    rid = record["id"]
    title = record["title"]
    summary = record["summary"]
    source_url = source.get("url") or "#"
    canonical = f"https://lineaige.barbph.com/record/{rid}/"
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        f'<title>{esc(title)} — LINEAiGE</title><meta name="description" content="{esc(summary[:220])}">'
        '<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1">'
        f'<link rel="canonical" href="{esc(canonical)}"><link rel="stylesheet" href="/assets/seo.css"></head>'
        '<body><main class="wrap">'
        f'<nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/">Home</a> / <a href="/records/">Records</a> / {esc(title)}</nav>'
        '<a class="brand" href="/">LINEAiGE</a><div class="eyebrow">CANONICAL HISTORY</div>'
        f'<h1>{esc(title)}</h1><p class="lede">{esc(summary)}</p>'
        f'<div class="meta"><span>{esc(record.get("displayDate"))}</span><span>CANONICAL HISTORY</span></div>'
        '<section class="card"><h2>Evidence / resource</h2><p>This page preserves the public LINEAiGE record and its first-party source relationship.</p>'
        f'<div class="actions"><a href="{esc(source_url)}" target="_blank" rel="noopener noreferrer external">OPEN SOURCE</a></div></section>'
        f'<section class="card"><h2>Record identity</h2><p><small>LINEAiGE ID</small><br><code>{esc(rid)}</code></p></section>'
        '<footer>LINEAiGE preserves chronology, evidence status, and source provenance. Automated GREEN admissions are limited to deterministic first-party milestones with no inferred causal edges.'
        '<br><a href="/records/">Record index</a> · <a href="/methodology/">Evidence methodology</a> · <a href="/">Interactive LINEAiGE</a></footer>'
        '</main></body></html>'
    )

def ensure_record_pages(events) -> None:
    record_root = ROOT / "record"
    record_root.mkdir(parents=True, exist_ok=True)
    canonical_ids = {record["id"] for record in events}

    # Canonical data is authoritative. Remove generated record pages that are
    # no longer represented in data/events.json so rejected/rolled-back GREEN
    # admissions cannot remain crawlable as orphan history.
    for child in record_root.iterdir():
        if child.is_dir() and child.name not in canonical_ids:
            shutil.rmtree(child)

    for record in events:
        path = record_root / record["id"] / "index.html"
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record_page(record), encoding="utf-8")

def update_sitemap(events) -> None:
    if not SITEMAP.exists():
        return
    text = SITEMAP.read_text(encoding="utf-8")
    # Rebuild the canonical /record/ section from authoritative data instead
    # of append-only behavior, which could preserve rolled-back GREEN records.
    text = re.sub(
        r'^\s*<url><loc>https://lineaige\.barbph\.com/record/.*?</url>\s*\n?',
        '',
        text,
        flags=re.M,
    )
    today = date.today().isoformat()
    rows = [
        f"  <url><loc>https://lineaige.barbph.com/record/{esc(record['id'])}/</loc><lastmod>{today}</lastmod></url>\n"
        for record in events
    ]
    SITEMAP.write_text(text.replace("</urlset>", "".join(rows) + "</urlset>"), encoding="utf-8")

def main():
    payload = load(EVENTS)
    events = historical_events(payload)
    update_records_index(events)
    ensure_record_pages(events)
    update_sitemap(events)
    print(json.dumps({"historical": len(events)}, indent=2))

if __name__ == "__main__":
    main()
