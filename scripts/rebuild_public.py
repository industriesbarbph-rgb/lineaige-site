#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import shutil
from datetime import date
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EVENTS=ROOT/"data"/"events.json"
FUTURE=ROOT/"data"/"future-announcements.json"
MAIN=ROOT/"index.html"
INDEX=ROOT/"records"/"index.html"
SITEMAP=ROOT/"sitemap.xml"


def load(path:Path):
    return json.loads(path.read_text(encoding="utf-8"))


def esc(value)->str:
    return html.escape(str(value or ""),quote=True)


def time_value(record:dict)->str:
    return record.get("eventDate") or record.get("eventMonth") or str(record.get("eventYear") or record.get("displayDate") or "")


def recorded_events(payload:dict):
    rows=[
      r for r in payload.get("events",[])
      if r.get("recordType") in {"event","entry_point"} and r.get("verification",{}).get("state")=="verified"
    ]
    return sorted(rows,key=lambda r:(time_value(r),r.get("title","").casefold(),r.get("id","")))


def split_history(rows):
    precursors=[]
    ai=[]
    for record in rows:
        layer=record.get("historicalLayer")
        if layer is None:
            year=int(time_value(record)[:4])
            layer="precursor" if year<1956 else "ai-history"
        if layer=="precursor":
            precursors.append(record)
        elif layer=="ai-history":
            ai.append(record)
        else:
            raise SystemExit(f"PUBLIC REBUILD FAILED: unknown historical layer on {record.get('id')}")
    return precursors,ai


def future_events(payload:dict):
    rows=payload.get("records",[])
    if not isinstance(rows,list):
        raise SystemExit("PUBLIC REBUILD FAILED: future records must be an array")
    return sorted(rows,key=lambda r:(str(r.get("targetDate") or ""),r.get("title","").casefold(),r.get("id","")))


def primary_source(record:dict)->dict:
    sources=record.get("sources") or []
    for source in sources:
        if source.get("primary") is True and source.get("sourceRole")=="claim-evidence":
            return source
    for source in sources:
        if source.get("primary") is True:
            return source
    return sources[0] if sources else {}


def card(record:dict)->str:
    return (
      f'<article class="card"><small>{esc(record.get("displayDate"))}</small>'
      f'<h2><a href="/record/{esc(record.get("id"))}/">{esc(record.get("title"))}</a></h2>'
      f'<p>{esc(record.get("summary",""))}</p></article>'
    )


def future_card(record:dict)->str:
    return (
      f'<article class="card"><small>{esc(record.get("targetPrecision") or record.get("targetDate"))}</small>'
      f'<h2><a href="/future/{esc(record.get("id"))}/">{esc(record.get("title"))}</a></h2>'
      f'<p>{esc(record.get("summary",""))}</p></article>'
    )


