#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import shutil
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "data" / "events.json"
FUTURE = ROOT / "data" / "future-announcements.json"
COURSES = ROOT / "data" / "courses.json"
MEDIA = ROOT / "data" / "media.json"
MAIN = ROOT / "index.html"
INDEX = ROOT / "records" / "index.html"
METHODOLOGY = ROOT / "methodology" / "index.html"
SITEMAP = ROOT / "sitemap.xml"

BASE = "https://lineaige.barbph.com"
OG_IMAGE = f"{BASE}/assets/og-lineaige.png"
ROBOTS = "index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1"
SEO_TEMPLATE_LASTMOD = "2026-10-03"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def clean_text(value) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def build_date() -> str:
    """Publication date in LINEAiGE's operating timezone, not the UTC runner date."""
    return datetime.now(ZoneInfo("Asia/Manila")).date().isoformat()


def compact_phrase(value: str, limit: int = 72) -> str:
    """Shorten a phrase at natural boundaries without ellipses or mid-word cuts."""
    phrase = clean_text(value)
    if len(phrase) <= limit:
        return phrase

    phrase = re.sub(r"\s*\([^)]{1,80}\)\s*", " ", phrase).strip()
    if len(phrase) <= limit:
        return phrase

    for marker in [", with ", ", using ", ": ", " — ", " – ", "; ", ", Part ", " Part "]:
        idx = phrase.find(marker)
        if idx >= 12:
            left = phrase[:idx].strip(" ,;:-")
            if left and len(left) <= limit:
                return left

    words = phrase.split()
    chosen = []
    for word in words:
        candidate = " ".join(chosen + [word])
        if len(candidate) > limit:
            break
        chosen.append(word)

    trailing = {
        "a", "an", "and", "as", "at", "by", "for", "from", "in", "into",
        "of", "on", "or", "the", "their", "to", "using", "with",
    }
    while chosen and chosen[-1].strip(" ,;:-").casefold() in trailing:
        chosen.pop()

    return " ".join(chosen).rstrip(" ,;:-") or phrase


def meta_description(value: str, soft_limit: int = 155) -> str:
    """Return readable metadata while protecting initials and avoiding ellipsis truncation."""
    text = clean_text(value)
    if not text:
        return ""

    protected = re.sub(
        r"\b([A-Z])\.(?=\s+[A-Z][A-Za-z'’\-]+)",
        r"\1<LINEAIGE_DOT>",
        text,
    )
    protected = re.sub(
        r"\b(Dr|Mr|Mrs|Ms|Prof|Sr|Jr|St|vs|etc)\.",
        r"\1<LINEAIGE_DOT>",
        protected,
        flags=re.I,
    )

    sentences = [
        part.replace("<LINEAIGE_DOT>", ".").strip()
        for part in re.split(r"(?<=[.!?])\s+", protected)
        if part.strip()
    ]
    if not sentences:
        return text

    first = sentences[0]
    if len(first) <= soft_limit:
        result = first
        for sentence in sentences[1:]:
            candidate = f"{result} {sentence}"
            if len(candidate) > soft_limit:
                break
            result = candidate
        return result

    clauses = [c.strip() for c in re.split(r"(?<=[,;:])\s+|\s+[—–]\s+", first) if c.strip()]
    result = ""
    for clause in clauses:
        candidate = clause if not result else f"{result} {clause}"
        if len(candidate) > soft_limit:
            break
        result = candidate

    if len(result) >= 55:
        result = result.rstrip(" ,;:-")
        return result if result.endswith((".", "!", "?")) else result + "."

    compact = compact_phrase(first, soft_limit - 1).rstrip(" ,;:-")
    return compact if compact.endswith((".", "!", "?")) else compact + "."


def seo_title(value: str, suffix: str = "LINEAiGE", limit: int | None = 60) -> str:
    """Keep SEO titles concise without ellipses, retaining the brand when it fits."""
    title = clean_text(value)
    if not title:
        return suffix

    if title.casefold().endswith(suffix.casefold()):
        return title if limit is None or len(title) <= limit else compact_phrase(title, limit)

    branded = f"{title} — {suffix}"
    if limit is None or len(branded) <= limit:
        return branded

    if len(title) <= limit:
        return title

    short = compact_phrase(title, limit)
    rebranded = f"{short} — {suffix}"
    return rebranded if len(rebranded) <= limit else short


def time_value(record: dict) -> str:
    return (
        record.get("eventDate")
        or record.get("eventMonth")
        or str(record.get("eventYear") or record.get("displayDate") or "")
    )


def year_value(record: dict) -> int:
    m = re.search(r"(?:19|20)\d{2}", time_value(record))
    return int(m.group(0)) if m else 0


def recorded_events(payload: dict):
    rows = [
        r
        for r in payload.get("events", [])
        if r.get("recordType") in {"event", "entry_point"}
        and r.get("verification", {}).get("state") == "verified"
        and r.get("temporalState") == "recorded"
    ]
    return sorted(rows, key=lambda r: (time_value(r), r.get("title", "").casefold(), r.get("id", "")))


def split_history(rows):
    precursors = []
    ai = []
    for record in rows:
        layer = record.get("historicalLayer")
        if layer is None:
            layer = "precursor" if year_value(record) < 1956 else "ai-history"
        if layer == "precursor":
            precursors.append(record)
        elif layer == "ai-history":
            ai.append(record)
        else:
            raise SystemExit(f"PUBLIC REBUILD FAILED: unknown historical layer on {record.get('id')}")
    return precursors, ai


