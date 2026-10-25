"""simclock.py - the virtual clock the REAL bot runs on (botsim, 2026-10-25).

The bot calls time.time(), time.sleep(), datetime.now(); here they read and advance a virtual "now". Sleeping is where
the world moves: the broker walks its ticks (stops and targets) and scheduled jobs run (the chart feed) - in order,
up to the moment the bot wakes. Optionally the bot's own compute time counts as time (real_compute): a slow pullback
rebuild delays its order exactly as it does live.
"""
import time as _rt
import types
from datetime import datetime as _DT, timezone as _TZ


class SimEnd(BaseException):
    """raised from sleep() when the replay window is over (BaseException: the bot's `except Exception` cannot eat it)"""


class Clock:
    def __init__(self, start, end, real_compute=False):
        self.now = float(start)
        self.end = float(end)
        self.real_compute = real_compute
        self._sync = _rt.perf_counter()
        self.jobs = []            # (next_t, period, fn) - called with the virtual time when due
        self.walkers = []         # fn(t_from, t_to) - the broker walks its ticks
        self.sleeps = 0

    def t(self):
        if self.real_compute:
            p = _rt.perf_counter()
            self.now += p - self._sync
            self._sync = p
        return self.now

    def every(self, period, fn, first):
        self.jobs.append([float(first), float(period), fn])

    def advance_to(self, target):
        while True:
            due = min((j for j in self.jobs if j[0] <= target), key=lambda j: j[0], default=None)
            stop = due[0] if due else target
            if stop > self.now:
                for w in self.walkers:
                    w(self.now, stop)
                self.now = stop
            if due is None:
                break
            due[0] += due[1]
            due[2](self.now)
        if self.now >= self.end:
            raise SimEnd()

    def sleep(self, s):
        self.sleeps += 1
        now = self.t()
        self.advance_to(now + max(0.0, float(s)))
        self._sync = _rt.perf_counter()


def time_module(clock):
    """a stand-in for the `time` module: virtual time() / sleep(); everything else is the real module"""
    m = types.ModuleType("time")
    for k in dir(_rt):
        if not k.startswith("__"):
            setattr(m, k, getattr(_rt, k))
    m.time = clock.t
    m.sleep = clock.sleep
    m.time_ns = lambda: int(clock.t() * 1e9)
    m.gmtime = lambda s=None: _rt.gmtime(clock.t() if s is None else s)
    m.localtime = lambda s=None: _rt.gmtime(clock.t() if s is None else s)     # the VPS runs on UTC
    m.strftime = lambda fmt, tt=None: _rt.strftime(fmt, _rt.gmtime(clock.t()) if tt is None else tt)
    return m


def datetime_class(clock):
    class SimDatetime(_DT):
        @classmethod
        def now(cls, tz=None):
            d = _DT.fromtimestamp(clock.t(), tz or _TZ.utc)
            return d if tz is not None else d.replace(tzinfo=None)

        @classmethod
        def utcnow(cls):
            return _DT.fromtimestamp(clock.t(), _TZ.utc).replace(tzinfo=None)

        @classmethod
        def today(cls):
            return cls.now()
    return SimDatetime
