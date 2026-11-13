"""Day 4 study-guide experiments (notes/day3_study_guide.md, section 3).

Run from the repo root:  python -m scripts.day4_experiments
Writes results/day4_experiments.csv and results/day4_crn.png
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from mm.simulator import SimConfig, compare, simulate
from mm.strategy import ASParams

N = 1000
BASE = dict(gamma=0.1, sigma=2.0, k=1.5, A=140.0)


def run(label, cfg=SimConfig(n_paths=N, seed=0), **over):
    p = ASParams(**{**BASE, **over})
    df = compare(p, cfg)
    df.insert(0, "experiment", label)
    return df


rows = [
    run("0 baseline"),
    run("1 sigma = 4", sigma=4.0),
    run("2 thin flow A = 40", A=40.0),
    run("3 q_max = 3 (both)", q_max=3),
    run("4 gaussian mid", cfg=SimConfig(n_paths=N, seed=0, price="gaussian")),
]
table = pd.concat(rows, ignore_index=True)
table["sharpe"] = table["mean_pnl"] / table["std_pnl"]
table = table.drop(columns=["gamma"]).round(2)
table.to_csv("results/day4_experiments.csv", index=False)
print(table.to_string(index=False))

# Experiment 3b: crude cap on the symmetric strategy vs uncapped A-S
cfg = SimConfig(n_paths=N, seed=0)
asm = simulate(ASParams(**BASE), cfg, "inventory").summary()
print("\nExperiment 3b: symmetric + cap vs plain A-S")
for qm in (2, 3, 5, 8):
    s = simulate(ASParams(**BASE, q_max=qm), cfg, "symmetric").summary()
    print(f"  symmetric q_max={qm}: mean {s['mean_pnl']:.1f}  std {s['std_pnl']:.1f}  "
          f"sharpe {s['mean_pnl']/s['std_pnl']:.1f}")
print(f"  A-S (no cap):        mean {asm['mean_pnl']:.1f}  std {asm['std_pnl']:.1f}  "
      f"sharpe {asm['mean_pnl']/asm['std_pnl']:.1f}")

# Experiment 5: common random numbers. 100 paths, seeds 0-9.
p = ASParams(**BASE)
recs = []
for seed in range(10):
    df = compare(p, SimConfig(n_paths=100, seed=seed)).set_index("strategy")["mean_pnl"]
    recs.append({"seed": seed, "inventory": df["inventory"], "symmetric": df["symmetric"]})
crn = pd.DataFrame(recs)
crn["gap_same_seed"] = crn["symmetric"] - crn["inventory"]
# Same comparison with DIFFERENT random numbers for each strategy
gap_indep = [simulate(p, SimConfig(n_paths=100, seed=s), "symmetric").summary()["mean_pnl"]
             - simulate(p, SimConfig(n_paths=100, seed=100 + s), "inventory").summary()["mean_pnl"]
             for s in range(10)]
crn["gap_indep_seeds"] = gap_indep
print("\nExperiment 5: mean PnL per seed (100 paths each)")
print(crn.round(2).to_string(index=False))
print("std across seeds:", crn.drop(columns="seed").std().round(2).to_dict())

fig, ax = plt.subplots(figsize=(8, 4))
ax.plot(crn.seed, crn.gap_same_seed, "o-", color="#8e44ad", label="gap, same random numbers")
ax.plot(crn.seed, crn.gap_indep_seeds, "s--", color="#7f8c8d", label="gap, independent random numbers")
ax.axhline(0, color="#999", lw=0.8)
ax.set(title="Symmetric minus inventory mean PnL, 100 paths per run",
       xlabel="seed", ylabel="PnL gap")
ax.legend()
fig.tight_layout()
fig.savefig("results/day4_crn.png", dpi=140)
print("saved results/day4_crn.png")