def future_events(payload: dict):
    rows = payload.get("records", [])
    if not isinstance(rows, list):
        raise SystemExit("PUBLIC REBUILD FAILED: future records must be an array")
    return sorted(rows, key=lambda r: (str(r.get("targetDate") or ""), r.get("title", "").casefold(), r.get("id", "")))


def primary_source(record: dict) -> dict:
    sources = record.get("sources") or []
    for source in sources:
        if source.get("primary") is True and source.get("sourceRole") == "claim-evidence":
            return source
    for source in sources:
        if source.get("primary") is True:
            return source
    return sources[0] if sources else {}


def jsonld(payload: dict) -> str:
    return '<script type="application/ld+json">' + json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    ) + "</script>"


def breadcrumb_schema(items):
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i,
                "name": name,
                "item": url,
            }
            for i, (name, url) in enumerate(items, 1)
        ],
    }


def page_schema(
    canonical: str,
    name: str,
    description: str,
    breadcrumbs,
    *,
    page_type: str = "WebPage",
    about=None,
    citations=None,
    main_entity=None,
    date_modified=None,
):
    page = {
        "@type": page_type,
        "@id": canonical + "#webpage",
        "url": canonical,
        "name": name,
        "description": description,
        "isPartOf": {"@id": BASE + "/#website"},
        "publisher": {"@id": "https://barbph.com/#organization"},
        "inLanguage": "en",
    }
    if date_modified:
        page["dateModified"] = str(date_modified)[:10]
    if about:
        page["about"] = about
    if citations:
        page["citation"] = citations
    if main_entity:
        page["mainEntity"] = main_entity
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": "https://barbph.com/#organization",
                "name": "BarbPH",
                "url": "https://barbph.com/",
            },
            {
                "@type": "WebSite",
                "@id": BASE + "/#website",
                "url": BASE + "/",
                "name": "LINEAiGE",
                "publisher": {"@id": "https://barbph.com/#organization"},
                "inLanguage": "en",
            },
            page,
            breadcrumb_schema(breadcrumbs),
        ],
    }


def head_markup(
    *,
    title: str,
    description: str,
    canonical: str,
    schema: dict,
    og_type: str = "website",
):
    return (
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        f"<title>{esc(title)}</title>"
        f'<meta name="description" content="{esc(description)}">'
        f'<meta name="robots" content="{ROBOTS}">'
        f'<meta name="googlebot" content="{ROBOTS}">'
        f'<link rel="canonical" href="{esc(canonical)}">'
        '<meta name="theme-color" content="#030507">'
        '<meta property="og:site_name" content="LINEAiGE">'
        '<meta property="og:locale" content="en_US">'
        f'<meta property="og:type" content="{esc(og_type)}">'
        f'<meta property="og:title" content="{esc(title)}">'
        f'<meta property="og:description" content="{esc(description)}">'
        f'<meta property="og:url" content="{esc(canonical)}">'
        f'<meta property="og:image" content="{esc(OG_IMAGE)}">'
        '<meta property="og:image:width" content="1200">'
        '<meta property="og:image:height" content="630">'
        '<meta property="og:image:alt" content="LINEAiGE AI history timeline">'
        '<meta name="twitter:card" content="summary_large_image">'
        f'<meta name="twitter:title" content="{esc(title)}">'
        f'<meta name="twitter:description" content="{esc(description)}">'
        f'<meta name="twitter:image" content="{esc(OG_IMAGE)}">'
        '<link rel="stylesheet" href="/assets/seo.css">'
        + jsonld(schema)
    )


def card(record: dict) -> str:
    return (
        f'<article class="card"><small>{esc(record.get("displayDate"))}</small>'
        f'<h2><a href="/record/{esc(record.get("id"))}/">{esc(record.get("title"))}</a></h2>'
        f'<p>{esc(meta_description(record.get("summary", ""), 190))}</p></article>'
    )


def future_card(record: dict) -> str:
    return (
        f'<article class="card"><small>{esc(record.get("targetPrecision") or record.get("targetDate"))}</small>'
        f'<h2><a href="/future/{esc(record.get("id"))}/">{esc(record.get("title"))}</a></h2>'
        f'<p>{esc(meta_description(record.get("summary", ""), 190))}</p></article>'
    )


def course_card(record: dict) -> str:
    return (
        f'<article class="card"><small>{esc(record.get("provider"))}</small>'
        f'<h2><a href="/learn/{esc(record.get("id"))}/">{esc(record.get("title"))}</a></h2>'
        f'<p>{esc(" · ".join(filter(None, [record.get("institution"), record.get("level"), record.get("access")])) )}</p></article>'
    )


def media_card(record: dict) -> str:
    return (
        f'<article class="card"><small>{esc(record.get("platform"))}</small>'
        f'<h2><a href="/context/{esc(record.get("id"))}/">{esc(record.get("title"))}</a></h2>'
        f'<p>{esc(record.get("note") or "")}</p></article>'
    )


