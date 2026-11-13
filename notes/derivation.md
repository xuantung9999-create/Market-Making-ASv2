# Day 1 — Deriving the Avellaneda-Stoikov quotes

Goal: be able to rebuild both A-S formulas on a whiteboard in an interview, and know where each assumption enters.

Notation: `s` mid, `x` cash, `q` inventory, `γ` risk aversion, `σ` volatility of mid, `τ = T − t` time left, `δᵃ, δᵇ` distances of ask/bid from mid.

---

## 1. Set-up (the three assumptions)

1. **Mid price is arithmetic Brownian motion**: `dS = σ dW`. No drift, no jumps, volatility constant.
2. **Fills are Poisson** with intensity that decays with distance from mid:
   `λ(δ) = A·e^(−kδ)`. (The paper motivates this from a power-law market-order size distribution plus a log price-impact model.)
3. **The market maker has CARA (exponential) utility** of terminal wealth:
   `u(x, s, q, t) = max E[ −exp(−γ (X_T + q_T S_T)) ]`.

CARA matters because it makes the value function separable in cash `x` — that is the trick that makes everything solvable.

---

## 2. Warm-up: the "frozen inventory" agent (no more trading)

If the agent just holds `q` until `T`:

```
v(x, s, q, t) = E[ −exp(−γ(x + q S_T)) ]
             = −exp(−γx) · exp(−γ q s) · exp( ½ γ² q² σ² τ )
```

(Use `S_T ~ N(s, σ²τ)` and the normal MGF: `E[e^{aZ}] = e^{aμ + ½a²σ²}`.)

### Reservation (indifference) prices

**Reservation ask** `rᵃ`: the price that makes the agent indifferent to selling one unit:

```
v(x + rᵃ, s, q − 1, t) = v(x, s, q, t)
```

Take logs, the `exp(−γx)` terms cancel:

```
−γ rᵃ + γ s + ½ γ² σ² τ [ (q−1)² − q² ] = 0
⇒ rᵃ = s + (1 − 2q) · γσ²τ / 2
```

**Reservation bid** `rᵇ` (indifferent to buying one unit), same steps:

```
v(x − rᵇ, s, q + 1, t) = v(x, s, q, t)
⇒ rᵇ = s + (−1 − 2q) · γσ²τ / 2
```

**Reservation price** = their average:

```
r = (rᵃ + rᵇ)/2 = s − q γ σ² τ          ← Formula 1
```

Note `rᵃ − rᵇ = γσ²τ`. Keep this; it reappears in the spread.

**Interpretation:** each unit of inventory exposes you to variance `σ²τ`; CARA prices that variance at `γ/2` per unit of variance; the marginal unit costs `γσ²τ·q`. Long → you value the asset less → shade both quotes down.

---

## 3. The real problem: the agent who keeps quoting

Now the agent chooses `δᵃ, δᵇ` continuously. The value function solves the HJB equation:

```
u_t + ½σ² u_ss
  + max_δᵇ λ(δᵇ) [ u(x − s + δᵇ, s, q + 1, t) − u ]     (bid gets hit: pay s − δᵇ, gain a unit)
  + max_δᵃ λ(δᵃ) [ u(x + s + δᵃ, s, q − 1, t) − u ]     (ask gets lifted: receive s + δᵃ, lose a unit)
  = 0,
terminal: u(x, s, q, T) = −exp(−γ(x + q s))
```

**Ansatz** (CARA separability): `u = −exp(−γx) · exp(−γ θ(s, q, t))`.

Substituting turns it into an equation for `θ`, and the reservation prices become
`rᵇ = θ(q+1) − θ(q)`, `rᵃ = θ(q) − θ(q−1)`.

### First-order condition for the optimal quote

Maximising the bid term gives

```
s − rᵇ + δᵇ = (1/γ) · ln( 1 − γ · λ(δᵇ) / λ'(δᵇ) )
```

With `λ = A e^(−kδ)`, `λ/λ' = −1/k`, so the right side is a **constant**:

```
s − rᵇ + δᵇ = (1/γ) ln(1 + γ/k)
```

Same for the ask: `δᵃ − (rᵃ − s) = (1/γ) ln(1 + γ/k)`.

**Interpretation:** each optimal quote sits a fixed distance `(1/γ)ln(1+γ/k)` *outside* its reservation price. This is the pure "liquidity-provision" mark-up — it depends only on how fast fills disappear with distance (`k`) and how risk averse you are (`γ`).

### Asymptotic approximation

The full `θ` has no closed form. A-S expand in inventory, `θ ≈ θ⁰ + q θ¹ + q² θ²`, which (to first order) gives back the frozen-inventory reservation prices from Section 2. That is why Formula 1 is the same as the warm-up.

---

## 4. The optimal spread

```
δᵃ + δᵇ = (rᵃ − rᵇ) + (2/γ) ln(1 + γ/k)
        = γ σ² τ + (2/γ) ln(1 + γ/k)          ← Formula 2
```

Quotes: `bid = r − spread/2`, `ask = r + spread/2`.

### Two parts of the spread

| Term | Name | Shrinks when |
|---|---|---|
| `γσ²τ` | Inventory-risk term | close to T, low vol, low γ |
| `(2/γ) ln(1+γ/k)` | Liquidity / order-flow term | fills decay fast (high k) |

**Trap to remember:** the spread does **not** always widen with γ. The first term rises with γ but the second *falls* with γ (as γ → 0 it tends to `2/k`; it decreases as γ grows). Whether total spread rises with γ depends on whether `σ²τ` is big enough. Higher γ always strengthens the inventory *skew*, though.

---

## 5. Check yourself (worked example — used in the unit tests)

`s = 100, q = 2, γ = 0.1, σ = 2, k = 1.5, T = 1, t = 0.5 (τ = 0.5)`

- `r = 100 − 2 · 0.1 · 4 · 0.5 = 99.6`
- `spread = 0.1 · 4 · 0.5 + (2/0.1) · ln(1 + 0.1/1.5) = 0.2 + 20 · 0.0645385 = 1.490770`
- `bid = 99.6 − 0.745385 = 98.854615`, `ask = 99.6 + 0.745385 = 100.345385`

Notice: ask is only 0.345 above mid, bid is 1.145 below → the agent leans toward **selling**, as it should when long.

---

## 6. Assumptions that break in crypto (feed into Week 2)

| Paper assumption | Reality in crypto | What we do |
|---|---|---|
| Finite horizon T | 24/7 market | Rolling horizon, or GLFT infinite-horizon quotes (D9) |
| Constant σ | Vol clusters | Rolling σ estimate (D8) |
| Continuous prices | Tick size | Round bid down, ask up |
| No fees | Maker fees/rebates | Subtract from each fill |
| Unbounded inventory | Risk limits | Hard `q_max`: stop quoting the side that adds risk |
| Fills independent of price moves | Adverse selection | Measure post-fill drift (D13) |

## 7. Units — decide once

Pick **seconds** for time, **USDT** for price, **BTC** for inventory. Then `σ` is USDT/√s, `k` is 1/USDT, `γ` is 1/(USDT·BTC). Mixing daily σ with a horizon in seconds is the most common bug in A-S implementations.
