"""TASK 006A - READ-ONLY OKX LIQUIDATION ENDPOINT SHAPE AUDIT

Settles, from fresh measurement, whether the OKX `limit=100` parameter truncates
liquidation EVENTS.

Task 006 claimed it did and called it urgent. That claim was wrong, and the repository
had already disproved it in commit 812ac5f on 2026-07-31:

    "The audit flagged a 193-event minute as a possible truncation of the 100-event cap.
     That was wrong: the cap applies to the outer instrument array, not to events, and a
     single call returns about 1,500 events spanning 22 hours. Nothing was truncated."

`recorder/derivs_recorder.py` already states the same measured behaviour in its docstring
and already paginates backwards with `after` as a safety net. Task 006 propagated a stale
test in `study/data_readiness.py` without checking either. This script re-measures so the
conclusion rests on today's data rather than on either claim.

STRICTLY READ-ONLY. It issues GET requests to a public endpoint, writes two files under
study/results/, and changes nothing else. It does not modify the recorder, does not alter
its polling interval, does not touch the live bot, and does not download price data or
inspect any post-event outcome.
"""
import os
import json
import time
import datetime as dt
import urllib.request

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RES = os.path.join(HERE, "results")
os.makedirs(RES, exist_ok=True)
LIQ_CSV = os.path.join(ROOT, "recorder", "data", "liquidations_BTC.csv")

OUT_TXT = os.path.join(RES, "okx_liquidation_endpoint_audit.txt")
OUT_JSON = os.path.join(RES, "okx_liquidation_endpoint_audit.json")

URL = ("https://www.okx.com/api/v5/public/liquidation-orders"
       "?instType=SWAP&uly=BTC-USDT&state=filled&limit=100")
UA = {"User-Agent": "Mozilla/5.0 (research)"}

LOG = []


def say(s=""):
    print(s, flush=True)
    LOG.append(s)


def get(url, timeout=25):
    t0 = time.time()
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        code = r.status
        body = json.loads(r.read().decode())
    return code, body, (time.time() - t0)


def shape(body):
    outer = body.get("data") or []
    per_outer, events = [], []
    for inst in outer:
        det = inst.get("details") or []
        per_outer.append(len(det))
        iid = inst.get("instId") or inst.get("uly") or "BTC-USDT-SWAP"
        for ev in det:
            try:
                ts = int(ev.get("ts") or ev.get("time"))
            except (TypeError, ValueError):
                continue
            events.append({"ts": ts, "instId": iid, "side": ev.get("side", ""),
                           "posSide": ev.get("posSide", ""), "sz": ev.get("sz", ""),
                           "bkPx": ev.get("bkPx", "")})
    return outer, per_outer, events


say("=" * 96)
say("TASK 006A - OKX LIQUIDATION ENDPOINT SHAPE AUDIT (READ-ONLY)")
say("=" * 96)
req_utc = dt.datetime.now(dt.timezone.utc)
say(f"request UTC        : {req_utc:%Y-%m-%d %H:%M:%S}Z")
say(f"url                : {URL}")
say("")

result = {"request_utc": req_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), "url": URL}

try:
    code, body, elapsed = get(URL)
except Exception as ex:
    say(f"REQUEST FAILED: {type(ex).__name__}: {ex}")
    result["error"] = f"{type(ex).__name__}: {ex}"
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(LOG) + "\n")
    raise SystemExit(1)

outer, per_outer, events = shape(body)
api_code = str(body.get("code"))
say("1. SINGLE RESPONSE SHAPE")
say(f"  http status          : {code}")
say(f"  api code             : {api_code}  ({'ok' if api_code == '0' else 'ERROR'})")
say(f"  elapsed              : {elapsed:.2f}s")
say(f"  outer `data` objects : {len(outer)}   <- this is what limit=100 caps")
say(f"  max details in one outer object : {max(per_outer) if per_outer else 0}")
say(f"  TOTAL events across all details : {len(events)}")
say("")

result.update({"http_status": code, "api_code": api_code,
               "outer_data_objects": len(outer),
               "max_details_in_one_outer": max(per_outer) if per_outer else 0,
               "total_detail_events": len(events)})

