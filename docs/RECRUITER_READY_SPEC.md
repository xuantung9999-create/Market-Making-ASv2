# Recruiter-ready spec: put the public copy online and make it hold up on a phone

> **For the model doing the work (Sonnet):** one task per session, in the order of section 7. Read
> sections 1-6 first, then only your task. `docs/BUILD_GUIDE.md` section 3 (how to work, when to stop
> and ask) still applies. Where this spec disagrees with `docs/DASHBOARD_SHOWCASE_SPEC.md`,
> `docs/DASHBOARD_SESSION_CHART_SPEC.md`, `docs/DASHBOARD_LIVE_SPEC.md`, `docs/DASHBOARD_REDESIGN.md`
> or `docs/DASHBOARD_GUIDE.md`, this spec wins. It overrides the showcase spec in three places:
> Story section 8 (section 5.4 here), the README part of task S8 (task R6), and "hosting" (task R1).
> Written 15 Nov 2026 from a review of the repo, the public copy and the screenshots in `docs/img/`;
> the suite was at **526 passing**.

## 1. Goal

The showcase spec made the page tell the finding. This spec makes the project **reachable and
credible from a link a recruiter opens, often on a phone**:

1. A public URL that works, linked from the first line of the README.
2. GitHub shows the current work, not the 14 Nov version.
3. No number on the README or the page disagrees with another, or with the test suite.
4. Every public page reads at 390 px with no clipped text and no horizontal page scroll.
5. The repo's first screen (file list and README top) looks like a finished project, not a work
   folder.

No new analysis, no new charts, no change to any result.

## 2. Decisions already made by the owner (do not reopen)

| Topic | Decision |
| --- | --- |
| Hosting | GitHub Pages from a **`gh-pages` branch** that holds only the contents of `dashboard_public/`. `main` stays as it is; `dashboard_public/` stays git-ignored on `main` |
| Repo name | Keep `xuantung9999-create/Market-Making-ASv2`. Public URL: `https://xuantung9999-create.github.io/Market-Making-ASv2/` |
| README history | The Day 7-10 sections, the Day 8 universe section and the paper-replication table move to `notes/HISTORY.md` with their figures. The README keeps one line linking to it |
| "What I did myself" | Sonnet drafts a short box in the README from the specs and the ledger, marked as a draft. **The owner edits it.** Deploy refuses while the draft marker is present |
| GIF / video | Out of scope |
| Root `.bat` files | `run_24x7.bat`, `install_autostart.bat` and `run_dashboard.bat` stay at the root (the Windows Startup entry written by `install_autostart.bat` runs `run_24x7.bat` from the root). Every other `run_*.bat` moves to `scripts/windows/` |
| Allowed changes | README, `notes/`, `docs/`, CSS, dashboard JavaScript views, the Python that writes bundles and sentences, `scripts/publish_dashboard.py`, moving `.bat` files, and the user-facing strings that name them. **No change to trading logic, no restart of any trader or the supervisor** |

## 3. What is wrong today (audit, 15 Nov 2026)

**Reachability**

| # | Found | Effect |
| --- | --- | --- |
| H1 | `dashboard_public/` is in `.gitignore`. The README tells the reader to serve `main`'s `dashboard/` with GitHub Pages | Pages would serve the owner copy: `dashboard/live/*` is also ignored, so the Execution test and "Live on real data" sections would be empty. There is no public URL today |
| H2 | `git status` shows 102 changed files; the last commit (`02ff6a7`, 14 Nov) is the six-tab live dashboard | GitHub shows the pre-showcase page and README. Everything from the showcase spec and the session chart is local only |
| H3 | `git` is not on PATH in PowerShell. GitHub Desktop's bundled git is at `%LOCALAPPDATA%\GitHubDesktop\app-*\resources\app\git\cmd\git.exe` | Any script that calls `git` must find it there or stop with the exact commands for the owner |

**Numbers**

| # | Seen | Cause |
| --- | --- | --- |
| N1 | README line 3: "331 tests". Story hero: "479 tests". Suite: 526 | The README number is typed in. The Story number is read correctly from `results/tests_passed.json`, but the bundles were built before the last green run |
| N2 | Hero tile "Agent fills 0 in 53 days" beside "60 dates, 3 coins"; Gate A row says "159 coin-days" | 53 counted days × 3 coins = 159, but the page never says so. Looks like a contradiction |
| N3 | `dashboard_public/index.html` has `SNAPSHOT_AT = "2026-11-15 07:33"`, the screenshots say 05:47 | Screenshots are older than the build. Fine once R7 retakes them; listed so nobody "fixes" the timestamp |

**Phone (390 px), from `docs/img/showcase-*-390.png`**