def update_records_index(ai,precursors,futures):
    text=INDEX.read_text(encoding="utf-8")
    text=re.sub(
      r'<div class="meta"><span>\d+\s+(?:HISTORICAL|AI HISTORY)</span>(?:<span>\d+\s+PRECURSORS</span>)?',
      f'<div class="meta"><span>{len(ai)} AI HISTORY</span><span>{len(precursors)} PRECURSORS</span>',
      text,count=1
    )
    text=re.sub(r'<span>\d+\s+FUTURE</span>',f'<span>{len(futures)} FUTURE</span>',text,count=1)
    replacement=(
      '<h2>Prehistory / foundations / precursors</h2><div class="grid">'
      +"".join(card(r) for r in precursors)
      +'</div><h2>Verified AI history — 1956 onward</h2><div class="grid">'
      +"".join(card(r) for r in ai)
      +'</div><h2>Verified learning resources</h2>'
    )
    patterns=[
      r'<h2>Prehistory / foundations / precursors</h2><div class="grid">.*?</div><h2>Verified AI history — 1956 onward</h2><div class="grid">.*?</div><h2>Verified learning resources</h2>',
      r'<h2>Verified historical records</h2><div class="grid">.*?</div><h2>Verified learning resources</h2>',
    ]
    changed=False
    for pattern in patterns:
        updated,count=re.subn(pattern,replacement,text,count=1,flags=re.S)
        if count==1:
            text=updated
            changed=True
            break
    if not changed:
        raise SystemExit("PUBLIC REBUILD FAILED: history section boundary not found")

    future_replacement='<h2>Announced future</h2><div class="grid">'+"".join(future_card(r) for r in futures)+'</div><footer>'
    text,count=re.subn(r'<h2>Announced future</h2><div class="grid">.*?</div><footer>',future_replacement,text,count=1,flags=re.S)
    if count!=1:
        raise SystemExit("PUBLIC REBUILD FAILED: announced-future section boundary not found")
    text=text.replace(
      "Historical evidence, learning resources, contextual media, and announced future milestones remain separate evidence layers.",
      "Prehistory/precursors, AI history from 1956 onward, learning resources, contextual media, and announced future milestones remain separate evidence layers."
    )
    INDEX.write_text(text,encoding="utf-8")


def record_page(record:dict)->str:
    source=primary_source(record)
    rid=record["id"]; title=record["title"]; summary=record["summary"]
    source_url=source.get("url") or "#"
    canonical=f"https://lineaige.barbph.com/record/{rid}/"
    precursor=record.get("historicalLayer")=="precursor"
    eyebrow="PREHISTORY / PRECURSOR" if precursor else "AI HISTORY"
    status_copy=(
      "This verified record predates the 1956 beginning of artificial intelligence as a recognized research field and is preserved as historical prehistory/foundation."
      if precursor else
      "This verified record belongs to LINEAiGE's artificial-intelligence history layer beginning in 1956."
    )
    return (
      '<!doctype html><html lang="en"><head><meta charset="utf-8">'
      '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
      f'<title>{esc(title)} — LINEAiGE</title><meta name="description" content="{esc(summary[:220])}">'
      '<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1">'
      f'<link rel="canonical" href="{esc(canonical)}"><link rel="stylesheet" href="/assets/seo.css"></head>'
      '<body><main class="wrap">'
      f'<nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/">Home</a> / <a href="/records/">Records</a> / {esc(title)}</nav>'
      f'<a class="brand" href="/">LINEAiGE</a><div class="eyebrow">{eyebrow}</div>'
      f'<h1>{esc(title)}</h1><p class="lede">{esc(summary)}</p>'
      f'<div class="meta"><span>{esc(record.get("displayDate"))}</span><span>{eyebrow}</span></div>'
      f'<section class="card"><h2>Historical classification</h2><p>{esc(status_copy)}</p></section>'
      '<section class="card"><h2>Evidence / resource</h2>'
      f'<div class="actions"><a href="{esc(source_url)}" target="_blank" rel="noopener noreferrer external">OPEN SOURCE</a></div></section>'
      f'<section class="card"><h2>Record identity</h2><p><small>LINEAiGE ID</small><br><code>{esc(rid)}</code></p></section>'
      '<footer>LINEAiGE separates verified precursors from AI-field history and preserves source provenance.'
      '<br><a href="/records/">Record index</a> · <a href="/methodology/">Evidence methodology</a> · <a href="/">Interactive LINEAiGE</a></footer>'
      '</main></body></html>'
    )


def ensure_record_pages(rows):
    root=ROOT/"record"
    root.mkdir(parents=True,exist_ok=True)
    ids={r["id"] for r in rows}
    for child in root.iterdir():
        if child.is_dir() and child.name not in ids:
            shutil.rmtree(child)
    for record in rows:
        path=root/record["id"]/"index.html"
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(record_page(record),encoding="utf-8")


