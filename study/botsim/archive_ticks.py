"""archive_ticks.py - Exness public tick archive -> the botsim's data format (2026-10-26).

For months before our own recording started (2026-08-28), the replay needs real ticks. Exness publishes every BTCUSD tick per
month (https://ticks.ex2archive.com, the Pro symbol = what Valère trades). This turns a month into:
  study/ticks_archive_BTCUSD/BTCUSD_YYYY-MM-DD.npz   (time_msc, bid, ask - like our recorder's files)
  study/ticks_archive_BTCUSD/bars_YYYY-MM.npz        (M1 broker-style candles from BID ticks, RATES dtype)

python study/botsim/archive_ticks.py 2026 9            one month
python study/botsim/archive_ticks.py compare 2026 9    archive vs our own recorded ticks for the same days
"""
import io, os, sys, time, urllib.request, zipfile
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
OUT = os.path.join(STUDY, "ticks_archive_BTCUSD")
URL = "https://ticks.ex2archive.com/ticks/BTCUSD/{y}/{m:02d}/Exness_BTCUSD_{y}_{m:02d}.zip"
sys.path.insert(0, HERE)


def log(s):
    print(time.strftime("%H:%M:%S"), s, flush=True)


def download(y, m):
    os.makedirs(OUT, exist_ok=True)
    zp = os.path.join(OUT, "_dl_%d_%02d.zip" % (y, m))
    url, size = URL.format(y=y, m=m), None
    for k in range(12):                       # the server drops big months mid-way: resume with Range
        try:
            have = os.path.getsize(zp) if os.path.exists(zp) else 0
            req = urllib.request.Request(url, headers={"Range": "bytes=%d-" % have} if have else {})
            with urllib.request.urlopen(req, timeout=120) as r, open(zp, "ab" if have else "wb") as f:
                if size is None:
                    cr = r.headers.get("Content-Range")
                    size = int(cr.split("/")[-1]) if cr else int(r.headers.get("Content-Length") or 0)
                if have and r.status != 206:
                    f.seek(0); f.truncate()
                while True:
                    ch = r.read(1 << 20)
                    if not ch:
                        break
                    f.write(ch)
            if size and os.path.getsize(zp) >= size:
                return zp
            log("  try %d: %d of %s bytes, resuming" % (k + 1, os.path.getsize(zp), size))
        except Exception as e:
            log("  try %d stopped: %s" % (k + 1, e))
            time.sleep(10 * (k + 1))
    raise RuntimeError("download failed %d-%02d" % (y, m))


def convert(y, m):
    import pandas as pd
    import fakemt5 as FM
    zp = download(y, m)
    z = zipfile.ZipFile(zp)
    name = [i.filename for i in z.infolist() if i.filename.endswith(".csv")][0]
    with z.open(name) as f:
        df = pd.read_csv(f, usecols=["Timestamp", "Bid", "Ask"], dtype={"Bid": "float64", "Ask": "float64"})
    z.close()
    df = df.drop_duplicates()
    df = df[(df["Bid"] > 0) & (df["Ask"] >= df["Bid"])]
    tm = pd.to_datetime(df["Timestamp"], utc=True).dt.tz_convert(None).to_numpy().astype("datetime64[ms]").astype("int64")
    bid, ask = df["Bid"].to_numpy(), df["Ask"].to_numpy()
    o = np.argsort(tm, kind="stable")
    tm, bid, ask = tm[o], bid[o], ask[o]
    keep = np.concatenate([[True], np.diff(tm) > 0])
    tm, bid, ask = tm[keep], bid[keep], ask[keep]
    day = tm // 86400000
    for d in np.unique(day):
        s = day == d
        nm = time.strftime("%Y-%m-%d", time.gmtime(int(d) * 86400))
        np.savez_compressed(os.path.join(OUT, "BTCUSD_%s.npz" % nm), time_msc=tm[s], bid=bid[s], ask=ask[s])
    mn = tm // 60000
    idx = np.flatnonzero(np.concatenate([[True], np.diff(mn) > 0]))
    R = np.zeros(len(idx), dtype=FM.RATES)
    R["time"] = mn[idx] * 60
    R["open"] = bid[idx]
    R["close"] = bid[np.append(idx[1:] - 1, len(bid) - 1)]
    R["high"] = np.maximum.reduceat(bid, idx)
    R["low"] = np.minimum.reduceat(bid, idx)
    R["tick_volume"] = np.diff(np.append(idx, len(bid)))
    R["spread"] = np.round(np.minimum.reduceat(ask - bid, idx) * 100).astype(int)
    np.savez_compressed(os.path.join(OUT, "bars_%d-%02d.npz" % (y, m)), R=R)
    os.remove(zp)
    log("%d-%02d: %d ticks, %d bars, %d days" % (y, m, len(tm), len(R), len(np.unique(day))))


def compare(y, m):
    """our recorded ticks (Valère's terminal) vs the archive, day by day: price agreement at the same moments"""
    rec = os.path.join(STUDY, "ticks_u224016179")
    for f in sorted(os.listdir(OUT)):
        if not (f.startswith("BTCUSD_%d-%02d" % (y, m)) and f.endswith(".npz")):
            continue
        p2 = os.path.join(rec, f)
        if not os.path.exists(p2):
            continue
        A, B = np.load(os.path.join(OUT, f)), np.load(p2)
        ta, tb = A["time_msc"], B["time_msc"]
        # every recorded tick: the archive's last price at or before that moment
        j = np.searchsorted(ta, tb, side="right") - 1
        ok = j >= 0
        db = np.abs(A["bid"][j[ok]] - B["bid"][ok])
        da = np.abs(A["ask"][j[ok]] - B["ask"][ok])
        print("%s  recorded %7d archive %7d | same bid %.1f%% (within 1 $: %.1f%%) | same ask %.1f%% | median |d bid| %.2f" % (
            f[7:17], len(tb), len(ta), 100 * np.mean(db < 0.005), 100 * np.mean(db <= 1.0), 100 * np.mean(da < 0.005), float(np.median(db))))


if __name__ == "__main__":
    if sys.argv[1] == "compare":
        compare(int(sys.argv[2]), int(sys.argv[3]))
    else:
        convert(int(sys.argv[1]), int(sys.argv[2]))
