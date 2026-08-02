"""TASK 004 - OFFICIAL FX POLICY-RATE DATA PANEL

Builds and audits the BIS central bank policy-rate data needed for the next strategy
family. DATA ONLY. This script tests no trading performance, chooses no lookback or
threshold, recommends no trade rule, touches no order and does not modify the live bot.

================================================================================
SOURCE - official BIS only
================================================================================
BIS Data Portal, dataflow BIS:WS_CBPOL(1.0) "Central bank policy rates",
flat CSV bulk download:

    https://data.bis.org/static/bulk/WS_CBPOL_csv_flat.zip

No substitute source is permitted. If the file cannot be downloaded or parsed the
script STOPS and says so rather than quietly reaching for FRED or a web scrape.

The archive holds one 469 MB CSV containing BOTH monthly (M) and daily (D) frequency
rows for every economy BIS covers. It is streamed and filtered rather than loaded, and
the full raw download stays in a gitignored directory - only the filtered panel and the
source metadata are committed.

The eight series used are the BIS designated main policy rate for each economy,
selected by REF_AREA and FREQ=D. No choice among competing national rates was made,
and none could be made on trading results because no returns are computed here.

    AUD  AU  Reserve Bank of Australia
    CAD  CA  Bank of Canada
    CHF  CH  Swiss National Bank
    EUR  XM  European Central Bank        (euro area)
    GBP  GB  Bank of England
    JPY  JP  Bank of Japan
    NZD  NZ  Reserve Bank of New Zealand
    USD  US  US Federal Reserve System

================================================================================
EFFECTIVE-DATE AND FORWARD-FILL RULES
================================================================================
The single rule that matters: on any calendar date d a currency's policy rate is the
value of the LAST observation whose official observation date is <= d.

  * a rate change is never moved earlier than its official date;
  * forward fill happens only after an observation becomes effective;
  * nothing is backward-filled before a currency's first observation;
  * no future publication or effective value is used on an earlier date;
  * negative rates and legitimate zero rates are preserved exactly;
  * values are kept as published, in per cent per year, without rounding.

Every panel row records which observation date supplied its value and whether that row
was forward-filled, so staleness is visible per cell rather than assumed.

================================================================================
WHAT IS DELIBERATELY NOT DONE
================================================================================
The Exness swap comparison at the end is a CURRENT DATED DIAGNOSTIC. The 2026-08-02
broker snapshot is never applied to any historical date, and a policy-rate differential
is not treated as equal to a retail CFD swap - the whole point of that section is to
measure how far apart they are.
"""
import os
import io
import csv
import json
import zipfile
import hashlib
import datetime as dt

import numpy as np
import pandas as pd

import urllib.request          # stdlib: this box has no `requests`

# ----------------------------------------------------------------- config
BIS_URL = "https://data.bis.org/static/bulk/WS_CBPOL_csv_flat.zip"
CSV_IN_ZIP = "WS_CBPOL_csv_flat.csv"
PANEL_START = pd.Timestamp("2010-01-01")

# BIS REF_AREA -> currency, with the economy label BIS itself uses
AREA2CCY = {"AU": "AUD", "CA": "CAD", "CH": "CHF", "XM": "EUR",
            "GB": "GBP", "JP": "JPY", "NZ": "NZD", "US": "USD"}
CCYS = ["AUD", "CAD", "CHF", "EUR", "GBP", "JPY", "NZD", "USD"]

# coverage windows this project cares about
WINDOWS = {
    "2010_onward": pd.Timestamp("2010-01-01"),
    "exness_D1_2018": pd.Timestamp("2018-07-03"),
    "canonical_2021_08": pd.Timestamp("2021-08-02"),
}

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
EXT = os.path.join(DATA, "external")
RAWDIR = os.path.join(EXT, "raw")
RES = os.path.join(HERE, "results")
for d in (DATA, EXT, RAWDIR, RES):
    os.makedirs(d, exist_ok=True)

