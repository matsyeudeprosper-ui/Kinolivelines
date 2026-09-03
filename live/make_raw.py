src = open('make_pro.py', encoding='utf-8').read()

def sub(old, new):
    global src
    assert old in src, f"NOT FOUND: {old[:60]!r}"
    src = src.replace(old, new)

sub("476715495", "81725152")
sub("Exness-MT5Trial9", "Exness-MT5Trial10")
sub("MT5-KinoliveTrader-Session3", "MT5-Forge")
sub('BTCUSD"          # PRO demo symbol (7pt spread measured)',
    'BTCUSDz"         # RAW demo symbol (0 spread + $0.09 RT commission measured)')
sub("owl_pro.log", "owl_raw.log")
sub("owl_pro_alive.json", "owl_raw_alive.json")
sub("owl_pro_state.json", "owl_raw_state.json")
sub("owl_pro_journal.csv", "owl_raw_journal.csv")
sub("owl_pro_market_log.csv", "owl_raw_market_log.csv")
sub("OWL-pro-CROC (DEMO 81725152, full size)", "OWL-raw-CROC (DEMO 81725152, full size)")
sub("owl_pro_bot.py", "owl_raw_bot.py")
open("make_raw_gen.py", "w", encoding="utf-8").write(src)
import ast
ast.parse(src)
print("make_raw_gen.py written")
