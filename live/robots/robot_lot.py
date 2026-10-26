"""robot_lot.py - the LOT formula of a robot's money (owner 2026-10-26: "failing to create a bot exactly the way the user wants
it is a business failure - make sure it can create any request understood").

A member's sizing rule ("0.01, plus 0.01 after each loss, 0.04 at most, back to 0.01 once I'm back at my peak") is written as
one formula over the robot's own trade history:
    min(0.04, 0.01 + 0.01 * losses_since_peak)
It is parsed with Python's parser and checked node by node against the short whitelist below - never executed as code.
Used the same way by the bench (live/lab/harness.py), the member's desk (owl_manual_trader.robot_tick) and the builder.

    names     losses_since_peak  losses since the robot's net last reached its peak (0 at a new peak)
              loss_streak win_streak   losing / winning trades in a row
              trades wins losses       counts since the start
              net peak drawdown        the robot's realised P&L, its best, and peak - net (>= 0)
              balance start_balance    the account now / at the start
              last_pnl                 the last closed trade's P&L (0 before the first)
    functions min max abs round floor  (round/floor to whole numbers; use them with * and /)
    operators + - * /  < <= > >= == !=  and or not  ( )   and   A if CONDITION else B
The value is a lot: floored to the 0.01 step, at least 0.01, at most 5.
"""
import ast
import math

NAMES = ("losses_since_peak", "loss_streak", "win_streak", "trades", "wins", "losses", "net", "peak", "drawdown",
         "balance", "start_balance", "last_pnl")
FUNCS = {"min": (2, 4), "max": (2, 4), "abs": (1, 1), "round": (1, 1), "floor": (1, 1)}
MAX_LEN, MAX_NODES = 300, 60
_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd, ast.Not, ast.And, ast.Or,
        ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq)


class LotError(ValueError):
    pass


def check(src):
    """the parsed tree, or LotError with a plain reason"""
    if not isinstance(src, str) or not src.strip():
        raise LotError("empty")
    if len(src) > MAX_LEN:
        raise LotError("too long")
    try:
        tree = ast.parse(src.strip(), mode="eval")
    except SyntaxError:
        raise LotError("cannot read it")
    n = 0
    for node in ast.walk(tree):
        n += 1
        if n > MAX_NODES:
            raise LotError("too long")
        if isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.Load)) or isinstance(node, _OPS):
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            continue
        if isinstance(node, ast.Name):
            if node.id not in NAMES and node.id not in FUNCS:
                raise LotError("unknown name '%s'" % node.id)
            continue
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCS or node.keywords:
                raise LotError("unknown function")
            lo, hi = FUNCS[node.func.id]
            if not lo <= len(node.args) <= hi:
                raise LotError("%s takes %d to %d values" % (node.func.id, lo, hi))
            continue
        raise LotError("not allowed: %s" % type(node).__name__)
    return tree


def is_ok(src):
    try:
        check(src)
        return True
    except LotError:
        return False


def _ev(n, V):
    if isinstance(n, ast.Expression):
        return _ev(n.body, V)
    if isinstance(n, ast.Constant):
        return float(n.value)
    if isinstance(n, ast.Name):
        return float(V.get(n.id, 0.0))
    if isinstance(n, ast.UnaryOp):
        v = _ev(n.operand, V)
        return -v if isinstance(n.op, ast.USub) else (v if isinstance(n.op, ast.UAdd) else float(not v))
    if isinstance(n, ast.BinOp):
        a, b = _ev(n.left, V), _ev(n.right, V)
        if isinstance(n.op, ast.Add):
            return a + b
        if isinstance(n.op, ast.Sub):
            return a - b
        if isinstance(n.op, ast.Mult):
            return a * b
        return a / b if b else 0.0
    if isinstance(n, ast.BoolOp):
        vals = [_ev(x, V) for x in n.values]
        return float(all(vals)) if isinstance(n.op, ast.And) else float(any(vals))
    if isinstance(n, ast.Compare):
        a = _ev(n.left, V)
        for op, cmp in zip(n.ops, n.comparators):
            b = _ev(cmp, V)
            ok = {ast.Lt: a < b, ast.LtE: a <= b, ast.Gt: a > b, ast.GtE: a >= b, ast.Eq: a == b, ast.NotEq: a != b}[type(op)]
            if not ok:
                return 0.0
            a = b
        return 1.0
    if isinstance(n, ast.IfExp):
        return _ev(n.body, V) if _ev(n.test, V) else _ev(n.orelse, V)
    if isinstance(n, ast.Call):
        args = [_ev(x, V) for x in n.args]
        f = n.func.id
        if f == "min":
            return min(args)
        if f == "max":
            return max(args)
        if f == "abs":
            return abs(args[0])
        if f == "round":
            return float(round(args[0]))
        return float(math.floor(args[0]))
    raise LotError("cannot compute")


def lot(src, V, step=0.01, lo=0.01, hi=5.0):
    """the lot for the next trade: the formula with the history V, on the broker's step"""
    v = _ev(check(src), V)
    if not (v == v):
        v = lo
    v = math.floor(v / step + 1e-9) * step
    return round(max(lo, min(hi, v)), 2)


class History:
    """the robot's own closed trades -> the names a formula reads (one instance per run, fed trade by trade)"""

    def __init__(self, start_balance=0.0):
        self.start = float(start_balance or 0.0)
        self.trades = self.wins = self.losses = 0
        self.loss_streak = self.win_streak = 0
        self.net = self.peak = 0.0
        self.since_peak = 0
        self.last = 0.0

    def add(self, pnl):
        pnl = float(pnl)
        self.trades += 1
        self.last = pnl
        self.net += pnl
        if pnl > 0:
            self.wins += 1
            self.win_streak += 1
            self.loss_streak = 0
        else:
            self.losses += 1
            self.loss_streak += 1
            self.win_streak = 0
            self.since_peak += 1
        if self.net >= self.peak - 1e-9:
            self.peak = self.net
            self.since_peak = 0

    def names(self, balance=None):
        return {"losses_since_peak": self.since_peak, "loss_streak": self.loss_streak, "win_streak": self.win_streak,
                "trades": self.trades, "wins": self.wins, "losses": self.losses, "net": self.net, "peak": self.peak,
                "drawdown": max(0.0, self.peak - self.net), "balance": float(balance if balance is not None else self.start + self.net),
                "start_balance": self.start, "last_pnl": self.last}


if __name__ == "__main__":
    H = History(200)
    f = "min(0.04, 0.01 + 0.01 * losses_since_peak)"
    seq = []
    for p in (-2, -2, 1, -2, 5, 3, -1):
        seq.append(lot(f, H.names()))
        H.add(p)
    print(seq)          # expected [0.01, 0.02, 0.03, 0.03, 0.04, 0.01, 0.01]
    assert seq == [0.01, 0.02, 0.03, 0.03, 0.04, 0.01, 0.01], seq
    for bad in ("__import__('os')", "open('x')", "lot.x", "[1]"):
        assert not is_ok(bad), bad
    print("ok")