RAW_ZIP = os.path.join(RAWDIR, "WS_CBPOL_csv_flat.zip")
OUT_DAILY = os.path.join(DATA, "fx_policy_rates_daily.csv")
OUT_LONG = os.path.join(DATA, "fx_policy_rates_long.csv")
OUT_SNAP = os.path.join(DATA, "fx_policy_rate_rebalance_snapshots.csv")
OUT_META = os.path.join(EXT, "bis_policy_rates_source.json")
OUT_AUDIT = os.path.join(RES, "fx_policy_rate_data_audit.csv")
OUT_SWAP = os.path.join(RES, "fx_policy_rate_swap_snapshot.csv")
OUT_REPORT = os.path.join(RES, "fx_policy_rate_data_report.txt")
UNIV = os.path.join(RES, "fx_universe_audit.csv")

LOG = []


def say(s=""):
    print(s, flush=True)
    LOG.append(s)


def fail(msg):
    """Stop loudly. The spec forbids silently falling back to another source."""
    say("")
    say("!" * 100)
    say(f"STOPPING: {msg}")
    say("The official BIS file could not be downloaded or interpreted reliably.")
    say("No substitute source was used. Nothing was written.")
    say("!" * 100)
    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(LOG) + "\n")
    raise SystemExit(1)


# ============================================================ 1. acquire
say("=" * 100)
say("TASK 004 - OFFICIAL FX POLICY-RATE DATA PANEL")
say("=" * 100)
say(f"generated : {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M:%S} UTC")
say("")

def bis_headers():
    """HTTP headers for the bulk file, for the BIS release date. Stdlib only."""
    try:
        req = urllib.request.Request(BIS_URL, method="HEAD")
        with urllib.request.urlopen(req, timeout=90) as r:
            return {k.lower(): v for k, v in r.headers.items()}
    except Exception as ex:
        say(f"  (header fetch failed: {type(ex).__name__}: {ex})")
        return {}


retrieved_utc = None
http_headers = bis_headers()
if not os.path.isfile(RAW_ZIP):
    say(f"downloading {BIS_URL} ...")
    try:
        with urllib.request.urlopen(BIS_URL, timeout=600) as r:
            payload = r.read()
            http_headers = {k.lower(): v for k, v in r.headers.items()}
        with open(RAW_ZIP, "wb") as f:
            f.write(payload)
        retrieved_utc = dt.datetime.now(dt.timezone.utc)
    except Exception as ex:
        fail(f"download failed: {type(ex).__name__}: {ex}")
else:
    say(f"using already-downloaded raw file: {RAW_ZIP}")
    retrieved_utc = dt.datetime.fromtimestamp(os.path.getmtime(RAW_ZIP),
                                              dt.timezone.utc)

sha256 = hashlib.sha256(open(RAW_ZIP, "rb").read()).hexdigest()
size_bytes = os.path.getsize(RAW_ZIP)
release_date = http_headers.get("last-modified") or http_headers.get("Last-Modified")

say(f"  sha-256          : {sha256}")
say(f"  size             : {size_bytes:,} bytes")
say(f"  retrieved (UTC)  : {retrieved_utc:%Y-%m-%d %H:%M:%S}")
say(f"  BIS release date : {release_date or 'unavailable from HTTP headers'}")
say("")

