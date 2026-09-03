import json, time, urllib.request, urllib.error
from datetime import datetime, timedelta

START = datetime(2022, 8, 16, 0, 0, 0)
END   = datetime(2024, 8, 16, 0, 0, 0)   # must exactly meet coinbase_m1_2yr_part1.json's start
CHUNK_MIN = 300  # coinbase max candles per request at granularity=60
OUT = "coinbase_m1_2yr_part0.json"
HEADERS = {"User-Agent": "Mozilla/5.0 research-script"}

rows = {}
cur = START
n_chunks = 0
total_chunks = int((END - START).total_seconds() // 60 // CHUNK_MIN) + 1
t0 = time.time()

while cur < END:
    chunk_end = min(cur + timedelta(minutes=CHUNK_MIN - 1), END)
    url = (f"https://api.exchange.coinbase.com/products/BTC-USD/candles"
           f"?start={cur.isoformat()}&end={chunk_end.isoformat()}&granularity=60")
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2.0 * (attempt + 1))
                continue
            time.sleep(1.0 * (attempt + 1))
        except Exception:
            time.sleep(1.0 * (attempt + 1))
    else:
        print(f"FAILED chunk at {cur} after retries, skipping")
        data = []

    for t, lo, hi, op, cl, vol in data:
        rows[int(t)] = (int(t), lo, hi, op, cl, vol)

    n_chunks += 1
    cur = chunk_end + timedelta(minutes=1)
    if n_chunks % 100 == 0:
        elapsed = time.time() - t0
        print(f"{n_chunks}/{total_chunks} chunks  ({len(rows)} bars)  {elapsed:.0f}s elapsed  cur={cur}", flush=True)
        with open(OUT + ".partial", "w") as f:
            json.dump(sorted(rows.values(), key=lambda x: x[0]), f)
    time.sleep(0.12)  # ~8 req/s, polite

final = sorted(rows.values(), key=lambda x: x[0])
with open(OUT, "w") as f:
    json.dump(final, f)
print(f"DONE: {len(final)} bars -> {OUT}")
print(f"range: {datetime.utcfromtimestamp(final[0][0])} -> {datetime.utcfromtimestamp(final[-1][0])}")