if events:
    ts = pd.Series([e["ts"] for e in events])
    t_first = pd.to_datetime(ts.min(), unit="ms", utc=True)
    t_last = pd.to_datetime(ts.max(), unit="ms", utc=True)
    span_h = (t_last - t_first).total_seconds() / 3600.0
    say("2. TIME COVERAGE OF ONE RESPONSE")
    say(f"  earliest event : {t_first:%Y-%m-%d %H:%M:%S}Z")
    say(f"  latest event   : {t_last:%Y-%m-%d %H:%M:%S}Z")
    say(f"  span           : {span_h:,.2f} hours")
    say("")
    result.update({"earliest_event_utc": t_first.strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "latest_event_utc": t_last.strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "span_hours_one_response": round(span_h, 3)})

gt100 = len(events) > 100
say("3. THE DECISIVE TEST")
say(f"  more than 100 total detail events in ONE response? : {gt100}")
if gt100:
    say(f"    -> {len(events)} events returned from a single limit=100 call.")
    say("    -> limit=100 therefore caps the OUTER instrument array, NOT events.")
    say("    -> THE TRUNCATION CLAIM IS DISPROVED by direct measurement.")
else:
    say(f"    -> only {len(events)} events; inconclusive from this call alone.")
say("")
result["more_than_100_detail_events"] = bool(gt100)

# ---- does `after` pagination reach older material?
say("4. `after` PAGINATION")
older_ok = None
if events:
    oldest = int(min(e["ts"] for e in events))
    try:
        code2, body2, _ = get(URL + f"&after={oldest}")
        _o2, _p2, ev2 = shape(body2)
        if ev2:
            t2 = pd.to_datetime(min(e["ts"] for e in ev2), unit="ms", utc=True)
            older_ok = min(e["ts"] for e in ev2) < oldest
            say(f"  page 2 events        : {len(ev2)}")
            say(f"  page 2 earliest      : {t2:%Y-%m-%d %H:%M:%S}Z")
            say(f"  reaches OLDER material than page 1 : {older_ok}")
            result.update({"page2_events": len(ev2),
                           "page2_earliest_utc": t2.strftime("%Y-%m-%dT%H:%M:%SZ"),
                           "after_pagination_reaches_older": bool(older_ok)})
        else:
            say("  page 2 returned no events")
            result["page2_events"] = 0
    except Exception as ex:
        say(f"  pagination probe failed: {type(ex).__name__}: {ex}")
        result["pagination_error"] = str(ex)
say("")

# ---- overlap with what is already stored
say("5. OVERLAP WITH STORED DATA (dedup sanity)")
if os.path.isfile(LIQ_CSV) and events:
    st = pd.read_csv(LIQ_CSV)
    stored = set(st["ts_ms"].astype(str) + "|" + st["side"].astype(str) + "|"
                 + st["posSide"].astype(str) + "|" + st["sz"].astype(str) + "|"
                 + st["bkPx"].astype(str))
    live = [f"{e['ts']}|{e['side']}|{e['posSide']}|{e['sz']}|{e['bkPx']}"
            for e in events]
    seen = sum(1 for k in live if k in stored)
    say(f"  events in this response      : {len(live)}")
    say(f"  already stored (composite key): {seen}  ({seen/max(len(live),1)*100:.1f}%)")
    say(f"  new since last poll          : {len(live) - seen}")
    say("  -> a high overlap is expected and is the dedup working, not a fault")
    result.update({"events_in_response": len(live), "already_stored": seen,
                   "new_since_last_poll": len(live) - seen})
say("")

say("6. VERDICT ON TRUNCATION")
evidence = []
if gt100:
    evidence.append(f"a single limit=100 call returned {len(events)} events")
if events and span_h > 2:
    evidence.append(f"one response spans {span_h:.1f} hours")
if older_ok:
    evidence.append("`after` pagination reaches strictly older material")
if evidence:
    say("  NO evidence of event truncation. Measured this run:")
    for e in evidence:
        say(f"    - {e}")
    say("  The 100-event cap applies to the OUTER instrument array. Task 006's urgent")
    say("  warning was incorrect and is withdrawn. The 60-second poll interval is")
    say("  comfortable, not marginal, and must NOT be shortened on this basis.")
    result["truncation_evidence_found"] = False
else:
    say("  Inconclusive this run - not the same as evidence of truncation.")
    result["truncation_evidence_found"] = None
say("")
say("READ-ONLY: no recorder file, polling interval, live process or trade was changed.")
say("No price data was downloaded and no post-event outcome was inspected.")

with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2)
with open(OUT_TXT, "w", encoding="utf-8") as f:
    f.write("\n".join(LOG) + "\n")
print(f"\njson -> {OUT_JSON}")
print(f"txt  -> {OUT_TXT}")