# ============================================================ 2. filter
say("streaming and filtering the bulk CSV (daily frequency, eight economies)...")
rows, meta, freq_seen, area_seen = [], {}, {}, set()
try:
    z = zipfile.ZipFile(RAW_ZIP)
    if CSV_IN_ZIP not in z.namelist():
        fail(f"{CSV_IN_ZIP} not inside the archive; found {z.namelist()}")
    with z.open(CSV_IN_ZIP) as fh:
        rd = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace"))
        need = ["FREQ:Frequency", "REF_AREA:Reference area",
                "TIME_PERIOD:Time period or range", "OBS_VALUE:Observation Value"]
        missing = [c for c in need if c not in (rd.fieldnames or [])]
        if missing:
            fail(f"BIS layout changed - missing columns {missing}")
        for row in rd:
            fr = row["FREQ:Frequency"].split(":")[0].strip()
            ar = row["REF_AREA:Reference area"].split(":")[0].strip()
            freq_seen[fr] = freq_seen.get(fr, 0) + 1
            if fr != "D" or ar not in AREA2CCY:
                continue
            area_seen.add(ar)
            v = row["OBS_VALUE:Observation Value"].strip()
            if v == "":
                continue
            try:
                val = float(v)
            except ValueError:
                continue
            rows.append((ar, row["TIME_PERIOD:Time period or range"].strip(), val))
            if ar not in meta:
                meta[ar] = {
                    "ref_area": row["REF_AREA:Reference area"],
                    "unit_measure": row.get("UNIT_MEASURE:Unit of measure", ""),
                    "unit_mult": row.get("UNIT_MULT:Unit Multiplier", ""),
                    "decimals": row.get("DECIMALS:Decimals", ""),
                    "source_ref": row.get("SOURCE_REF:Publication Source", ""),
                    "title": row.get("TITLE:Title", ""),
                    "compilation": row.get("COMPILATION:Compilation", ""),
                    "supp_info_breaks": row.get("SUPP_INFO_BREAKS:Supplemental "
                                                "information and breaks", ""),
                    "time_format": row.get("TIME_FORMAT:Time Format", ""),
                }
except zipfile.BadZipFile:
    fail("the downloaded file is not a valid zip archive")

if not rows:
    fail("no daily observations parsed for any of the eight economies")
missing_areas = set(AREA2CCY) - area_seen
if missing_areas:
    fail(f"BIS daily series absent for {sorted(missing_areas)}")

src = pd.DataFrame(rows, columns=["area", "obs_date", "rate"])
src["obs_date"] = pd.to_datetime(src["obs_date"], errors="coerce")
if src["obs_date"].isna().any():
    fail("unparseable TIME_PERIOD values in the daily rows")
src["currency"] = src["area"].map(AREA2CCY)
src = src.sort_values(["currency", "obs_date"]).reset_index(drop=True)

say(f"  frequencies in file : {freq_seen}")
say(f"  daily rows kept     : {len(src):,} across {src['currency'].nunique()} currencies")
latest_ref = src["obs_date"].max()
say(f"  latest reference date: {latest_ref:%Y-%m-%d}")
say("")

# ============================================================ 3. panel
say("building the daily panel (forward fill only after an observation is effective)")
end = latest_ref
cal = pd.date_range(PANEL_START, end, freq="D")
wide = pd.DataFrame({"date": cal}).set_index("date")
long_rows = []
first_obs = {}

for ccy in CCYS:
    s = src[src["currency"] == ccy].drop_duplicates(subset="obs_date", keep="last")
    s = s.set_index("obs_date")["rate"].sort_index()
    first_obs[ccy] = s.index.min()
    # value in force on date d = last observation with obs_date <= d
    vals = s.reindex(s.index.union(cal)).ffill().reindex(cal)
    obsd = pd.Series(s.index, index=s.index).reindex(
        s.index.union(cal)).ffill().reindex(cal)
    # never backward-fill before this currency's first observation
    before = cal < first_obs[ccy]
    vals[before] = np.nan
    obsd[before] = pd.NaT
    wide[ccy] = vals.values
    ff = ~cal.isin(s.index)
    long_rows.append(pd.DataFrame({
        "date": cal, "currency": ccy, "economy": meta[
            [a for a, c in AREA2CCY.items() if c == ccy][0]]["ref_area"],
        "policy_rate_pct": vals.values,
        "bis_series_id": f"BIS:WS_CBPOL(1.0):D.{[a for a,c in AREA2CCY.items() if c==ccy][0]}",
        "source_observation_date": obsd.values,
        "is_forward_filled": ff,
        "source_release_date": release_date or "",
    }))

wide = wide.reset_index()
long = pd.concat(long_rows, ignore_index=True)
long = long[long["policy_rate_pct"].notna()]

wide.to_csv(OUT_DAILY, index=False)
long.to_csv(OUT_LONG, index=False)
say(f"  daily wide panel : {len(wide):,} calendar dates x {len(CCYS)} currencies")
say(f"  long panel       : {len(long):,} rows")
say(f"  any NaN in wide  : {int(wide[CCYS].isna().sum().sum())}")
say("")