def records_index_page(ai, precursors, futures, courses, media):
    canonical = BASE + "/records/"
    description = (
        "Browse verified AI history from 1956, documented precursors, learning resources, "
        "context media, and source-backed announced future milestones in LINEAiGE."
    )
    title = "LINEAiGE Record Index — Verified AI History & Sources"
    schema = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": "https://barbph.com/#organization",
                "name": "BarbPH",
                "url": "https://barbph.com/",
            },
            {
                "@type": "WebSite",
                "@id": BASE + "/#website",
                "url": BASE + "/",
                "name": "LINEAiGE",
                "publisher": {"@id": "https://barbph.com/#organization"},
                "inLanguage": "en",
            },
            {
                "@type": "CollectionPage",
                "@id": canonical + "#webpage",
                "url": canonical,
                "name": title,
                "description": description,
                "isPartOf": {"@id": BASE + "/#website"},
                "dateModified": build_date(),
                "inLanguage": "en",
            },
            breadcrumb_schema([("Home", BASE + "/"), ("Record Index", canonical)]),
        ],
    }
    return (
        '<!doctype html><html lang="en"><head>'
        + head_markup(title=title, description=description, canonical=canonical, schema=schema)
        + '</head><body><main class="wrap">'
        '<nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/">Home</a> / Record Index</nav>'
        '<a class="brand" href="/">LINEAiGE</a>'
        '<div class="eyebrow">EVIDENCE INDEX</div>'
        '<h1>LINEAiGE Record Index</h1>'
        '<p class="lede">The crawlable documentary index behind the interactive timeline. '
        'Prehistory and precursors remain separate from artificial-intelligence history beginning in 1956.</p>'
        f'<div class="meta"><span>{len(ai)} AI HISTORY</span><span>{len(precursors)} PRECURSORS</span>'
        f'<span>{len(courses)} LEARNING</span><span>{len(media)} CONTEXT</span><span>{len(futures)} FUTURE</span></div>'
        '<h2>Prehistory / foundations / precursors</h2><div class="grid">'
        + "".join(card(r) for r in precursors)
        + '</div><h2>Verified AI history — 1956 onward</h2><div class="grid">'
        + "".join(card(r) for r in ai)
        + '</div><h2>Verified learning resources</h2><div class="grid">'
        + "".join(course_card(r) for r in courses)
        + '</div><h2>Context media</h2><div class="grid">'
        + "".join(media_card(r) for r in media)
        + '</div><h2>Announced future</h2><div class="grid">'
        + "".join(future_card(r) for r in futures)
        + '</div><footer>LINEAiGE separates prehistory/precursors, AI history from 1956 onward, '
        'learning resources, contextual media, and announced future milestones into distinct evidence layers.'
        '<br><a href="/methodology/">Evidence methodology</a> · <a href="/">Interactive LINEAiGE</a></footer>'
        '</main></body></html>'
    )


def entity_block(record: dict) -> str:
    groups = []
    if record.get("people"):
        groups.append("<p><small>PEOPLE</small><br>" + esc(", ".join(record["people"])) + "</p>")
    if record.get("organizations"):
        groups.append("<p><small>ORGANIZATIONS</small><br>" + esc(", ".join(record["organizations"])) + "</p>")
    if record.get("technologies"):
        groups.append("<p><small>TECHNOLOGIES</small><br>" + esc(", ".join(record["technologies"])) + "</p>")
    if not groups:
        return ""
    return '<section class="card"><h2>People, organizations & technologies</h2>' + "".join(groups) + "</section>"


def verification_block(record: dict) -> str:
    v = record.get("verification") or {}
    return (
        '<section class="card"><h2>Evidence & verification</h2>'
        f'<p><small>STATE</small><br>{esc(v.get("state") or "verified")}</p>'
        f'<p><small>CONFIDENCE</small><br>{esc(v.get("confidence") or "—")}</p>'
        + (f'<p><small>LAST VERIFIED</small><br>{esc(v.get("lastVerified"))}</p>' if v.get("lastVerified") else "")
        + (f'<p>{esc(v.get("note"))}</p>' if v.get("note") else "")
        + "</section>"
    )


def sources_block(record: dict) -> str:
    sources = record.get("sources") or []
    if not sources:
        return ""
    chunks = []
    for i, source in enumerate(sources, 1):
        badges = []
        if source.get("primary"):
            badges.append("PRIMARY")
        if source.get("sourceRole"):
            badges.append(str(source["sourceRole"]).upper())
        label = " · ".join(badges)
        chunks.append(
            '<div class="card">'
            f'<small>SOURCE {i}{(" · " + esc(label)) if label else ""}</small>'
            f'<h2>{esc(source.get("title") or "Source")}</h2>'
            + (f'<p>{esc(source.get("publisher"))}</p>' if source.get("publisher") else "")
            + (f'<p><small>PUBLISHED</small><br>{esc(source.get("publishedDate"))}</p>' if source.get("publishedDate") else "")
            + (f'<div class="actions"><a href="{esc(source.get("url"))}" target="_blank" rel="noopener noreferrer external">OPEN SOURCE</a></div>' if source.get("url") else "")
            + (f'<div class="actions"><a href="{esc(source.get("archivedUrl"))}" target="_blank" rel="noopener noreferrer external">OPEN ARCHIVE</a></div>' if source.get("archivedUrl") else "")
            + "</div>"
        )
    return '<section><h2>Sources</h2><div class="grid">' + "".join(chunks) + "</div></section>"


def corrections_block(record: dict) -> str:
    corrections = record.get("corrections") or []
    if not corrections:
        return ""
    chunks = []
    for i, correction in enumerate(corrections, 1):
        parts = []
        for label, key in [
            ("DATE", "date"),
            ("FIELD", "field"),
            ("PREVIOUS", "previousValue"),
            ("CORRECTED", "correctedValue"),
            ("NOTE", "note"),
            ("REASON", "reason"),
        ]:
            if correction.get(key):
                parts.append(f"<p><small>{label}</small><br>{esc(correction[key])}</p>")
        if correction.get("sourceUrl"):
            parts.append(
                f'<div class="actions"><a href="{esc(correction["sourceUrl"])}" target="_blank" rel="noopener noreferrer external">CORRECTION EVIDENCE</a></div>'
            )
        chunks.append(f'<div class="card"><h2>Correction {i}</h2>{"".join(parts)}</div>')
    return '<section><h2>Correction history</h2>' + "".join(chunks) + "</section>"


