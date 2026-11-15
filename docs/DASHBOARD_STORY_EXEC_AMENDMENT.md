# Amendment: the Story's execution section shows the lifecycle, not a glitch

> Written 16 Nov 2026 from the owner's review of section 7 of the Story page ("It sends real orders.").
> This amends `docs/DASHBOARD_SHOWCASE_SPEC.md` section 6, row 7, and nothing else. Where they disagree,
> this file wins. The Execution test page (showcase spec section 7) is unchanged: it still publishes
> every finding in full, book glitches included.

## 1. Decisions (owner, 16 Nov 2026)

| Topic | Decision |
| --- | --- |
| Book-glitch fills on the Story | Not a finding about the code, so not under "What the test caught". One muted footnote line instead, with the count and no USDT figure |
| Restarts without a clean stop on the Story | Stays, worded as a known limitation that is logged as an incident, not as "Status: open" |
| Tape figure on the Story | Removed. The curated fill sat in a locked testnet book and did not answer the section's own question |
| New Story figure | The order lifecycle: every order attempt and where it ended (filled, cancelled, still open, rejected), with one sentence written by Python that includes the median time between quote replacements |
| `story.tape_example` | Still written: the Execution test page opens its tape drill-down on it |
| Section link | `#exec-test` (the page head), no longer `#exec-test/tape` |
| Data | The Story is built from the current testnet run (fresh run from 15 Nov 13:44 UTC), never from the archive |

## 2. Audit (what the page showed on 16 Nov 2026)

| # | What the reader saw | Problem |
| --- | --- | --- |
| A1 | "The testnet book printed fills far from the mid: 12 book-glitch fills, -51.07 USDT. Status: by design." | A venue problem listed as something the test caught; a large negative USDT figure reads as an excuse |
| A2 | "The trader restarted without a clean stop ... Status: open." | An open bug, with no explanation, on the front page |
| A3 | Tape around one fill: bid and ask both at -2.85 bp before the fill, then a 3 bp jump | A locked testnet book; the figure says nothing about order handling |
| A4 | 3,506 orders, 6 restarts | Numbers from the archived 12-15 Nov run, which the owner decided not to show |

## 3. Tasks

**T1. `scripts/build_story.py`.**
- `story_caught(rows)`: `caught_items` without the ids in `STORY_HIDDEN = {"book_glitch"}`; a row whose
  status is `open` ends "Status: known limitation; each one is logged as an incident." instead of
  "Status: open.". Returns `(items, footnote)`; the footnote is
  "<n> fill(s) that the thin testnet book printed far from the mid are kept out of every strategy number
  (details on the Execution test page)." or `None`.
- `order_lifecycle(testnet_bundles)`: `placed`, `filled`, `partial`, `cancelled`, `rejected`,
  `attempts = placed + rejected`, `open = max(0, placed - filled - cancelled)`, `replace` (one
  `{coin, median_s}` per session that has `median_replace_s`), and a `sentence`, for example
  "13 orders placed: 6 filled, 7 cancelled, none still open. No order attempt was rejected. A resting quote
  was replaced every 3.5 s (median, BTC)."
- Section 7 gains `caught_footnote` and `lifecycle`, loses `tape` and `tape_missing`; link `#exec-test`.

Tests (`tests/test_build_story.py`): the glitch row never reaches the Story's list and gives the
footnote; an `open` row never says "Status: open"; the lifecycle adds the funnels across sessions,
`open` is never negative, the sentence names every count; `tape_example` still picks an ordinary fill.

**T2. `dashboard/js/views/story.js` and `index.html` CSS.** Draw the footnote under the list
(`story-footnote`, muted, small). Replace the tape with one stacked horizontal bar, "Order attempts":
filled, cancelled, still open, rejected, each segment labelled with its count, static (no zoom, hover
only), followed by the lifecycle sentence. No digit in a string literal outside the format helpers.

## 4. Acceptance questions

1. Does the word "glitch" appear in the Story's execution section only in the footnote?
2. Does "Status: open" appear nowhere on the Story?
3. Does the bar's total equal placed plus rejected, and do its segments add up to that total?
4. Does the Execution test page still list the book-glitch row and open its tape on a curated fill?
5. Are the Story's numbers from the current testnet run?
