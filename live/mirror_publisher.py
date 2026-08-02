"""Publish KinoliveLines demo position events to the MT5 COMMON folder for KLMirror.mq5.

READ-ONLY on the demo side. This process never places, modifies or closes an order -
it polls positions_get() and appends a line to a shared file. All trading on the mirror
account is done by KLMirror.mq5, which the user compiles and attaches themselves. That
separation is deliberate: the demo loop's order path stays untouched, and enabling real
money trading requires a human attaching an EA to a chart.

WHY A FILE. An MQL5 program can only see its own terminal and account, so the EA on the
live terminal cannot read the demo account. Every MT5 instance on a machine shares one
COMMON folder, which is the standard bridge and needs no DLL.

  <COMMON>\\Files\\kl_mirror_signals.csv
  seq,epoch,event,ticket,side,volume,price,sl,tp

Append-only with a monotonic sequence number, so the EA can resume from where it left
off and can never act on the same event twice. The EA also ignores anything older than
its InpMaxSignalAge, so a restart cannot replay a burst of stale trades.

TO STOP MIRRORING: kill this process. The EA then receives nothing and does nothing.
That is the off switch - it does not require touching the EA or the demo loop.
"""
import MetaTrader5 as mt5
import os, csv, time, json
from datetime import datetime, timezone

TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"
SOURCE_LOGIN = 436771046           # the DEMO account we observe
SYM = "BTCUSDm"
POLL = 1.0
HERE = os.path.dirname(os.path.abspath(__file__))
ALIVE = os.path.join(HERE, "mirror_publisher_alive.json")
COLS = ["seq", "epoch", "event", "ticket", "side", "volume", "price", "sl", "tp"]


def connect():
    if not mt5.initialize(path=TERMINAL):
        raise SystemExit("publisher: initialize failed %s" % (mt5.last_error(),))
    a = mt5.account_info()
    if a is None or a.login != SOURCE_LOGIN:
        mt5.shutdown()
        raise SystemExit("publisher: REFUSING - expected demo %d, terminal is on %s"
                         % (SOURCE_LOGIN, a.login if a else None))
    return a


def signal_path():
    common = mt5.terminal_info().commondata_path
    d = os.path.join(common, "Files")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "kl_mirror_signals.csv")


def next_seq(path):
    """Resume the sequence from whatever is already on disk."""
    if not os.path.exists(path):
        return 1
    last = 0
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.reader(f):
                if row and row[0].isdigit():
                    last = max(last, int(row[0]))
    except Exception:
        pass
    return last + 1


def main():
    acc = connect()
    path = signal_path()
    seq = next_seq(path)
    print("publisher: watching demo %d (%s), writing %s, next seq %d"
          % (acc.login, acc.server, path, seq), flush=True)

    ORDER_NAMES = {mt5.ORDER_TYPE_BUY_LIMIT: "BUY_LIMIT",
                   mt5.ORDER_TYPE_SELL_LIMIT: "SELL_LIMIT",
                   mt5.ORDER_TYPE_BUY_STOP: "BUY_STOP",
                   mt5.ORDER_TYPE_SELL_STOP: "SELL_STOP"}

    known = {}                       # position ticket -> (side, volume, price, sl, tp)
    known_ord = {}                   # pending ticket  -> (type, volume, price, sl, tp)
    first_pass = True
    while True:
        try:
            pos = mt5.positions_get(symbol=SYM) or []
            cur = {}
            for p in pos:
                cur[p.ticket] = ("BUY" if p.type == 0 else "SELL",
                                 p.volume, p.price_open, p.sl, p.tp)

            # PENDING ORDERS ARE MIRRORED TOO.
            #
            # Mirroring only fills meant the EA acted a second or two late and entered
            # at whatever price existed then - measured drift of 11 to 26 points. A
            # mirrored pending is already resting at its price when the market arrives,
            # so both sides fill at the same moment. Whatever happens on the master now
            # happens on the slave.
            ords = mt5.orders_get(symbol=SYM) or []
            cur_ord = {}
            for o in ords:
                nm = ORDER_NAMES.get(o.type)
                if nm:
                    cur_ord[o.ticket] = (nm, o.volume_current, o.price_open, o.sl, o.tp)

            # On the very first pass, adopt whatever already exists WITHOUT emitting
            # events. Otherwise attaching the publisher mid-trade would mirror a
            # position already halfway to its outcome, or an order placed long ago.
            if first_pass:
                known, known_ord = dict(cur), dict(cur_ord)
                first_pass = False
                if known or known_ord:
                    print("publisher: adopted %d position(s) and %d order(s) silently"
                          % (len(known), len(known_ord)), flush=True)
            else:
                rows = []
                for t, v in cur_ord.items():
                    if t not in known_ord:
                        rows.append([seq, int(time.time()), "PEND_OPEN", t,
                                     v[0], v[1], v[2], v[3], v[4]]); seq += 1
                for t in known_ord:
                    if t not in cur_ord:
                        # A pending that fills becomes a position carrying the SAME
                        # ticket. That is how a fill is told from a cancellation - and
                        # a fill needs no signal, because the mirrored pending fills on
                        # its own. Emitting one would open a second mirror.
                        if t in cur:
                            print("publisher: pending %s filled (mirror fills itself)" % t,
                                  flush=True)
                        else:
                            rows.append([seq, int(time.time()), "PEND_CANCEL", t,
                                         "", "", "", "", ""]); seq += 1
                for t, v in cur.items():
                    # Only signal positions that did NOT arrive via a pending we already
                    # mirrored - i.e. genuine market entries.
                    if t not in known and t not in known_ord:
                        rows.append([seq, int(time.time()), "OPEN", t,
                                     v[0], v[1], v[2], v[3], v[4]]); seq += 1
                for t in known:
                    if t not in cur:
                        rows.append([seq, int(time.time()), "CLOSE", t,
                                     "", "", "", "", ""]); seq += 1
                if rows:
                    new = not os.path.exists(path) or os.path.getsize(path) == 0
                    with open(path, "a", newline="", encoding="utf-8") as f:
                        w = csv.writer(f)
                        if new:
                            w.writerow(COLS)
                        for r in rows:
                            w.writerow(r)
                            print("publisher: %s ticket %s %s" % (r[2], r[3], r[4]), flush=True)
                known, known_ord = dict(cur), dict(cur_ord)

            with open(ALIVE, "w", encoding="utf-8") as f:
                json.dump({"alive_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "open_positions": len(cur), "pending_orders": len(cur_ord),
                           "next_seq": seq, "signal_file": path}, f)
        except Exception as e:
            try:
                print("publisher error %s: %s" % (type(e).__name__, str(e)[:120]), flush=True)
            except Exception:
                pass
        time.sleep(POLL)


if __name__ == "__main__":
    main()