def contributor_block(record: dict) -> str:
    contributor = record.get("contributor")
    if not contributor:
        return ""
    if isinstance(contributor, str):
        text = contributor
    else:
        values = [
            contributor.get("name"),
            contributor.get("type"),
            contributor.get("admittedAt"),
            contributor.get("note"),
        ]
        text = " · ".join(str(v) for v in values if v)
    return f'<section class="card"><h2>Co-author / marginalia</h2><p>{esc(text)}</p></section>'


def record_lastmod(record: dict) -> str:
    verified = (record.get("verification") or {}).get("lastVerified")
    if verified:
        return max_lastmod(str(verified)[:10], SEO_TEMPLATE_LASTMOD)
    value = record.get("eventDate") or record.get("eventMonth") or record.get("eventYear")
    if value:
        raw = str(value)
        if re.match(r"^\d{4}-\d{2}-\d{2}", raw):
            return max_lastmod(raw[:10], SEO_TEMPLATE_LASTMOD)
        if re.match(r"^\d{4}-\d{2}", raw):
            return max_lastmod(raw[:7] + "-01", SEO_TEMPLATE_LASTMOD)
        if re.match(r"^\d{4}$", raw):
            return max_lastmod(raw + "-01-01", SEO_TEMPLATE_LASTMOD)
    return SEO_TEMPLATE_LASTMOD


def record_page(record: dict, previous_record, next_record, courses, media, valid_ids: set[str]) -> str:
    rid = record["id"]
    raw_title = record["title"]
    summary = record.get("summary") or ""
    description = meta_description(summary)
    title = seo_title(raw_title)
    canonical = f"{BASE}/record/{rid}/"
    precursor = record.get("historicalLayer") == "precursor"
    eyebrow = "PREHISTORY / PRECURSOR" if precursor else "AI HISTORY"
    status_copy = (
        "This verified record predates the 1956 beginning of artificial intelligence as a recognized research field and is preserved as historical prehistory/foundation."
        if precursor
        else "This verified record belongs to LINEAiGE's artificial-intelligence history layer beginning in 1956."
    )

    citation_urls = [s.get("url") for s in (record.get("sources") or []) if s.get("url")]
    about = {
        "@type": "Thing",
        "name": raw_title,
        "description": summary,
    }
    schema = page_schema(
        canonical,
        raw_title + " — LINEAiGE",
        description,
        [("Home", BASE + "/"), ("Records", BASE + "/records/"), (raw_title, canonical)],
        page_type="Article",
        about=about,
        citations=citation_urls,
        date_modified=record_lastmod(record),
    )

    nav_actions = []
    if previous_record:
        nav_actions.append(
            f'<a href="/record/{esc(previous_record["id"])}/">← {esc(previous_record["title"])}</a>'
        )
    if next_record:
        nav_actions.append(
            f'<a href="/record/{esc(next_record["id"])}/">{esc(next_record["title"])} →</a>'
        )
    navigation = (
        '<section class="card"><h2>Trace the chronology</h2><div class="actions">'
        + "".join(nav_actions)
        + "</div></section>"
        if nav_actions
        else ""
    )

    semantic_links = []
    seen = set()
    for rel in record.get("relationships") or []:
        target = rel.get("targetId")
        if not target or target not in valid_ids or target in seen:
            continue
        if rel.get("type") in {"chronological", "navigation"}:
            continue
        seen.add(target)
        semantic_links.append(
            f'<p><a href="/record/{esc(target)}/">{esc(rel.get("label") or target)}</a>'
            + (f'<br><small>{esc(rel.get("evidenceNote"))}</small>' if rel.get("evidenceNote") else "")
            + "</p>"
        )
    relationships = (
        '<section class="card"><h2>Related LINEAiGE records</h2>' + "".join(semantic_links) + "</section>"
        if semantic_links
        else ""
    )

    linked_courses = [c for c in courses if rid in (c.get("eventIds") or [])]
    learning = (
        '<section class="card"><h2>Learn this topic</h2>'
        + "".join(
            f'<p><a href="/learn/{esc(c["id"])}/">{esc(c["title"])}</a><br><small>{esc(c.get("provider"))}</small></p>'
            for c in linked_courses
        )
        + "</section>"
        if linked_courses
        else ""
    )

    linked_media = [m for m in media if m.get("eventId") == rid]
    context = (
        '<section class="card"><h2>Context media</h2>'
        + "".join(
            f'<p><a href="/context/{esc(m["id"])}/">{esc(m["title"])}</a>'
            + (f'<br><small>{esc(m.get("creator") or m.get("platform"))}</small>' if (m.get("creator") or m.get("platform")) else "")
            + "</p>"
            for m in linked_media
        )
        + "</section>"
        if linked_media
        else ""
    )

    significance = (
        f'<section class="card"><h2>Why it matters</h2><p>{esc(record.get("significance"))}</p></section>'
        if record.get("significance")
        else ""
    )

    return (
        '<!doctype html><html lang="en"><head>'
        + head_markup(title=title, description=description, canonical=canonical, schema=schema, og_type="article")
        + '</head><body><main class="wrap">'
        f'<nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/">Home</a> / <a href="/records/">Records</a> / {esc(raw_title)}</nav>'
        '<a class="brand" href="/">LINEAiGE</a>'
        f'<div class="eyebrow">{eyebrow}</div>'
        f'<h1>{esc(raw_title)}</h1><p class="lede">{esc(summary)}</p>'
        f'<div class="meta"><span>{esc(record.get("displayDate"))}</span><span>{eyebrow}</span><span>VERIFIED</span></div>'
        f'<section class="card"><h2>Historical classification</h2><p>{esc(status_copy)}</p></section>'
        + significance
        + entity_block(record)
        + verification_block(record)
        + sources_block(record)
        + navigation
        + relationships
        + learning
        + context
        + corrections_block(record)
        + contributor_block(record)
        + f'<section class="card"><h2>Record identity</h2><p><small>LINEAiGE ID</small><br><code>{esc(rid)}</code></p></section>'
        '<footer>LINEAiGE separates verified precursors from AI-field history and preserves source provenance.'
        '<br><a href="/records/">Record index</a> · <a href="/methodology/">Evidence methodology</a> · <a href="/">Interactive LINEAiGE</a></footer>'
        '</main></body></html>'
    )