| # | Page | Seen |
| --- | --- | --- |
| M1 | All | Nav row cut off after "Fill economics"; Agent, Execution test and Appendix cannot be reached without knowing to swipe |
| M2 | Story, Verdict | Forest plot: the left margin is a fixed `l: 250` (`js/views/story.js:96` and the Verdict equivalent), so long labels ("All coins · front of queue, 100 ms (v1 assumption)") are cut on the left and the plot area is squeezed to about 60 px |
| M3 | Story, Verdict | Gate A table runs off the right edge; "What happened" and "Result" (the FAIL badges) are not visible |
| M4 | Story | Waterfall x labels are rotated about 45° and overlap the bars and each other |
| M5 | Verdict | Blotter: only Coin and Scenario are visible, cut mid-word, with no sign the table scrolls |
| M6 | Execution test | "What the test caught" table: each finding is cut after about 40 characters |
| M7 | Execution test | The headline paragraph above the banner is a dense 6-line block in mono; the state card's detail text wraps into a narrow column |
| M8 | Verdict | The cumulative P&L legend takes as much height as the chart |

**Desktop**

| # | Seen |
| --- | --- |
| D1 | Story forest plot at 1,440 px: the first label is cut ("ll coins, front of queue, 100 ms (v1 assumption)"). Same cause as M2 |

**Repo first screen**

| # | Seen |
| --- | --- |
| G1 | 24 `run_*.bat` files at the root, an empty `session_chart.js` (0 bytes, 15 Nov), `setup_git.bat` (obsolete: the repo exists) |
| G2 | README: "Edit the `SITE` block…" (a note to the owner); a "Dashboard" section describing the old page ("a live A-S simulator with sliders…"); about 190 lines, of which the top 40 carry the message |
| G3 | Story section 8 ends the page with three simulator caveats (synthetic Sharpe, no spot order book history, BTC tick) that a first-time reader has no context for |

## 4. Layout rules for narrow screens

Apply at `max-width: 640px` unless stated. These are additions to section 10 of the showcase spec.

1. **No horizontal page scroll** at 390 px on any public page: `document.documentElement.scrollWidth
   <= window.innerWidth`.
2. **Nav.** The nav row scrolls horizontally inside itself (`overflow-x: auto`, no visible
   scrollbar), with a fade on the right edge while more items are hidden. The active item scrolls
   into view on load.