# ============================================================ 4. snapshots
def first_monday(y, m):
    d = dt.date(y, m, 1)
    while d.weekday() != 0:
        d += dt.timedelta(days=1)
    return pd.Timestamp(d)


say("building monthly rebalance snapshots (first Monday, cutoff = preceding Friday)")
snaps = []
for per in pd.period_range(PANEL_START, end, freq="M"):
    fm = first_monday(per.year, per.month)
    if fm > end:
        continue
    cutoff = fm - pd.Timedelta(days=3)          # the completed Friday before it
    for ccy in CCYS:
        s = src[(src["currency"] == ccy) & (src["obs_date"] <= cutoff)]
        if not len(s):
            continue
        last = s.iloc[-1]
        snaps.append({
            "rebalance_month": str(per), "first_monday": fm.date(),
            "information_cutoff_friday": cutoff.date(), "currency": ccy,
            "policy_rate_pct": last["rate"],
            "source_observation_date": last["obs_date"].date(),
            "value_age_days": int((cutoff - last["obs_date"]).days),
        })
snap = pd.DataFrame(snaps)
snap.to_csv(OUT_SNAP, index=False)
n_months = snap["rebalance_month"].nunique()
say(f"  snapshots: {len(snap):,} rows over {n_months} months "
    f"({snap['first_monday'].min()} -> {snap['first_monday'].max()})")
say(f"  complete months (all 8 currencies): "
    f"{int((snap.groupby('rebalance_month').size() == 8).sum())}/{n_months}")
say(f"  value age days: median {snap['value_age_days'].median():.0f}, "
    f"max {snap['value_age_days'].max()}")
say("")

# ============================================================ 5. audit
say("auditing each currency")
aud = []
for ccy in CCYS:
    area = [a for a, c in AREA2CCY.items() if c == ccy][0]
    s = src[src["currency"] == ccy].drop_duplicates(subset="obs_date", keep="last")
    s = s.set_index("obs_date")["rate"].sort_index()
    dup = int(src[src["currency"] == ccy]["obs_date"].duplicated().sum())
    chg = s.diff().fillna(0)
    changes = chg[chg != 0]
    gaps = s.index.to_series().diff().dt.days.dropna()
    w = wide.set_index("date")[ccy]
    ffdays = int(w.notna().sum() - s.index.isin(wide["date"]).sum())
    row = {
        "currency": ccy, "economy": meta[area]["ref_area"],
        "bis_series_id": f"BIS:WS_CBPOL(1.0):D.{area}",
        "source_ref": meta[area]["source_ref"],
        "unit_measure": meta[area]["unit_measure"],
        "first_observation": s.index.min().date(), "last_observation": s.index.max().date(),
        "n_observations": int(len(s)), "duplicates": dup,
        "n_forward_filled_days": ffdays,
        "longest_stale_interval_days": int(gaps.max()) if len(gaps) else 0,
        "median_gap_days": float(gaps.median()) if len(gaps) else np.nan,
        "min_rate": float(s.min()), "max_rate": float(s.max()),
        "n_rate_changes": int(len(changes)),
        "n_negative_obs": int((s < 0).sum()),
        "n_zero_obs": int((s == 0).sum()),
        "negative_period": (f"{s[s<0].index.min().date()}..{s[s<0].index.max().date()}"
                            if (s < 0).any() else ""),
        "zero_period": (f"{s[s==0].index.min().date()}..{s[s==0].index.max().date()}"
                        if (s == 0).any() else ""),
        "latest_rate": float(s.iloc[-1]),
        "supp_info_breaks": (meta[area]["supp_info_breaks"] or "")[:200],
    }
    up = changes.nlargest(5)
    dn = changes.nsmallest(5)
    row["top5_increases"] = "; ".join(f"{d.date()}:{v:+.2f}" for d, v in up.items())
    row["top5_decreases"] = "; ".join(f"{d.date()}:{v:+.2f}" for d, v in dn.items())
    for wname, wstart in WINDOWS.items():
        row[f"covers_{wname}"] = bool(s.index.min() <= wstart)
        seg = w[w.index >= wstart]
        row[f"gaps_{wname}"] = int(seg.isna().sum())
    # Stale intervals INSIDE the panel window matter far more than the all-history
    # maximum: a multi-year hole means the panel carries one stale number across a
    # period in which policy actually moved. Reported per currency, and the offending
    # intervals are listed, because forward fill makes them invisible in the wide panel.
    sw_ = s[s.index >= PANEL_START]
    g2 = sw_.index.to_series().diff().dt.days.dropna()
    row["longest_stale_in_panel_days"] = int(g2.max()) if len(g2) else 0
    long_gaps = g2[g2 > 90]
    row["n_stale_intervals_over_90d_in_panel"] = int(len(long_gaps))
    row["stale_intervals_over_90d"] = "; ".join(
        f"{(d - pd.Timedelta(days=int(v))).date()}..{d.date()}({int(v)}d)"
        for d, v in long_gaps.items())
    aud.append(row)
