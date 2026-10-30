"""nullcheck.py - for a config, 60 random-direction replays (same times, same geometry): where does the real net sit?"""
import sys, os, json, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fastbt as F, signals as S


def null(sig, seeds=60, **kw):
    real = F.report(F.simulate(sig, **kw), "", quiet=True)
    R = [F.report(F.simulate(S.random_like(sig, seed=s), **kw), "", quiet=True) for s in range(seeds)]
    nets = np.array([r["net"] for r in R])
    mu = np.array([[r["months"][m] for m in sorted(r["months"])] for r in R])
    return {"real": real["net"], "m_up": real["months_up"], "null_mean": float(nets.mean()), "null_sd": float(nets.std()),
            "z": float((real["net"] - nets.mean()) / nets.std()), "p": float((nets >= real["net"]).mean()),
            "null_m_up_max": int(max(r["months_up"] for r in R))}


if __name__ == "__main__":
    for spec in sys.argv[1:]:
        kw = json.loads(spec)
        fam = kw.pop("fam", "bos")
        sig = getattr(S, fam)(**kw)
        print(spec, json.dumps({k: round(v, 2) if isinstance(v, float) else v for k, v in null(sig).items()}, default=float), flush=True)
