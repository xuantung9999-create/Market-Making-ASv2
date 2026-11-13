"""Day 2 sanity plot: how A-S quotes move with inventory and with time left.

Run from the repo root:  python -m scripts.plot_quotes
"""
import matplotlib.pyplot as plt
import numpy as np

from mm.strategy import PAPER_PARAMS as P, quote

S = 100.0

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))

# Left: quotes vs inventory at t = 0
qs = np.arange(-10, 11)
quotes = [quote(S, q, 0.0, P) for q in qs]
ax1.plot(qs, [x.ask for x in quotes], "o-", color="#c0392b", label="ask")
ax1.plot(qs, [x.reservation for x in quotes], "s--", color="#555", label="reservation r")
ax1.plot(qs, [x.bid for x in quotes], "o-", color="#2471a3", label="bid")
ax1.axhline(S, color="#999", lw=0.8, ls=":", label="mid")
ax1.set(title="Quotes vs inventory (t = 0)", xlabel="inventory q", ylabel="price")
ax1.legend()

# Right: quotes vs time for q = +3, showing skew fading toward T
ts = np.linspace(0, P.T, 101)
for q, c in [(3, "#8e44ad"), (0, "#27ae60")]:
    qt = [quote(S, q, t, P) for t in ts]
    ax2.fill_between(ts, [x.bid for x in qt], [x.ask for x in qt], color=c, alpha=0.18)
    ax2.plot(ts, [x.reservation for x in qt], color=c, label=f"r, q = {q:+d}")
ax2.axhline(S, color="#999", lw=0.8, ls=":")
ax2.set(title="Bid-ask band over time (shaded)", xlabel="time t", ylabel="price")
ax2.legend()

fig.suptitle(f"Avellaneda-Stoikov quotes — gamma={P.gamma}, sigma={P.sigma}, k={P.k}, T={P.T}")
fig.tight_layout()
fig.savefig("results/day2_quotes.png", dpi=140)
print("saved results/day2_quotes.png")
