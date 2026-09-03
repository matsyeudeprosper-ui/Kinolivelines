import MetaTrader5 as mt5
from datetime import datetime, timedelta
mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
frm = datetime(2026,8,10,7,0)
to = datetime(2026,8,11,10,0)
r = mt5.copy_rates_range("BTCUSDm", mt5.TIMEFRAME_M15, frm, to)
mt5.shutdown()
for row in r:
    t = datetime.utcfromtimestamp(row['time'])
    if t.minute % 30 == 0:
        print(t, row['close'])
