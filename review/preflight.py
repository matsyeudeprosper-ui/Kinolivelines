"""Pre-flight for the live bots: would this code blow up at runtime?

2026-09-30: a patch added two USES of `INTERNAL_ENTRIES` and, because the
script that added its DEFINITION exited on a failed anchor without writing,
nothing defined it. The file compiled perfectly - an undefined name is legal
Python until the line runs - so the bots restarted clean and then threw
`NameError` on two REAL accounts for two minutes.

`py_compile` cannot catch that. This can: it walks the module with ast,
collects every name that is bound at module level or inside each function,
and reports any name that is READ but never bound anywhere it could be. It
is deliberately conservative - it only reports a name that exists nowhere in
the module, which is exactly the shape of the bug above and produces no
noise on normal code.

Run it before restarting anything:

    python review/preflight.py                    # the live bots + lab
    python review/preflight.py path\\to\\file.py   # one file

Exit code 1 means DO NOT RESTART.
"""
import ast
import builtins
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIVE = os.path.join(ROOT, "live")

DEFAULT = [
    os.path.join(LIVE, "structure_bos_bot.py"),
    os.path.join(LIVE, "owl_app_server.py"),
    os.path.join(LIVE, "owl_chart_feed.py"),
    os.path.join(LIVE, "owl_package.py"),
    os.path.join(LIVE, "lab_researcher.py"),
    os.path.join(LIVE, "lab", "harness.py"),
    os.path.join(LIVE, "lab", "proof_build.py"),
]
SAFE = set(dir(builtins)) | {
    "__file__", "__name__", "__doc__", "__builtins__", "self", "cls",
}


class Collect(ast.NodeVisitor):
    """every name the module could possibly bind, anywhere in it"""

    def __init__(self):
        self.bound = set()

    def visit_Name(self, n):
        if isinstance(n.ctx, (ast.Store, ast.Del)):
            self.bound.add(n.id)
        self.generic_visit(n)

    def _fn(self, n):
        self.bound.add(n.name)
        for a in list(getattr(n.args, "posonlyargs", [])) + n.args.args + \
                n.args.kwonlyargs:
            self.bound.add(a.arg)
        if n.args.vararg:
            self.bound.add(n.args.vararg.arg)
        if n.args.kwarg:
            self.bound.add(n.args.kwarg.arg)
        self.generic_visit(n)

    visit_FunctionDef = _fn
    visit_AsyncFunctionDef = _fn

    def visit_Lambda(self, n):
        # a lambda's parameters are bindings too. Missing these produced two
        # false positives on the first run (`lambda ds:` and `lambda j:`),
        # and a checker that cries wolf is a checker nobody runs.
        for a in (list(getattr(n.args, "posonlyargs", []))
                  + n.args.args + n.args.kwonlyargs):
            self.bound.add(a.arg)
        if n.args.vararg:
            self.bound.add(n.args.vararg.arg)
        if n.args.kwarg:
            self.bound.add(n.args.kwarg.arg)
        self.generic_visit(n)

    def visit_ClassDef(self, n):
        self.bound.add(n.name)
        self.generic_visit(n)

    def visit_Import(self, n):
        for a in n.names:
            self.bound.add((a.asname or a.name).split(".")[0])
        self.generic_visit(n)

    def visit_ImportFrom(self, n):
        for a in n.names:
            if a.name == "*":
                self.bound.add("*")
            self.bound.add(a.asname or a.name)
        self.generic_visit(n)

    def visit_ExceptHandler(self, n):
        if n.name:
            self.bound.add(n.name)
        self.generic_visit(n)

    def visit_Global(self, n):
        self.bound.update(n.names)
        self.generic_visit(n)

    def visit_Nonlocal(self, n):
        self.bound.update(n.names)
        self.generic_visit(n)


def read_names(tree):
    out = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            out.setdefault(n.id, n.lineno)
    return out


def check(path):
    src = io.open(path, encoding="utf-8-sig").read()
    try:
        tree = ast.parse(src, path)
    except SyntaxError as e:
        print(f"  SYNTAX ERROR line {e.lineno}: {e.msg}")
        return 1
    c = Collect()
    c.visit(tree)
    if "*" in c.bound:          # a star import can bind anything
        print("  skipped: this module uses `from x import *`")
        return 0
    bad = []
    for name, line in sorted(read_names(tree).items(), key=lambda kv: kv[1]):
        if name in c.bound or name in SAFE:
            continue
        bad.append((line, name))
    for line, name in bad:
        print(f"  line {line}: name '{name}' is used but never defined "
              f"anywhere in this file")
    return len(bad)


def main():
    files = sys.argv[1:] or DEFAULT
    total = 0
    for f in files:
        if not os.path.exists(f):
            print(os.path.basename(f), "- missing")
            continue
        n = check(f)
        total += n
        print(f"{'FAIL' if n else 'ok  '}  {os.path.relpath(f, ROOT)}")
    print("")
    if total:
        print(f"PRE-FLIGHT FAILED: {total} undefined name(s). DO NOT RESTART.")
    else:
        print("PRE-FLIGHT OK: no name is used without being defined.")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