audit = pd.DataFrame(aud)
audit.to_csv(OUT_AUDIT, index=False)
say(audit[["currency", "first_observation", "last_observation", "n_observations",
           "n_rate_changes", "min_rate", "max_rate", "latest_rate",
           "longest_stale_interval_days", "longest_stale_in_panel_days"]].to_string(
               index=False))
say("")
_bad = audit[audit["n_stale_intervals_over_90d_in_panel"] > 0]
if len(_bad):
    say("  !! STALE INTERVALS LONGER THAN 90 DAYS INSIDE THE 2010+ PANEL")
    for _, r in _bad.iterrows():
        say(f"     {r['currency']}: {r['stale_intervals_over_90d']}")
    say("     Forward fill holds one value across these, which is the rule as specified,")
    say("     but it means the panel shows a constant rate where the official series")
    say("     simply has no observation. Flagged rather than patched.")
else:
    say("  no stale interval longer than 90 days inside the 2010+ panel")
say("")

# ============================================================ 6. swap comparison
say("current Exness swap comparison (dated diagnostic, 2026-08-02 snapshot)")
u = pd.read_csv(UNIV)
sel = u[u["selected"] == True]                                          # noqa: E712
ex = sel[(sel["revised_risk_pct_of_979"] <= 1.50) & (sel["census_exposure_x"] <= 2.00)
         & (sel["census_spread_pct_atr"] <= 6.00) & (sel["both_sides"] == True)]
pairs = sorted(ex["symbol"].tolist())
latest = {c: float(wide[c].iloc[-1]) for c in CCYS}
say(f"  latest BIS policy rates: "
    + ", ".join(f"{c} {latest[c]:.2f}%" for c in CCYS))

sw = []
for p in pairs:
    b, q = p[:3], p[3:6]
    if b not in latest or q not in latest:
        continue
    r = ex[ex["symbol"] == p].iloc[0]
    tl = latest[b] - latest[q]
    ts = latest[q] - latest[b]
    # broker annual carry, positive = you RECEIVE (cost snapshot is positive = you pay)
    bl = -float(r["annual_cost_long_pct_snapshot"])
    bs = -float(r["annual_cost_short_pct_snapshot"])
    sw.append({
        "pair": p, "base": b, "quote": q,
        "policy_rate_base_pct": latest[b], "policy_rate_quote_pct": latest[q],
        "theoretical_long_differential": tl, "theoretical_short_differential": ts,
        "exness_swap_long_points": r["swap_long"], "exness_swap_short_points": r["swap_short"],
        "broker_annual_carry_long_pct": bl, "broker_annual_carry_short_pct": bs,
        "sign_agree_long": bool(np.sign(tl) == np.sign(bl)) if bl != 0 else False,
        "sign_agree_short": bool(np.sign(ts) == np.sign(bs)) if bs != 0 else False,
        "both_directions_cost": bool(bl < 0 and bs < 0),
        "markup_long_pct": tl - bl,
        "markup_short_pct": ts - bs,
        "theoretical_positive_side": ("long" if tl > 0 else "short" if ts > 0 else "flat"),
        "broker_pays_that_side": bool((tl > 0 and bl > 0) or (ts > 0 and bs > 0)),
    })
