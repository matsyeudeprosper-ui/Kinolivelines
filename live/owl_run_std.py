"""owl_run_std.py - the STANDARD-account (134499778) bot instance.

ONE codebase: regenerates the instance from owl_manual_bot.py at every
launch (constants + data filenames swapped), so the two live bots can
never drift apart. The Pro account (223985697) runs the original file;
this runs the same rules on the old standard account with its own
state/ledger/weather/journal (all *_std files).
"""
import runpy

SRC = r"C:\Projects\KinoliveLines\live\owl_manual_bot.py"
OUT = r"C:\Projects\KinoliveLines\live\owl_std_bot_gen.py"

REPL = [
    ("LOGIN = 223985697", "LOGIN = 134499778"),
    (r'TERMINAL = r"C:\NestTerminals\u223985697\terminal64.exe"',
     r'TERMINAL = r"C:\Projects\MT5-KinoliveTrader\terminal64.exe"'),
    ('SYMBOL = "BTCUSD"', 'SYMBOL = "BTCUSDm"'),
    ('"owl_manual.log"', '"owl_std.log"'),
    ('"owl_manual_alive.json"', '"owl_std_alive.json"'),
    ('"owl_manual_state.json"', '"owl_std_state.json"'),
    ('"owl_manual_journal.csv"', '"owl_std_journal.csv"'),
    ('"owl_market_log.csv"', '"owl_std_market_log.csv"'),
    ('"owl_trading_pause.json"', '"owl_trading_pause_std.json"'),
    ('"owl_weather.json"', '"owl_weather_std.json"'),
    ('"owl_ledger.json"', '"owl_ledger_std.json"'),
    ('"owl_fight_history.json"', '"owl_fight_history_std.json"'),
    ('"owl_chain_floor.json"', '"owl_chain_floor_std.json"'),
    ('"owl_milestone.json"', '"owl_milestone_std.json"'),
    ('"owl_equity_trail.json"', '"owl_equity_trail_std.json"'),
    ('"owl_kino_pause.json"', '"owl_kino_pause_std.json"'),
]

src = open(SRC, encoding="utf-8").read()
for a, b in REPL:
    assert a in src, "anchor missing: " + a
    src = src.replace(a, b)
open(OUT, "w", encoding="utf-8").write(src)
runpy.run_path(OUT, run_name="__main__")
