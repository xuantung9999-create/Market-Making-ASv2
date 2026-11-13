"""Day 3-4: replicate Avellaneda & Stoikov (2008), section 4.

Run from the repo root:  python -m scripts.replicate_paper
Writes:
  results/day3_single_path.png   one path: mid, r, quotes, inventory, PnL
  results/day4_pnl_hist.png      PnL distribution, 1,000 paths, gamma = 0.1
  results/day4_paper_table.csv   the paper's table for gamma in {0.01, 0.1, 0.5}
"""
import matplotlib.pyplot as plt
import numpy as np

from mm.simulator import SimConfig, paper_table, simulate
from mm.strategy import PAPER_PARAMS as P

INV, SYM = "#8e44ad", "#7f8c8d"

# ---- Day 3: one path, both strategies on the same random numbers ----------
cfg1 = SimConfig(n_paths=1, seed=11)
inv, sym = simulate(P, cfg1, "inventory"), simulate(P, cfg1, "symmetric")
t = inv.t

fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True,
                         gridspec_kw={"height_ratios": [2.2, 1, 1]})
ax = axes[0]
ax.plot(t, inv.s[0], color="#222", lw=1.2, label="mid s")
ax.plot(t, inv.r[0], color=INV, lw=1.2, ls="--", label="reservation r")
ax.fill_between(t, inv.bid[0], inv.ask[0], color=INV, alpha=0.15, label="inventory bid-ask")
for fills, price, mk, c, lab in [(inv.bid_fills[0], inv.bid[0], "^", "#2471a3", "bid filled (buy)"),
                                 (inv.ask_fills[0], inv.ask[0], "v", "#c0392b", "ask filled (sell)")]:
    ax.scatter(t[fills], price[fills], marker=mk, s=18, color=c, zorder=3, label=lab)
ax.set(ylabel="price", title="Inventory strategy on one path (paper settings)")
ax.legend(ncol=3, fontsize=8, loc="upper left")

axes[1].step(t, inv.q[0], where="post", color=INV, label="inventory strategy")
axes[1].step(t, sym.q[0], where="post", color=SYM, label="symmetric strategy")
axes[1].axhline(0, color="#999", lw=0.8)
axes[1].set(ylabel="inventory q")
axes[1].legend(fontsize=8)

axes[2].plot(t, inv.pnl[0], color=INV, label="inventory strategy")
axes[2].plot(t, sym.pnl[0], color=SYM, label="symmetric strategy")
axes[2].set(ylabel="PnL (x + q s)", xlabel="time t")
axes[2].legend(fontsize=8)

fig.suptitle(f"gamma={P.gamma}, sigma={P.sigma}, k={P.k}, A={P.A}, dt={cfg1.dt}")
fig.tight_layout()
fig.savefig("results/day3_single_path.png", dpi=140)
print("saved results/day3_single_path.png")

# ---- Day 4: Monte Carlo ----------------------------------------------------
cfgN = SimConfig(n_paths=1000, seed=0)
inv_n, sym_n = simulate(P, cfgN, "inventory"), simulate(P, cfgN, "symmetric")
fig, ax = plt.subplots(figsize=(9, 4.5))
bins = np.linspace(min(inv_n.final_pnl.min(), sym_n.final_pnl.min()),
                   max(inv_n.final_pnl.max(), sym_n.final_pnl.max()), 50)
for res, c in [(sym_n, SYM), (inv_n, INV)]:
    fp = res.final_pnl
    ax.hist(fp, bins=bins, color=c, alpha=0.55,
            label=f"{res.strategy}: mean {fp.mean():.1f}, std {fp.std(ddof=1):.1f}")
ax.set(title="Terminal PnL over 1,000 paths (gamma = 0.1)", xlabel="PnL", ylabel="paths")
ax.legend()
fig.tight_layout()
fig.savefig("results/day4_pnl_hist.png", dpi=140)
print("saved results/day4_pnl_hist.png")

table = paper_table(n_paths=1000, seed=0).round(2)
table.to_csv("results/day4_paper_table.csv", index=False)
print(table.to_string(index=False))