def future_page(record:dict)->str:
    rid=record["id"]; title=record["title"]; summary=record.get("summary","")
    status=record.get("status") or "ANNOUNCED"; source_url=record.get("source") or "#"
    canonical=f"https://lineaige.barbph.com/future/{rid}/"
    lifecycle=record.get("lifecycleState") or "scheduled"
    status_copy=(
      "The target horizon has passed and LINEAiGE is seeking authoritative confirmation, delay, cancellation, or changed scope."
      if status=="DUE FOR CONFIRMATION" else
      "This is an announced future milestone, not a completed historical event."
    )
    return (
      '<!doctype html><html lang="en"><head><meta charset="utf-8">'
      '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
      f'<title>{esc(title)} — Announced Future | LINEAiGE</title><meta name="description" content="{esc(summary[:220])}">'
      '<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1">'
      f'<link rel="canonical" href="{esc(canonical)}"><link rel="stylesheet" href="/assets/seo.css"></head>'
      '<body><main class="wrap">'
      f'<nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/">Home</a> / <a href="/records/">Records</a> / {esc(title)}</nav>'
      '<a class="brand" href="/">LINEAiGE</a><div class="eyebrow">ANNOUNCED FUTURE</div>'
      f'<h1>{esc(title)}</h1><p class="lede">{esc(summary)}</p>'
      f'<div class="meta"><span>{esc(record.get("targetPrecision") or record.get("targetDate"))}</span><span>{esc(status)}</span><span>{esc(record.get("category"))}</span></div>'
      '<section class="card"><h2>Announcement status</h2>'
      f'<p><strong>{esc(status_copy)}</strong></p><p><small>LIFECYCLE</small><br>{esc(lifecycle)}</p>'
      f'<p><small>ANNOUNCED ON</small><br>{esc(record.get("announcedOn"))}</p>'
      f'<p><small>ANNOUNCED BY</small><br>{esc(record.get("organization"))}</p>'
      f'<p><small>TARGET</small><br>{esc(record.get("targetPrecision") or record.get("targetDate"))}</p>'
      f'<p><small>GEOGRAPHY</small><br>{esc(record.get("geography"))}</p>'
      f'<div class="actions"><a href="{esc(source_url)}" target="_blank" rel="noopener noreferrer external">{esc(record.get("sourceLabel") or "OPEN SOURCE")}</a></div></section>'
      '<footer>LINEAiGE preserves chronology, evidence status, and source provenance. A future announcement becomes completed history only after verified evidence confirms the milestone.'
      '<br><a href="/records/">Record index</a> · <a href="/methodology/">Evidence methodology</a> · <a href="/">Interactive LINEAiGE</a></footer>'
      '</main></body></html>'
    )


def ensure_future_pages(futures):
    root=ROOT/"future"; root.mkdir(parents=True,exist_ok=True)
    ids={r["id"] for r in futures}
    for child in root.iterdir():
        if child.is_dir() and child.name not in ids:
            shutil.rmtree(child)
    for record in futures:
        path=root/record["id"]/"index.html"
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(future_page(record),encoding="utf-8")