def ensure_record_pages(rows, courses, media):
    root = ROOT / "record"
    root.mkdir(parents=True, exist_ok=True)
    ids = {r["id"] for r in rows}
    for child in root.iterdir():
        if child.is_dir() and child.name not in ids:
            shutil.rmtree(child)
    for i, record in enumerate(rows):
        path = root / record["id"] / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        previous_record = rows[i - 1] if i > 0 else None
        next_record = rows[i + 1] if i + 1 < len(rows) else None
        path.write_text(
            record_page(record, previous_record, next_record, courses, media, ids),
            encoding="utf-8",
        )


def future_page(record: dict, previous_record, next_record, lifecycle_lastmod=None) -> str:
    rid = record["id"]
    raw_title = record["title"]
    summary = record.get("summary", "")
    description = meta_description(summary)
    title = seo_title(raw_title, "LINEAiGE Future")
    status = record.get("status") or "ANNOUNCED"
    source_url = record.get("source") or "#"
    canonical = f"{BASE}/future/{rid}/"
    lifecycle = record.get("lifecycleState") or "scheduled"
    status_copy = (
        "The target horizon has passed and LINEAiGE is seeking authoritative confirmation, delay, cancellation, or changed scope."
        if status == "DUE FOR CONFIRMATION"
        else "This is an announced future milestone, not a completed historical event."
    )

    schema = page_schema(
        canonical,
        raw_title + " — Announced Future | LINEAiGE",
        description,
        [("Home", BASE + "/"), ("Records", BASE + "/records/"), (raw_title, canonical)],
        about={
            "@type": "Thing",
            "name": raw_title,
            "description": summary,
        },
        page_type="Article",
        citations=[source_url] if source_url != "#" else [],
        date_modified=max_lastmod(lifecycle_lastmod, record.get("announcedOn"), SEO_TEMPLATE_LASTMOD),
    )

    nav_actions = []
    if previous_record:
        nav_actions.append(
            f'<a href="/future/{esc(previous_record["id"])}/">← {esc(previous_record["title"])}</a>'
        )
    if next_record:
        nav_actions.append(
            f'<a href="/future/{esc(next_record["id"])}/">{esc(next_record["title"])} →</a>'
        )
    navigation = (
        '<section class="card"><h2>Other announced future records</h2><div class="actions">'
        + "".join(nav_actions)
        + "</div></section>"
        if nav_actions
        else ""
    )

    return (
        '<!doctype html><html lang="en"><head>'
        + head_markup(title=title, description=description, canonical=canonical, schema=schema, og_type="article")
        + '</head><body><main class="wrap">'
        f'<nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/">Home</a> / <a href="/records/">Records</a> / {esc(raw_title)}</nav>'
        '<a class="brand" href="/">LINEAiGE</a><div class="eyebrow">ANNOUNCED FUTURE</div>'
        f'<h1>{esc(raw_title)}</h1><p class="lede">{esc(summary)}</p>'
        f'<div class="meta"><span>{esc(record.get("targetPrecision") or record.get("targetDate"))}</span>'
        f'<span>{esc(status)}</span><span>{esc(record.get("category"))}</span></div>'
        '<section class="card"><h2>Announcement status</h2>'
        f'<p><strong>{esc(status_copy)}</strong></p>'
        f'<p><small>LIFECYCLE</small><br>{esc(lifecycle)}</p>'
        f'<p><small>ANNOUNCED ON</small><br>{esc(record.get("announcedOn"))}</p>'
        f'<p><small>ANNOUNCED BY</small><br>{esc(record.get("organization"))}</p>'
        f'<p><small>TARGET</small><br>{esc(record.get("targetPrecision") or record.get("targetDate"))}</p>'
        f'<p><small>GEOGRAPHY</small><br>{esc(record.get("geography"))}</p>'
        f'<p><small>EVIDENCE QUALITY</small><br>{esc(record.get("evidenceQuality"))}</p>'
        f'<div class="actions"><a href="{esc(source_url)}" target="_blank" rel="noopener noreferrer external">{esc(record.get("sourceLabel") or "OPEN SOURCE")}</a></div>'
        '</section>'
        + navigation
        + f'<section class="card"><h2>Record identity</h2><p><small>LINEAiGE ID</small><br><code>{esc(rid)}</code></p></section>'
        '<footer>LINEAiGE preserves chronology, evidence status, and source provenance. '
        'A future announcement becomes completed history only after verified evidence confirms the milestone.'
        '<br><a href="/records/">Record index</a> · <a href="/methodology/">Evidence methodology</a> · <a href="/">Interactive LINEAiGE</a></footer>'
        '</main></body></html>'
    )


def ensure_future_pages(futures, lifecycle_lastmod=None):
    root = ROOT / "future"
    root.mkdir(parents=True, exist_ok=True)
    ids = {r["id"] for r in futures}
    for child in root.iterdir():
        if child.is_dir() and child.name not in ids:
            shutil.rmtree(child)
    for i, record in enumerate(futures):
        path = root / record["id"] / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            future_page(
                record,
                futures[i - 1] if i > 0 else None,
                futures[i + 1] if i + 1 < len(futures) else None,
                lifecycle_lastmod,
            ),
            encoding="utf-8",
        )