3. **Tables with three short columns or fewer** stay tables. **Tables with long text** (Gate A, "What
   the test caught", Incidents) become stacked rows: line 1 the id and the status/result badge, line
   2 the rule or finding, line 3 the value or evidence. Same DOM, CSS only, using `data-label`
   attributes where a cell needs its column name.
4. **Wide numeric tables** (Blotter, Fills, per-day) scroll inside their own wrapper, with the first
   column sticky and a right-edge fade while more columns are hidden.
5. **Category charts** (forest plots) use a short label from the bundle (rule 5.1) and a left margin
   measured from the longest label, not a fixed number.
6. **Bar charts** never rotate x labels; long labels break onto two lines (`<br>`) from the bundle.
7. **Legends** with more than three entries sit below the chart in one wrapping horizontal row
   (`orientation: "h"`) and never take more than 25% of the chart height; three or fewer become
   direct labels (already a showcase rule).
8. **Prose** in mono is only for numbers and code. Headline paragraphs use the body face.

## 5. Changes

### 5.1 Short labels

The verdict and story bundles gain `label_short` for every forest row, written by Python, at most 18
characters: `Front, 100 ms`, `Queue 0.5x`, `Queue 1x`, `Queue 2x`, `Agent, 1x`, and per coin
`ANKR 1x` and so on. The long label stays for hover and for widths over 640 px. Story waterfall and
ladder categories gain the same field with `<br>` breaks (`Spread<br>captured`).

### 5.2 Numbers

- Story hero tile: "0 fills · 53 counted days (159 coin-days)". Written by `scripts/build_story.py`.
  The Verdict "Agent fills" tile follows the same wording.
- The test count shown anywhere on the page comes from `results/tests_passed.json` as today. The
  build order in R7 makes it current.
- The README states the test count **rounded down to the hundred** ("over 500 tests") so it does
  not go stale with every test. A test asserts the README figure is at most the last green count and
  within 100 of it.

### 5.3 Deploy (`scripts/publish_dashboard.py --deploy`)

1. Run the normal publish (`--live-snapshot` is required with `--deploy`; refuse without it).
2. **Refuse to deploy** if: the README still contains `<!-- DRAFT -->`; `results/tests_passed.json`
   is missing or older than the newest `.py` file under `mm/` or `scripts/`; the existing scanner
   (paths, private IPs, host name, process ids, credential words) fails.
3. Write `dashboard_public/.nojekyll`.
4. Find git: PATH first, then the newest `%LOCALAPPDATA%\GitHubDesktop\app-*\resources\app\git\cmd\git.exe`.
   If none, print the exact commands for the owner and exit non-zero.
5. In a temporary directory: copy `dashboard_public/`, `git init`, commit with the message
   `Publish <SNAPSHOT_AT>`, push with force to `origin` `gh-pages`. `main` and the working tree are
   never touched. The `origin` URL is read from the repo's own `.git/config`.
6. If the push fails on authentication, stop and print: "Push from GitHub Desktop or run
   `git push` once to store credentials, then re-run." Do not try to set up credentials.
7. Print the public URL.

### 5.4 Story ending (overrides showcase spec section 6, row 8)

Section 8 becomes **"What is next."** Conclusion 5 only (book imbalance, v2.1, pass rules fixed, not
yet evaluated), then one line: "What these simulations cannot show: Method and limits." The three
caveats move to the top of the Method and limits page (`#about`), under a heading "What this cannot
show", unchanged in wording.

### 5.5 README structure

In this order:

1. Title (the one name from the showcase spec).
2. One line: **Live page: <URL>** · code layout · 2-minute read.
3. The finding paragraph and the 4-row results table (as today).
4. One screenshot: `docs/img/showcase-story-1440.png`. The other screenshots are linked, not
   embedded.
5. **What was built** (as today, tightened to the six pipeline stages and the testnet line).
6. **What I did myself** (draft box, rule 5.6).
7. **How it was built** (the AI-to-spec paragraph, as today).
8. **What is next** (v2.1, two sentences).
9. **Run it**: Docker first, then the Python setup block shortened to install, test, publish. The
   day-by-day commands move to `notes/HISTORY.md`.
10. **Testnet trading** (as today; keep the "do not read testnet P&L as a result" paragraph).
11. **Layout** and **Model** (as today).
12. One line: "How the project got here, day by day: `notes/HISTORY.md`."

Removed: the old "Dashboard" section and the `SITE` note. The session-chart paragraph moves into
`docs/DASHBOARD_GUIDE.md`.

### 5.6 "What I did myself" (draft)

Five bullets at most, each a fact the owner can defend in an interview, drafted from
`docs/PROJECT_PLAN.md`, `docs/BUILD_GUIDE.md`, `docs/SPEC_V2_1.md`, the dashboard specs and
`docs/progress/v2_ledger.md`. Candidates: framing the question (does a tick-constrained edge survive
a queue model?); choosing the gates and pass rules before the 60-day run; writing the specs and the
test rules; reviewing every task against its spec; deciding to stop and publish a negative result.
Do not claim anything the documents do not show. Put `<!-- DRAFT: owner to edit, then delete this
line -->` directly above the box. The owner removes it.

## 6. Out of scope

New charts, new analysis, any change to a result, the v2.1 work, renaming the repo, a GIF or video,
a light theme, a custom domain, and any change under `mm/` other than the one message string in R5.

## 7. Tasks

**R0. Baseline and commit what is already done.** Run the suite and record the count. Then commit
the 102 changed files **as they are**, in one commit: "Showcase S0-S8 and the shared session chart".
Do not edit them, and do not review the trading diffs. List the changed files under `mm/` in the
task report so the owner sees them. Push. If the push fails on authentication, stop and ask the
owner to push from GitHub Desktop (H3).

**R1. Deploy step.** Section 5.3 in `scripts/publish_dashboard.py`.
- Tests in `tests/test_publish_deploy.py`, with git calls replaced by a fake runner: `--deploy`
  without `--live-snapshot` refuses; a README with `<!-- DRAFT -->` refuses; a stale or missing
  `tests_passed.json` refuses; a planted secret refuses (reuse the scanner); the pushed tree contains
  `.nojekyll` and only files from `dashboard_public/`; the push target is `gh-pages` on the URL read
  from `.git/config`; with no git found the exit code is non-zero and the printed text contains
  `git push`.
- Do not deploy in this task.

**R2. Numbers and short labels.** Sections 5.1 and 5.2 in `scripts/build_story.py` and the script
that builds the verdict bundle.
- Tests: every forest row has `label_short` of at most 18 characters; the hero agent tile contains
  both the counted days and the coin-days, and coin-days equals days × coins; the README test-count
  test from 5.2.

**R3. Phone layout.** Section 4 rules 1-8 and audit rows M1-M8, D1, in the CSS in
`dashboard/index.html` and the views (`story.js`, `overview.js`, `lv_exec.js`, `execution.js`, and
any other view a 390 px check shows clipping on).
- Static tests in `tests/test_dashboard_static.py`: the nav wrapper has `overflow-x: auto`; the
  forest plots do not use a fixed left margin over 120; no Plotly layout in a view sets `tickangle`
  to a non-zero value; the Gate A, "What the test caught" and Incidents tables carry `data-label` on
  their cells.
- Check by opening `dashboard_public/index.html` (after a publish) at 390, 1,024 and 1,440 px on
  every public page, and record `scrollWidth` against `innerWidth` for each page in the task report.
  Any page that fails rule 4.1 is not done.

**R4. Story ending.** Section 5.4 in `scripts/build_story.py`, `js/views/story.js` and the About
view. Test: the story bundle's last section contains no "Sharpe" and links to `#about`; the About
view renders the three caveats under "What this cannot show".

**R5. Repo tidy.** Move every `run_*.bat` except `run_24x7.bat` and `run_dashboard.bat` to
`scripts/windows/`, each starting with `cd /d "%~dp0..\.."` so it still runs from the repo root.
Update every user-facing string that names a moved file (today: `dashboard/js/live.js`,
`dashboard/js/source.js`, `dashboard/js/views/data.js`, `dashboard/js/views/book.js`,
`scripts/validate_tape.py`, `scripts/build_book_bundle.py`, `scripts/run_agent_walkforward.py`,
`scripts/hedge_precheck.py`, `mm/paper.py` (message text only), `docs/*.md`, `DOCKER.md`). Fix the
stale names on the way (`run_recorder.bat` does not exist). Delete the empty root
`session_chart.js` and `setup_git.bat`.
- Test: every `*.bat` name mentioned in a `.py`, `.js` or `.md` file exists at the path given.
- Do not stop, start or restart anything that is running.

**R6. README and history.** Sections 5.5 and 5.6. Create `notes/HISTORY.md` from the moved README
sections, keeping their figures (paths relative to `notes/`) and the day-by-day commands. Update the
"Superseded" note on the Day 8 section so it still makes sense out of context.
- Tests: every image and file link in `README.md` and `notes/HISTORY.md` resolves to a file in the
  repo; the README contains the public URL and `<!-- DRAFT`; the README no longer contains "SITE
  block".

**R7. Final pass.** In this order: run the full suite (writes `tests_passed.json`); rebuild the
verdict and story bundles; `python -m scripts.publish_dashboard --live-snapshot`; retake every
`docs/img/showcase-*-{1440,390}.png`; commit and push `main`. **Do not run `--deploy`**: the owner
does that after editing the draft box (section 8). Report the section 9 answers from the local
public copy.

Rules for every task:

1. No change to what orders are sent, when, or at what price. No restart of the traders or the
   supervisor. If a trading bug shows up, describe it and stop.
2. Python computes every number and writes every sentence, with pytest coverage. JavaScript formats
   and draws.
3. Vanilla JavaScript, Plotly from the existing CDN reference, no build step, no new dependency.
   The public copy still works opened as a file.
4. Each task ends with the suite green and one commit. R0 is the only commit of other people's work
   without review.

## 8. Steps for the owner (not Sonnet)

1. After R0: if the push failed, push from GitHub Desktop.
2. After R7: edit the "What I did myself" box in the README and delete the draft line.
3. Run `python -m scripts.publish_dashboard --live-snapshot --deploy`.
4. Once only: GitHub → repo Settings → Pages → Source "Deploy from a branch", branch `gh-pages`,
   folder `/ (root)`.
5. Open the public URL on your phone and run the section 9 test.

## 9. Acceptance

On the **public URL**, on a phone:

1. Does the page load in under five seconds on mobile data, with the Story first?
2. Can every nav item be reached, and is it obvious the nav scrolls?
3. Is every forest-plot label readable and every Gate A result (FAIL) visible without sideways
   scrolling?
4. Does any page scroll sideways? (It must not.)
5. Does the test count on the Story match the last green suite, and does the README's rounded figure
   agree with it?
6. Is "53 counted days" explained where it appears?
7. Does the Story end on the next experiment, not on simulator caveats?

On **GitHub**:

8. Does the README's first line give the live URL, and does the top screen state the finding?
9. Does the root file list show at most three `.bat` files and no empty files?
10. Does every link and image in the README resolve?
11. Does `main` contain the showcase and session-chart work (no uncommitted changes after R7)?

## 10. Open questions for the owner

1. ~~R0 commits changes under `mm/` without review.~~ Answered 15 Nov 2026: the owner approved
   publishing them.
2. The snapshot is frozen at publish time. Re-deploy when you want newer testnet numbers. Nothing
   refreshes it automatically, by design.