def homepage_jsonld(ai,precursors,futures):
    today=date.today().isoformat()
    description="Explore LINEAiGE: verified AI history beginning in 1956, documented prehistory and precursors, learning resources, and source-backed future announcements."
    graph=[
      {"@type":"Organization","@id":"https://barbph.com/#organization","name":"BarbPH","url":"https://barbph.com/"},
      {"@type":"WebSite","@id":"https://lineaige.barbph.com/#website","url":"https://lineaige.barbph.com/","name":"LINEAiGE","description":description,"publisher":{"@id":"https://barbph.com/#organization"},"inLanguage":"en"},
      {"@type":"CollectionPage","@id":"https://lineaige.barbph.com/#webpage","url":"https://lineaige.barbph.com/","name":"LINEAiGE — Verified AI History, Precursors & Future Announcements","description":description,"isPartOf":{"@id":"https://lineaige.barbph.com/#website"},"about":{"@type":"Thing","name":"Artificial intelligence history"},"datePublished":"2026-09-20","dateModified":today,"mainEntity":{"@id":"https://lineaige.barbph.com/#ai-history"}},
      {"@type":"ItemList","@id":"https://lineaige.barbph.com/#precursors","name":"Verified prehistory, foundations and precursors to artificial intelligence","numberOfItems":len(precursors),"itemListElement":[{"@type":"ListItem","position":i,"name":r["title"],"url":f"https://lineaige.barbph.com/record/{r['id']}/"} for i,r in enumerate(precursors,1)]},
      {"@type":"ItemList","@id":"https://lineaige.barbph.com/#ai-history","name":"Verified artificial-intelligence history from 1956 onward","numberOfItems":len(ai),"itemListElement":[{"@type":"ListItem","position":i,"name":r["title"],"url":f"https://lineaige.barbph.com/record/{r['id']}/"} for i,r in enumerate(ai,1)]},
      {"@type":"ItemList","@id":"https://lineaige.barbph.com/#announced-future","name":"Evidence-backed announced future AI milestones in LINEAiGE","numberOfItems":len(futures),"itemListElement":[{"@type":"ListItem","position":i,"name":r["title"],"url":f"https://lineaige.barbph.com/future/{r['id']}/"} for i,r in enumerate(futures,1)]},
    ]
    return {"@context":"https://schema.org","@graph":graph}


def update_homepage(ai,precursors,futures):
    text=MAIN.read_text(encoding="utf-8")
    payload=json.dumps(homepage_jsonld(ai,precursors,futures),ensure_ascii=False,separators=(",",":"))
    text,count=re.subn(r'<script type="application/ld\+json">.*?</script>',f'<script type="application/ld+json">{payload}</script>',text,count=1,flags=re.S)
    if count!=1:
        raise SystemExit("PUBLIC REBUILD FAILED: homepage JSON-LD block not found")
    fallback=json.dumps(futures,ensure_ascii=False,separators=(",",":"))
    text,count=re.subn(r'const FUTURE_FALLBACK=.*?;\n',f'const FUTURE_FALLBACK={fallback};\n',text,count=1,flags=re.S)
    if count!=1:
        raise SystemExit("PUBLIC REBUILD FAILED: FUTURE_FALLBACK block not found")
    MAIN.write_text(text,encoding="utf-8")


def update_sitemap(rows,futures):
    text="\n".join(
      line for line in SITEMAP.read_text(encoding="utf-8").splitlines()
      if "https://lineaige.barbph.com/record/" not in line and "https://lineaige.barbph.com/future/" not in line
    )+"\n"
    today=date.today().isoformat()
    rows_xml=[f"  <url><loc>https://lineaige.barbph.com/record/{esc(r['id'])}/</loc><lastmod>{today}</lastmod></url>\n" for r in rows]
    rows_xml += [f"  <url><loc>https://lineaige.barbph.com/future/{esc(r['id'])}/</loc><lastmod>{today}</lastmod></url>\n" for r in futures]
    SITEMAP.write_text(text.replace("</urlset>","".join(rows_xml)+"</urlset>"),encoding="utf-8")


def main():
    rows=recorded_events(load(EVENTS))
    precursors,ai=split_history(rows)
    futures=future_events(load(FUTURE))
    if not ai or int(time_value(ai[0])[:4])!=1956:
        raise SystemExit("PUBLIC REBUILD FAILED: AI history must begin in 1956")
    update_records_index(ai,precursors,futures)
    ensure_record_pages(rows)
    ensure_future_pages(futures)
    update_homepage(ai,precursors,futures)
    update_sitemap(rows,futures)
    print(json.dumps({"aiHistory":len(ai),"precursors":len(precursors),"allRecorded":len(rows),"future":len(futures)},indent=2))


if __name__=="__main__":
    main()
