# Day 3–4 study guide: what the simulator teaches you

Read `mm/simulator.py` top to bottom (about 100 lines), then work through these. Write your answers below each one — they are the questions an interviewer at a market maker will ask.

## 1. Read the single-path plot (`results/day3_single_path.png`)

- Find a stretch where inventory goes to +2 or +3. What happens to the dashed line r and the shaded band? Which side gets filled next, and why?
- The symmetric strategy reached q = +8 around t = 0.75. Why can it drift so far? (Hint: what in its quotes reacts to q?)
- Near t = 1 the band re-centres on the mid even with q ≠ 0. Which term in the formula causes that?

## 2. Read the Monte Carlo table (`results/day4_paper_table.csv`)

- At γ = 0.1 the inventory strategy earns ~3 less on average but its std is halved. If you were the desk head, which would you run, and how would you justify it with a Sharpe-like number?
- At γ = 0.5 the symmetric strategy's mean PnL also falls (58 vs 68). Why does a symmetric strategy care about γ at all? (Look at what γ does to the spread.)
- Why do both strategies have mean final q close to 0, but very different std?

## 3. Experiments to run yourself (10–15 min each)

Use `from mm.simulator import SimConfig, simulate, compare` in a notebook.

1. **Volatility shock:** rerun `compare` with σ = 4. Which strategy suffers more? Why?
2. **Thin order flow:** set A = 40. What happens to fills, spread capture and the advantage of the inventory strategy?
3. **Inventory cap:** give the *symmetric* strategy `q_max=3`. How close does a crude cap get to A-S? This is the "do I even need the math?" question.
4. **Gaussian mid:** `SimConfig(price="gaussian")`. Do results change? They shouldn't much — why?
5. **Common random numbers:** run `compare` with 100 paths and seeds 0–9. How much does the gap between strategies move vs each strategy's mean? This is why both strategies share a seed.

## 4. Things this market leaves out (they show up on Day 5–7)

- No adverse selection: fills here are independent of where the price goes next. Real informed flow hits you right before the move.
- No fees, no tick size, no latency, no queue.
- σ, A and k are known exactly. On real data you have to estimate them (Day 8).

Expect the real-data result to look much worse. That gap is the most interesting part of the project.
