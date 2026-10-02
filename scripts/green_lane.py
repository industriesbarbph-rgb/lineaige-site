#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "green-lane.json"
EVENTS = ROOT / "data" / "events.json"

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36 LINEAiGE-GreenLane/1.0"
)

MILESTONE_PATTERNS = [
    re.compile(r"\bwe(?:'re| are) (?:introducing|launching|releasing)\b", re.I),
    re.compile(r"\bwe (?:introduced|launched|released)\b", re.I),
    re.compile(r"\b(?:is|are) now available\b", re.I),
    re.compile(r"\bgeneral availability\b", re.I),
    re.compile(r"\bavailable today\b", re.I),
    re.compile(r"\blaunch(?:es|ed|ing)? today\b", re.I),
    re.compile(r"\breleas(?:e|es|ed|ing) today\b", re.I),
]
MODEL_TITLE = re.compile(
    r"\b(gpt[-‑\s]?\d|claude(?:\s+[a-z]+)?\s*\d|gemini(?:\s+[a-z0-9.]+)?|"
    r"gemma(?:\s*\d)?|llama(?:\s*\d)?|mistral|codestral|ministral|devstral|magistral|"
    r"qwen|deepseek|grok|aya|command|nemotron|lyria|alphagenome|weathernext|robotics)\b",
    re.I,
)
EXPLICIT_TITLE = re.compile(
    r"\b(release|released|launch|launched|general availability|now available)\b",
    re.I,
)
INTRO_PRODUCT_TITLE = re.compile(
    r"^introducing\b.*\b(model|agent|api|gpt|claude|gemini|gemma|llama|mistral|"
    r"qwen|deepseek|grok|aya|command|nemotron|lyria|robotics|weathernext|alphagenome)\b",
    re.I,
)
BLOCK_TITLE = re.compile(
    r"\b(policy|election|lawsuit|funding|partnering|partnership|hiring|program|watermark|"
    r"threat intelligence|wellbeing|responsible scaling|security report|standard|benchmark|"
    r"measurements|safeguard|verification program)\b",
    re.I,
)