def course_page(record: dict) -> str:
    rid = record["id"]
    canonical = f"{BASE}/learn/{rid}/"
    topics = ", ".join(record.get("topics") or [])
    raw_desc = " · ".join(
        filter(
            None,
            [
                record.get("provider"),
                record.get("institution"),
                record.get("level"),
                record.get("access"),
                ("Topics include " + topics) if topics else None,
            ],
        )
    )
    description = meta_description(raw_desc)
    title = seo_title(record["title"])
    provider = {
        "@type": "Organization",
        "name": record.get("institution") or record.get("provider") or "Course provider",
    }
    course_entity = {
        "@type": "Course",
        "name": record["title"],
        "url": record.get("courseUrl"),
        "provider": provider,
        "description": description,
    }
    schema = page_schema(
        canonical,
        record["title"] + " — LINEAiGE",
        description,
        [("Home", BASE + "/"), ("Records", BASE + "/records/"), (record["title"], canonical)],
        main_entity=course_entity,
        date_modified=max_lastmod(record.get("verifiedAt"), SEO_TEMPLATE_LASTMOD),
    )
    return (
        '<!doctype html><html lang="en"><head>'
        + head_markup(title=title, description=description, canonical=canonical, schema=schema)
        + '</head><body><main class="wrap">'
        f'<nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/">Home</a> / <a href="/records/">Records</a> / {esc(record["title"])}</nav>'
        '<a class="brand" href="/">LINEAiGE</a><div class="eyebrow">LEARNING RESOURCE</div>'
        f'<h1>{esc(record["title"])}</h1><p class="lede">{esc(description)}</p>'
        '<section class="card"><h2>Course details</h2>'
        f'<p><small>PROVIDER</small><br>{esc(record.get("provider"))}</p>'
        f'<p><small>INSTITUTION</small><br>{esc(record.get("institution"))}</p>'
        f'<p><small>LEVEL</small><br>{esc(record.get("level"))}</p>'
        f'<p><small>ACCESS</small><br>{esc(record.get("access"))}</p>'
        f'<p><small>TOPICS</small><br>{esc(topics)}</p>'
        f'<div class="actions"><a href="{esc(record.get("courseUrl"))}" target="_blank" rel="noopener noreferrer external">OPEN COURSE</a></div>'
        '</section>'
        '<footer>Learning resources are contextual educational material and remain separate from primary historical evidence.'
        '<br><a href="/records/">Record index</a> · <a href="/methodology/">Evidence methodology</a> · <a href="/">Interactive LINEAiGE</a></footer>'
        '</main></body></html>'
    )


def ensure_course_pages(courses):
    root = ROOT / "learn"
    root.mkdir(parents=True, exist_ok=True)
    ids = {r["id"] for r in courses}
    for child in root.iterdir():
        if child.is_dir() and child.name not in ids:
            shutil.rmtree(child)
    for record in courses:
        path = root / record["id"] / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(course_page(record), encoding="utf-8")


def media_page(record: dict) -> str:
    rid = record["id"]
    canonical = f"{BASE}/context/{rid}/"
    description = meta_description(record.get("note") or record.get("title"))
    title = seo_title(record["title"])
    video = {
        "@type": "VideoObject",
        "name": record["title"],
        "description": description,
        "uploadDate": record.get("publishedDate"),
        "url": record.get("watchUrl"),
    }
    if record.get("embedUrl"):
        video["embedUrl"] = record["embedUrl"]
    schema = page_schema(
        canonical,
        record["title"] + " — LINEAiGE",
        description,
        [("Home", BASE + "/"), ("Records", BASE + "/records/"), (record["title"], canonical)],
        main_entity=video,
        date_modified=max_lastmod(record.get("publishedDate"), SEO_TEMPLATE_LASTMOD),
    )
    return (
        '<!doctype html><html lang="en"><head>'
        + head_markup(title=title, description=description, canonical=canonical, schema=schema)
        + '</head><body><main class="wrap">'
        f'<nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/">Home</a> / <a href="/records/">Records</a> / {esc(record["title"])}</nav>'
        '<a class="brand" href="/">LINEAiGE</a><div class="eyebrow">CONTEXT MEDIA</div>'
        f'<h1>{esc(record["title"])}</h1><p class="lede">{esc(description)}</p>'
        '<section class="card"><h2>Media details</h2>'
        f'<p><small>CREATOR</small><br>{esc(record.get("creator"))}</p>'
        f'<p><small>PUBLISHED</small><br>{esc(record.get("publishedDate"))}</p>'
        f'<p>{esc(record.get("note"))}</p>'
        f'<div class="actions"><a href="{esc(record.get("watchUrl"))}" target="_blank" rel="noopener noreferrer external">WATCH SOURCE</a></div>'
        '</section>'
        '<footer>Context media can help explain a verified record, but it is not automatically primary historical evidence.'
        '<br><a href="/records/">Record index</a> · <a href="/methodology/">Evidence methodology</a> · <a href="/">Interactive LINEAiGE</a></footer>'
        '</main></body></html>'
    )


def ensure_media_pages(media):
    root = ROOT / "context"
    root.mkdir(parents=True, exist_ok=True)
    ids = {r["id"] for r in media}
    for child in root.iterdir():
        if child.is_dir() and child.name not in ids:
            shutil.rmtree(child)
    for record in media:
        path = root / record["id"] / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(media_page(record), encoding="utf-8")


