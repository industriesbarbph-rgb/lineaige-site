#!/usr/bin/env python3
from __future__ import annotations

import json
from calendar import monthrange
from datetime import date, datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FUTURE=ROOT/"data"/"future-announcements.json"
EVENTS=ROOT/"data"/"events.json"
RESOLVED=ROOT/"data"/"future-resolution-ledger.json"


def load(path,default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z")


def target_end(value):
    if not isinstance(value,str):
        return None
    value=value.strip()
    try:
        if len(value)==10:
            return date.fromisoformat(value)
        if len(value)==7 and value[4]=="-":
            y,m=map(int,value.split("-")); return date(y,m,monthrange(y,m)[1])
        if len(value)==4 and value.isdigit():
            return date(int(value),12,31)
        if len(value)==7 and value[4:6]=="-Q" and value[-1] in "1234":
            y=int(value[:4]); m=int(value[-1])*3; return date(y,m,monthrange(y,m)[1])
    except ValueError:
        return None
    return None


def main():
    today=date.today()
    future=load(FUTURE,{"schemaVersion":"1.0","records":[]})
    events=load(EVENTS,{"events":[]})
    resolved=load(RESOLVED,{"schemaVersion":"1.0","records":[]})

    future["cutoffMode"]="runtime-date"
    future["policy"]=(
        "Only evidence-backed announcements whose target milestone is unresolved are retained here. "
        "Lifecycle evaluation uses the actual run date, not the legacy stored cutoff. A target passing "
        "its horizon becomes DUE FOR CONFIRMATION, never completed history by date alone. Completion "
        "requires verified evidence and a canonical recorded event."
    )

    canonical_ids={
        e.get("id") for e in events.get("events",[])
        if e.get("recordType") in {"event","entry_point"}
        and e.get("verification",{}).get("state")=="verified"
    }
    resolved_ids={r.get("futureId") for r in resolved.get("records",[])}
    kept=[]; changed=0; resolved_now=0

    for record in future.get("records",[]):
        rid=record.get("id")
        if rid in canonical_ids:
            if rid not in resolved_ids:
                resolved.setdefault("records",[]).append({
                    "futureId":rid,
                    "canonicalId":rid,
                    "title":record.get("title"),
                    "resolvedAt":now_iso(),
                    "resolution":"verified canonical record exists with the same lineage identity",
                    "originalAnnouncement":record
                })
                resolved_ids.add(rid); resolved_now+=1
            continue

        end=target_end(record.get("targetDate"))
        due=bool(end and today>end)
        desired="DUE FOR CONFIRMATION" if due else "ANNOUNCED"
        lifecycle_state="verification-needed" if due else "scheduled"
        if record.get("status")!=desired or record.get("lifecycleState")!=lifecycle_state:
            record["status"]=desired
            record["lifecycleState"]=lifecycle_state
            changed+=1
        kept.append(record)

    future["records"]=kept
    if changed or resolved_now:
        future["lifecycleUpdatedAt"]=now_iso()
    if resolved_now:
        resolved["updatedAt"]=now_iso()

    save(FUTURE,future)
    save(RESOLVED,resolved)
    print(json.dumps({"runtimeDate":today.isoformat(),"future":len(kept),"stateChanges":changed,"resolved":resolved_now},indent=2))


if __name__=="__main__":
    main()