def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def save(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def canon(url: str) -> str:
    p = urlparse(url)
    path = re.sub(r"/+$", "", p.path) or "/"
    return f"{p.scheme.lower()}://{p.netloc.lower()}{path}" + (f"?{p.query}" if p.query else "")

def fetch(url: str, limit: int = 1800000):
    req = Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml,application/rss+xml;q=0.9,*/*;q=0.5",
            "Accept-Language": "en-US,en;q=0.8",
        },
    )
    try:
        with urlopen(req, timeout=20) as response:
            return response.geturl(), response.read(limit)
    except Exception as first:
        try:
            cp = subprocess.run(
                ["curl", "--http2", "--fail", "--location", "--silent", "--show-error",
                 "--max-time", "20", "-A", UA, url],
                check=True, capture_output=True, timeout=24,
            )
            return url, cp.stdout[:limit]
        except Exception:
            raise first

class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self._href = None
        self._anchor = []
        self.in_title = False
        self.title = []
        self.in_h1 = False
        self.h1 = []
        self.text = []
        self.meta = {}
        self.times = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): v for k, v in attrs if k}
        tag = tag.lower()
        if tag == "a":
            self._href = a.get("href")
            self._anchor = []
        elif tag == "title":
            self.in_title = True
        elif tag == "h1":
            self.in_h1 = True
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            val = a.get("content")
            if key and val and key not in self.meta:
                self.meta[key] = val
        elif tag == "time" and a.get("datetime"):
            self.times.append(a["datetime"])

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "a" and self._href is not None:
            label = re.sub(r"\s+", " ", html.unescape(" ".join(self._anchor))).strip()
            self.links.append((self._href, label))
            self._href = None
            self._anchor = []
        elif tag == "title":
            self.in_title = False
        elif tag == "h1":
            self.in_h1 = False

    def handle_data(self, data):
        clean = re.sub(r"\s+", " ", html.unescape(data)).strip()
        if not clean:
            return
        self.text.append(clean)
        if self._href is not None:
            self._anchor.append(clean)
        if self.in_title:
            self.title.append(clean)
        if self.in_h1:
            self.h1.append(clean)

def parse_page(body: bytes) -> PageParser:
    parser = PageParser()
    parser.feed(body.decode("utf-8", "replace"))
    return parser

def iso_day(value):
    if not isinstance(value, str):
        return None
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", value.strip())
    if not m:
        return None
    try:
        parsed = date.fromisoformat(m.group(1))
    except ValueError:
        return None
    if parsed > date.today():
        return None
    return parsed.isoformat()

def visible_date(text: str):
    months = (
        "January|February|March|April|May|June|July|August|September|October|November|December|"
        "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
    )
    m = re.search(rf"\b({months})\.?\s+(\d{{1,2}}),\s+(20\d{{2}})\b", text)
    if not m:
        return None
    mon = m.group(1).replace(".", "")
    try:
        parsed = datetime.strptime(
            f"{mon} {m.group(2)} {m.group(3)}",
            "%B %d %Y" if len(mon) > 3 else "%b %d %Y",
        ).date()
    except ValueError:
        return None
    if parsed > date.today():
        return None
    return parsed.isoformat()

def published_date(parser: PageParser):
    for key in ("article:published_time", "date", "datepublished", "publish-date", "parsely-pub-date"):
        found = iso_day(parser.meta.get(key))
        if found:
            return found
    for value in parser.times:
        found = iso_day(value)
        if found:
            return found
    return visible_date(" ".join(parser.text[:120]))

def clean_title(parser: PageParser, fallback: str) -> str:
    choices = [parser.meta.get("og:title"), " ".join(parser.h1), " ".join(parser.title), fallback]
    for value in choices:
        if isinstance(value, str) and value.strip():
            title = re.sub(r"\s+", " ", html.unescape(value)).strip()
            title = re.sub(r"\s*[|—-]\s*(OpenAI|Anthropic|Google DeepMind|Google)\s*$", "", title, flags=re.I)
            return title[:180]
    return fallback[:180]

def allowed_url(url: str, source: dict) -> bool:
    p = urlparse(url)
    if p.scheme not in {"http", "https"}:
        return False
    if p.netloc.lower() not in {h.lower() for h in source["allowedHosts"]}:
        return False
    return any(p.path.startswith(prefix) for prefix in (source.get("pathPrefixes") or ["/"]))

def milestone(title: str, text: str) -> bool:
    if BLOCK_TITLE.search(title):
        return False
    strong_title = (
        EXPLICIT_TITLE.search(title)
        or INTRO_PRODUCT_TITLE.search(title)
        or MODEL_TITLE.search(title)
    )
    if not strong_title:
        return False
    # A model/product name in a headline is not enough. The release/launch/
    # introduction/availability language must appear near the top of the
    # first-party page so retrospective mentions cannot promote unrelated posts.
    return any(pattern.search(text[:4500]) for pattern in MILESTONE_PATTERNS)

def source_urls(events):
    urls = set()
    for event in events:
        for source in event.get("sources", []):
            url = source.get("url")
            if isinstance(url, str):
                urls.add(canon(url))
    return urls

def make_id(publisher: str, title: str, day: str, url: str, existing: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", f"{publisher} {title}".casefold()).strip("-")
    base = re.sub(r"-(openai|anthropic|google|google-deepmind)$", "", base)
    base = (base[:70].rstrip("-") or "milestone") + "-" + day[:4]
    rid = base
    if rid in existing:
        rid = f"{base}-{hashlib.sha1(canon(url).encode()).hexdigest()[:8]}"
    return rid

def human_date(day: str) -> str:
    d = date.fromisoformat(day)
    return f"{d.day} {d.strftime('%B %Y')}"

def main() -> None:
    cfg = load(CFG)
    doc = load(EVENTS)
    events = doc.get("events")
    if not isinstance(events, list):
        raise SystemExit("GREEN LANE FAILED: data/events.json has no events array")

    existing_ids = {e.get("id") for e in events if isinstance(e.get("id"), str)}
    known_urls = source_urls(events)
    additions = []
    checked = set()
    max_new = int(cfg.get("maxNewRecordsPerRun", 8))
    max_pages = int(cfg.get("maxPagesPerSource", 24))

    for source in cfg["sources"]:
        try:
            final_root, body = fetch(source["root"])
            root = parse_page(body)
        except Exception as exc:
            print(f"GREEN YELLOW: {source['id']} root unavailable: {type(exc).__name__}: {exc}")
            continue

        candidates = []
        if source.get("mode") == "rss":
            try:
                xml_root = ET.fromstring(body)
                for item in xml_root.findall(".//item")[:100]:
                    href = (item.findtext("link") or "").strip()
                    label = (item.findtext("title") or "").strip()
                    if not href:
                        continue
                    try:
                        url = canon(href)
                    except Exception:
                        continue
                    if url in checked or url in known_urls or not allowed_url(url, source):
                        continue
                    checked.add(url)
                    candidates.append((url, label))
            except Exception as exc:
                print(f"GREEN YELLOW: {source['id']} feed parse failed: {type(exc).__name__}: {exc}")
                continue
        else:
            for href, label in root.links:
                try:
                    url = canon(urljoin(final_root, href))
                except Exception:
                    continue
                if url == canon(final_root) or url in checked or url in known_urls:
                    continue
                if not allowed_url(url, source):
                    continue
                checked.add(url)
                candidates.append((url, label))

        for url, label in candidates[:max_pages]:
            if len(additions) >= max_new:
                break
            try:
                final_url, page_body = fetch(url)
                final_url = canon(final_url)
                if final_url in known_urls or not allowed_url(final_url, source):
                    continue
                page = parse_page(page_body)
            except Exception as exc:
                print(f"GREEN YELLOW: fetch failed {url}: {type(exc).__name__}: {exc}")
                continue

            title = clean_title(page, label or final_url.rsplit("/", 1)[-1])
            day = published_date(page)
            text = " ".join(page.text)
            if not day:
                print(f"GREEN YELLOW: no exact publication date: {title}")
                continue
            if not milestone(title, text):
                continue

            rid = make_id(source["publisher"], title, day, final_url, existing_ids)
            existing_ids.add(rid)
            known_urls.add(final_url)
            parsed_day = date.fromisoformat(day)
            summary = (
                f"{source['publisher']} published the first-party milestone “{title}” on "
                f"{parsed_day.strftime('%B')} {parsed_day.day}, {parsed_day.year}; the source states an "
                "introduction, release, launch, or availability event."
            )
            record = {
                "id": rid,
                "recordType": "event",
                "title": title,
                "displayDate": human_date(day),
                "eventDate": day,
                "datePrecision": "day",
                "temporalState": "recorded",
                "status": "VERIFIED RECORD",
                "summary": summary,
                "significance": "A dated first-party AI milestone admitted by LINEAiGE's deterministic GREEN lane.",
                "people": [],
                "organizations": [source["publisher"]],
                "technologies": [],
                "verification": {
                    "state": "verified",
                    "factualClaim": True,
                    "confidence": "high",
                    "note": (
                        "Autonomous GREEN admission: exact publication date, trusted first-party host, "
                        "release/launch/introduction/availability language, no inferred geography, ancestry, "
                        "influence, causality, priority, or relationship edge."
                    ),
                    "lastVerified": now_iso(),
                },
                "sources": [{
                    "title": title,
                    "url": final_url,
                    "publisher": source["publisher"],
                    "publishedDate": day,
                    "sourceType": "official-announcement",
                    "primary": True,
                    "archivedUrl": None
                }],
                "relationships": [],
                "corrections": [],
                "contributor": None,
                "entryOrigin": "lineaige"
            }
            additions.append(record)
            print(f"GREEN ADMIT: {day} | {source['publisher']} | {title}")

        if len(additions) >= max_new:
            break

    if additions:
        events.extend(additions)
        def sort_key(event):
            if isinstance(event.get("eventDate"), str):
                return event["eventDate"]
            if isinstance(event.get("eventMonth"), str):
                return event["eventMonth"] + "-01"
            if event.get("eventYear") is not None:
                return f"{event['eventYear']}-01-01"
            return "9999-12-31"
        events.sort(key=sort_key)
        save(EVENTS, doc)

    print(json.dumps({"greenAdded": len(additions), "canonicalTotal": len(events)}, indent=2))

if __name__ == "__main__":
    main()