def homepage_jsonld(ai, precursors, futures, courses, media):
    today = build_date()
    description = (
        "Explore LINEAiGE: verified AI history beginning in 1956, documented prehistory and precursors, "
        "learning resources, and source-backed future announcements."
    )
    graph = [
        {
            "@type": "Organization",
            "@id": "https://barbph.com/#organization",
            "name": "BarbPH",
            "url": "https://barbph.com/",
        },
        {
            "@type": "WebSite",
            "@id": BASE + "/#website",
            "url": BASE + "/",
            "name": "LINEAiGE",
            "description": description,
            "publisher": {"@id": "https://barbph.com/#organization"},
            "inLanguage": "en",
        },
        {
            "@type": "CollectionPage",
            "@id": BASE + "/#webpage",
            "url": BASE + "/",
            "name": "LINEAiGE — Verified AI History, Precursors & Future Announcements",
            "description": description,
            "isPartOf": {"@id": BASE + "/#website"},
            "about": {"@type": "Thing", "name": "Artificial intelligence history"},
            "datePublished": "2026-09-20",
            "dateModified": today,
            "mainEntity": {"@id": BASE + "/#ai-history"},
        },
        {
            "@type": "ItemList",
            "@id": BASE + "/#precursors",
            "name": "Verified prehistory, foundations and precursors to artificial intelligence",
            "numberOfItems": len(precursors),
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": i,
                    "name": r["title"],
                    "url": f"{BASE}/record/{r['id']}/",
                }
                for i, r in enumerate(precursors, 1)
            ],
        },
        {
            "@type": "ItemList",
            "@id": BASE + "/#ai-history",
            "name": "Verified artificial-intelligence history from 1956 onward",
            "numberOfItems": len(ai),
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": i,
                    "name": r["title"],
                    "url": f"{BASE}/record/{r['id']}/",
                }
                for i, r in enumerate(ai, 1)
            ],
        },
        {
            "@type": "ItemList",
            "@id": BASE + "/#announced-future",
            "name": "Evidence-backed announced future AI milestones in LINEAiGE",
            "numberOfItems": len(futures),
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": i,
                    "name": r["title"],
                    "url": f"{BASE}/future/{r['id']}/",
                }
                for i, r in enumerate(futures, 1)
            ],
        },
        {
            "@type": "ItemList",
            "@id": BASE + "/#learning",
            "name": "Verified AI learning resources in LINEAiGE",
            "numberOfItems": len(courses),
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": i,
                    "name": r["title"],
                    "url": f"{BASE}/learn/{r['id']}/",
                }
                for i, r in enumerate(courses, 1)
            ],
        },
        {
            "@type": "ItemList",
            "@id": BASE + "/#context-media",
            "name": "Context media attached to LINEAiGE records",
            "numberOfItems": len(media),
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": i,
                    "name": r["title"],
                    "url": f"{BASE}/context/{r['id']}/",
                }
                for i, r in enumerate(media, 1)
            ],
        },
    ]
    return {"@context": "https://schema.org", "@graph": graph}