swap = pd.DataFrame(sw)
swap.to_csv(OUT_SWAP, index=False)

n_both_cost = int(swap["both_directions_cost"].sum())
n_pos_ok = int(swap["broker_pays_that_side"].sum())
say(f"  pairs compared                          : {len(swap)}")
say(f"  sign agrees, long side                  : {int(swap['sign_agree_long'].sum())}/{len(swap)}")
say(f"  sign agrees, short side                 : {int(swap['sign_agree_short'].sum())}/{len(swap)}")
say(f"  BOTH directions charge a cost           : {n_both_cost}/{len(swap)}")
say(f"  theoretical positive-carry side is also")
say(f"    positive under the broker snapshot    : {n_pos_ok}/{len(swap)}")
say(f"  median markup, long  side (theory-broker): {swap['markup_long_pct'].median():.2f} pp")
say(f"  median markup, short side (theory-broker): {swap['markup_short_pct'].median():.2f} pp")
say("")
say(swap[["pair", "theoretical_long_differential", "broker_annual_carry_long_pct",
          "broker_annual_carry_short_pct", "both_directions_cost",
          "theoretical_positive_side", "broker_pays_that_side"]].to_string(
              index=False, float_format=lambda x: f"{x:,.2f}"))
say("")
say("  This is a CURRENT DATED DIAGNOSTIC only. The 2026-08-02 broker snapshot is not")
say("  applied to any historical date, and a policy-rate differential is NOT claimed to")
say("  equal a retail CFD swap - measuring the distance between them is the point.")
say("")

# ============================================================ 7. metadata
metadata = {
    "dataset": "BIS:WS_CBPOL(1.0) Central bank policy rates",
    "source_url_resolved": BIS_URL,
    "file_in_archive": CSV_IN_ZIP,
    "retrieval_timestamp_utc": retrieved_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "bis_release_date_http_last_modified": release_date,
    "sha256_of_download": sha256,
    "download_size_bytes": size_bytes,
    "source_frequency_selected": "D (daily)",
    "frequencies_present_in_file": freq_seen,
    "units": "Per cent per year (UNIT_MEASURE 368), UNIT_MULT 0 (units)",
    "latest_reference_date": latest_ref.strftime("%Y-%m-%d"),
    "panel_start": PANEL_START.strftime("%Y-%m-%d"),
    "series": {
        AREA2CCY[a]: {
            "bis_series_id": f"BIS:WS_CBPOL(1.0):D.{a}",
            "ref_area": meta[a]["ref_area"],
            "publication_source": meta[a]["source_ref"],
            "unit_measure": meta[a]["unit_measure"],
            "decimals": meta[a]["decimals"],
            "title": meta[a]["title"],
            "compilation": meta[a]["compilation"],
            "supp_info_breaks": meta[a]["supp_info_breaks"],
        } for a in AREA2CCY
    },
    "effective_date_rule": ("value on date d = last observation with obs_date <= d; "
                            "no backward fill before first observation; no future "
                            "publication used on an earlier date"),
    "raw_file_committed": False,
    "raw_file_path": os.path.relpath(RAW_ZIP, os.path.dirname(HERE)).replace("\\", "/"),
}
with open(OUT_META, "w", encoding="utf-8") as f:
    json.dump(metadata, f, indent=2)

say("COVERAGE CONFIRMATION")
for wname in WINDOWS:
    ok = audit[f"covers_{wname}"].all()
    gaps = int(audit[f"gaps_{wname}"].sum())
    say(f"  {wname:20s} all eight covered: {ok}   total gap-days across currencies: {gaps}")
say("")
say(f"daily     -> {OUT_DAILY}")
say(f"long      -> {OUT_LONG}")
say(f"snapshots -> {OUT_SNAP}")
say(f"metadata  -> {OUT_META}")
say(f"audit     -> {OUT_AUDIT}")
say(f"swap      -> {OUT_SWAP}")
say(f"raw       -> {RAW_ZIP}  (GITIGNORED, not committed)")

with open(OUT_REPORT, "w", encoding="utf-8") as f:
    f.write("\n".join(LOG) + "\n")
print(f"report    -> {OUT_REPORT}")