def update_homepage(ai, precursors, futures, courses, media):
    text = MAIN.read_text(encoding="utf-8")
    payload = json.dumps(
        homepage_jsonld(ai, precursors, futures, courses, media),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    text, count = re.subn(
        r'<script type="application/ld\+json">.*?</script>',
        f'<script type="application/ld+json">{payload}</script>',
        text,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise SystemExit("PUBLIC REBUILD FAILED: homepage JSON-LD block not found")
    fallback = json.dumps(futures, ensure_ascii=False, separators=(",", ":"))
    text, count = re.subn(
        r"const FUTURE_FALLBACK=.*?;\n",
        f"const FUTURE_FALLBACK={fallback};\n",
        text,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise SystemExit("PUBLIC REBUILD FAILED: FUTURE_FALLBACK block not found")
    MAIN.write_text(text, encoding="utf-8")


def max_lastmod(*values) -> str:
    days = [str(v)[:10] for v in values if v and re.match(r"^\d{4}-\d{2}-\d{2}", str(v))]
    return max(days) if days else SEO_TEMPLATE_LASTMOD


def methodology_lastmod() -> str:
    if not METHODOLOGY.exists():
        return SEO_TEMPLATE_LASTMOD
    text = METHODOLOGY.read_text(encoding="utf-8")
    match = re.search(r'"dateModified"\s*:\s*"(\d{4}-\d{2}-\d{2})"', text)
    return match.group(1) if match else build_date()


def update_sitemap(rows, futures, courses, media, lifecycle_lastmod=None):
    today = build_date()
    entries = [
        (BASE + "/", today),
        *[(f"{BASE}/learn/{r['id']}/", max_lastmod(r.get("verifiedAt"), SEO_TEMPLATE_LASTMOD)) for r in courses],
        *[(f"{BASE}/context/{r['id']}/", max_lastmod(r.get("publishedDate"), SEO_TEMPLATE_LASTMOD)) for r in media],
        (BASE + "/records/", today),
        (BASE + "/methodology/", methodology_lastmod()),
        *[(f"{BASE}/record/{r['id']}/", record_lastmod(r)) for r in rows],
        *[(f"{BASE}/future/{r['id']}/", max_lastmod(lifecycle_lastmod, r.get("announcedOn"), SEO_TEMPLATE_LASTMOD)) for r in futures],
    ]
    seen = set()
    unique_entries = []
    for url, lastmod in entries:
        if url in seen:
            continue
        seen.add(url)
        unique_entries.append((url, lastmod))
    xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    xml += [f"  <url><loc>{esc(url)}</loc><lastmod>{lastmod}</lastmod></url>" for url, lastmod in unique_entries]
    xml.append("</urlset>")
    SITEMAP.write_text("\n".join(xml) + "\n", encoding="utf-8")




def sitemap_html_path(url: str) -> Path:
    if url == BASE + "/":
        return MAIN
    relative = url.removeprefix(BASE).strip("/")
    return ROOT / relative / "index.html"


def validate_public_surfaces() -> dict:
    """Fail closed if the generated public SEO surface regresses."""
    sitemap_text = SITEMAP.read_text(encoding="utf-8")
    urls = re.findall(r"<loc>(.*?)</loc>", sitemap_text)
    if len(urls) != len(set(urls)):
        raise SystemExit("PUBLIC SEO VALIDATION FAILED: duplicate sitemap URLs")

    titles = {}
    descriptions = {}
    failures = []

    for url in urls:
        path = sitemap_html_path(url)
        if not path.exists():
            failures.append(f"{url}: missing HTML file")
            continue

        source = path.read_text(encoding="utf-8")
        title_match = re.search(r"<title>(.*?)</title>", source, re.S | re.I)
        desc_match = re.search(r'<meta name="description" content="([^"]*)"', source, re.I)
        canonical_match = re.search(r'<link rel="canonical" href="([^"]*)"', source, re.I)
        robots_match = re.search(r'<meta name="robots" content="([^"]*)"', source, re.I)

        title = clean_text(title_match.group(1)) if title_match else ""
        description = clean_text(desc_match.group(1)) if desc_match else ""
        canonical = clean_text(canonical_match.group(1)) if canonical_match else ""
        robots = clean_text(robots_match.group(1)).casefold() if robots_match else ""

        if not title:
            failures.append(f"{url}: missing title")
        if title.endswith(("…", "...")):
            failures.append(f"{url}: mechanically truncated title")
        if "LINEAiGE" not in title:
            failures.append(f"{url}: title missing LINEAiGE site name")

        if not description:
            failures.append(f"{url}: missing meta description")
        if description.endswith(("…", "...")):
            failures.append(f"{url}: mechanically truncated meta description")

        if canonical != url:
            failures.append(f"{url}: canonical mismatch ({canonical!r})")
        if "index" not in robots or "noindex" in robots:
            failures.append(f"{url}: invalid robots directive ({robots!r})")
        if len(re.findall(r"<h1\b", source, re.I)) != 1:
            failures.append(f"{url}: expected exactly one H1")
        if 'property="og:title"' not in source or 'property="og:description"' not in source:
            failures.append(f"{url}: missing Open Graph metadata")
        if 'name="twitter:card"' not in source:
            failures.append(f"{url}: missing Twitter card metadata")
        if 'application/ld+json' not in source:
            failures.append(f"{url}: missing JSON-LD")
        else:
            for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', source, re.S | re.I):
                try:
                    json.loads(html.unescape(block))
                except json.JSONDecodeError as exc:
                    failures.append(f"{url}: invalid JSON-LD ({exc})")

        if "/record/" in url:
            for marker in ("Why it matters", "Evidence & verification", "<h2>Sources</h2>", "Trace the chronology"):
                if marker not in source:
                    failures.append(f"{url}: missing record section {marker!r}")
            if 'property="og:type" content="article"' not in source:
                failures.append(f"{url}: historical record og:type must be article")
        if "/future/" in url:
            if "announced future" not in source.casefold():
                failures.append(f"{url}: future page does not clearly identify announced-future status")
            if 'property="og:type" content="article"' not in source:
                failures.append(f"{url}: future record og:type must be article")

        titles.setdefault(title, []).append(url)
        descriptions.setdefault(description, []).append(url)

    for title, matching in titles.items():
        if title and len(matching) > 1:
            failures.append(f"duplicate title across {len(matching)} pages: {title!r}")
    for description, matching in descriptions.items():
        if description and len(matching) > 1:
            failures.append(f"duplicate meta description across {len(matching)} pages")

    if failures:
        preview = "\n".join(f" - {item}" for item in failures[:40])
        suffix = "" if len(failures) <= 40 else f"\n - ... plus {len(failures) - 40} more"
        raise SystemExit(f"PUBLIC SEO VALIDATION FAILED ({len(failures)} issues):\n{preview}{suffix}")

    return {
        "urlsValidated": len(urls),
        "uniqueTitles": len(titles),
        "uniqueDescriptions": len(descriptions),
        "mechanicalTruncations": 0,
    }


def main():
    rows = recorded_events(load(EVENTS))
    precursors, ai = split_history(rows)
    future_payload = load(FUTURE)
    futures = future_events(future_payload)
    lifecycle_lastmod = future_payload.get("lifecycleUpdatedAt")
    courses = load(COURSES).get("items", [])
    media = load(MEDIA).get("items", [])

    if not ai or year_value(ai[0]) != 1956:
        raise SystemExit("PUBLIC REBUILD FAILED: AI history must begin in 1956")

    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(records_index_page(ai, precursors, futures, courses, media), encoding="utf-8")
    ensure_record_pages(rows, courses, media)
    ensure_future_pages(futures, lifecycle_lastmod)
    ensure_course_pages(courses)
    ensure_media_pages(media)
    update_homepage(ai, precursors, futures, courses, media)
    update_sitemap(rows, futures, courses, media, lifecycle_lastmod)
    seo_validation = validate_public_surfaces()

    print(
        json.dumps(
            {
                "seoValidation": seo_validation,
                "aiHistory": len(ai),
                "precursors": len(precursors),
                "allRecorded": len(rows),
                "future": len(futures),
                "courses": len(courses),
                "media": len(media),
                "sitemapUrls": 1 + len(courses) + len(media) + 2 + len(rows) + len(futures),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
