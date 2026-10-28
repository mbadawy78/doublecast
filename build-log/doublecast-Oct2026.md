# Build log: Doublecast, October 2026

Written 28 Oct 2026. Every figure below was measured or read during the build; anything not
verified is marked **(unverified)**. Real project folders, customers and people are referred to
generically on purpose: this file is public.

## 1. State

| | |
|---|---|
| Repository | github.com/mbadawy78/doublecast (public), default branch `main` |
| Build copy | branch `master` in the build sandbox, delivered to the Mac as git bundles |
| Latest commit | `2df91e2` docs: build history (28 Oct) |
| Last push confirmed on GitHub | `b50c053` 0.2.5 (24 Oct; push output `69df014..b50c053 main -> main` seen in Terminal) |
| Delivered, push not confirmed | `a935a67`, `11d3d27`, `a564d99` (0.2.6), `2df91e2`, in `~/Projects/doublecast-ci-fix.bundle`, `doublecast-0.2.6.bundle`, `doublecast-build-history.bundle` **(unverified: pulled/pushed?)** |
| Merged | Everything is a fast-forward on one line; no open branches or pull requests |
| CI | Red from `7b42f97` to `b50c053` (lint step on `bench/blind/*.py`); fix is `11d3d27`, result **(unverified)** |
| Installed on the Mac | `pipx install --force -e ~/Projects/doublecast[tray]`, version 0.2.5 confirmed 24 Oct (editable: later pulls take effect after a Claude app restart) |
| Claude app connector | Local MCP server `doublecast`; tools `list_folder`, `search_folder`, `read_file`, `save_file` confirmed working 24 Oct |
| Allowed places | `/Users/<user>/Downloads` (`doublecast allow`, confirmed 24 Oct) |
| Menu-bar icon | Not running at last check (25 Oct); never confirmed on a real Mac |
| LibreOffice on the Mac | Not installed (24 Oct): Excel models show formulas, not results |

## 2. What was built

| Commit | Date | Version | What it does |
|---|---|---|---|
| `dc09191` | 15 Oct | 0.1.0 | Engine, deterministic doubles, money scaling with exact restore, encrypted vault, proxy (Claude Code, Codex), files, clipboard, MCP server, leak benchmark |
| `22f8eb8` | 15 Oct | 0.2.0 | Auto mode (no lists), spreadsheet column understanding, discovery (Excel/CSV, SQL, M365, Power BI, D365 F&O, Dataverse, Business Central), Claude skill |
| `f314e0e` | 15 Oct | | Hardening after an independent review of auto mode and discovery |
| `e04a9c0` | 21 Oct | 0.2.1 | Realistic doubles: real name pools by language and gender, emails from doubles, one double across Greek and Latin script |
| `4f47c2b` | 21 Oct | | Links point to mbadawy78 |
| `7b42f97` | 21 Oct | 0.2.2 | Blind benchmark vs Microsoft Presidio and the detection/restore fixes it found |
| `aeef6dc` | 21 Oct | 0.2.3 | `doublecast status`, menu-bar/tray icon (`src/doublecast/tray.py`), Claude Code plugin `integrations/claude-code/doublecast-status` |
| `69df014` | 21 Oct | 0.2.4 | `doublecast mirror` (`src/doublecast/mirror.py`): scrambled twin folder, two-way sync; names matched inside underscores |
| `b50c053` | 24 Oct | 0.2.5 | `src/doublecast/gateway.py` + connector tools (folders without copies, `doublecast allow`); row-label money logic, "1 is never scaled", LibreOffice recalc and model check (`files/recalc.py`); mirror owner marker, backup before overwrite, 20-change hold |
| `a935a67` | 24 Oct | | `read_file` pages 60,000 → 20,000 characters |
| `11d3d27` | 24 Oct | | Lint fixes in `bench/blind/`, `actions/checkout@v5`, `actions/setup-python@v6` |
| `a564d99` | 25 Oct | 0.2.6 | Alias/contact/website columns, URL detection and doubles, learn names before scrambling (and fix: spreadsheet-learned names were never saved), alias restored as written, capitals, codes equal to earlier doubles, numbers stored as text, counts never scaled, CSV quoting |
| `2df91e2` | 28 Oct | | `docs/BUILD-HISTORY.md`, README link |

## 3. The numbers

**Tests:** 222 (start of 21 Oct) → 245 (`a564d99`), all passing; `ruff check .` and
`ruff format --check .` clean at `11d3d27` and later.

**List benchmark** (`doublecast bench -n 100`, run after each change on 24–25 Oct): exact restore
556/556; restore after model mangling 1,107/1,107. `docs/benchmark.md` (larger run, read): 0
leaks across 6,409 values, 1,653/1,653 and 3,316/3,316.

**Blind benchmark** (`bench/blind/score.py corpus.jsonl shared`, 130 documents, 1,542 values,
686 keep-phrases):

| Run | Leaked (all but money) | Over-protection | Exact restore |
|---|---:|---:|---:|
| Before 0.2.6 changes (25 Oct) | 280/1,302 (21.5%) | 19/686 (2.8%) | 130/130 |
| After alias + case fixes | 273/1,302 (21.0%) | 20/686 (2.9%) | 130/130 |
| After code-collision guard | 276/1,302 (21.2%) | 21/686 (3.1%) | 130/130 |
| Final `a564d99` | 281/1,302 (21.6%) | 20/686 (2.9%) | 130/130 |

The "all but money" figure includes internal codes. `docs/benchmark-blind.md` reports 16%
excluding amounts and codes, against 28% for Presidio and 45% Presidio over-protection (read
from that file, measured 21 Oct).

**Mirror trial on a real project folder** (21 Oct): 452 files, 791 MB → twin of 27 MB; 79 files
scrambled, 322 not copied (174 jpg, 115 heic, 14 parquet, 7 mov, 3 zip, 3 png, 3 jpeg, 1 cab,
1 doc, 1 pptx), 115,871 to 117,130 values swapped across three builds; first sync 65 s once resumable. First build: the
owner's own company and people names appeared 508 times in the twin (six names: 260, 168, 42,
23, 14 and 1 hits) → after adding 4 terms with aliases to `~/.doublecast/config.yaml`: 0 hits, except 2 in
a JavaScript function name.

**Scrambled model check** (21 Oct, standalone P&L model, recalculated with LibreOffice): gross
margin −120.0% (2026) and EBITDA losses larger than revenue: nonsense caused by scaling a
switch, an index and collection days. Model test after the fix: 1 model "adds up", 1 deliberately
broken model flagged (`tests/test_mirror.py`).

**Gateway on the real folder** (24 Oct): names scrambled in listing, 3 photos hidden, save test
round-tripped the company name, no copies (446 files before and after, excluding the test file).
A single `read_file` returned 61,811 characters, over the chat client's limit → `a935a67`.

**Real Dynamics 365 export** (25 Oct, counts only, values never printed):

| Column (before fix) | Unchanged after scrambling |
|---|---:|
| `NAMEALIAS` | 27 / 29 |
| `PRIMARYCONTACTURL` | 4 / 4 |
| `Contact` (delivery addresses) | 8 / 10 |
| `Sage price list` | 19 / 29 |

| File, after `a564d99` | Names | Still visible | Not restored exactly |
|---|---:|---:|---:|
| `*_D365_Customers_V3.xlsx` | 128 | 2 | 0 cells |
| `*_D365_Vendors_V2.xlsx` | 474 | 2 | 0 cells |
| `*_D365_Setup_Answers.xlsx` | 337 | 9 | 0 cells |
| `*_D365_Items.xlsx` | 73 | 12 | 25 cells (+2 spacing only) |
| BI export `DimAccount`, `DimCustomer`, `DimDate`, `DimVendor`, `FactPriceList`, `FactOpenAP` (.csv) | | | 0 lines |
| BI export `DimItem.csv` | | | 13 lines |

The names still visible are made only of generic words. Before the restore fixes the same four
files had 0 / 236 / 328 / 269 cells not restored exactly.

**Earlier in the thread** (read from the session record): proxy +1.6 s on a first 110 KB request,
~0.2 s per turn after; Power BI `INFO.VIEW.COLUMNS()` listed 1,137 columns; `COLUMNSTATISTICS()`
ran out of memory (1,331 MB limit); `pip-audit` and `bandit` clean.

## 4. Tried and rejected

| Option | What killed it |
|---|---|
| Mirror twin as the default way into folders | Owner did not want duplicate files (disk). Measured cost was 27 MB for a 791 MB folder, but the two-mirror incident (section 5) showed sync can corrupt real files. Kept as an option; the gateway (no copies) became the recommendation. |
| `doublecast discover path` on a folder of financial models | Classified P&L numbers as 4,276 phone numbers and P&L row labels as 101 projects; 9,604 values saved, then deleted (`trio.*` rules removed). Discovery stays for master-data exports. |
| Running the mirror's vault on the shared folder mount | `sqlite3.OperationalError: disk I/O error`; used a local copy of the key and config instead. |
| Scale every number under a money header | Scenario switch 1 → *k* revealed the factor and broke the model (−120% margin). Replaced by row-label logic. |
| Free-text code-collision guard everywhere | Broke `test_structured_doubles_are_never_rescrambled` (chat history passing through the proxy holds doubles). Restricted to files read from disk (`engine.from_disk`). |
| First case-refine rule (equal "marks") | `COSTCO`-style all-caps still won over title case (capitals counted as marks); restore stayed wrong. Replaced by an accents-only comparison. |
| Intercepting Claude app attachments; a macFUSE virtual drive | Rejected on design grounds, nothing measured: attachments never pass through the computer; macFUSE needs a system extension. |
| Model data with real numbers, or reading the real file directly | Owner chose fixing models (option A) over both. |

## 5. Incidents and lessons

1. **Connected is not protected** (21 Oct). A Claude app chat read a real costing file with its
   own shell and the file was also attached; Doublecast was never called. → README states that
   attachments and cloud connectors bypass Doublecast; the gateway (`b50c053`) is the
   recommended way in: name folders, never add them.
2. **Two mirrors, one twin** (21 Oct, 23:13–23:26 local). A rebuilt twin with a new vault
   collided with the owner's running mirror: 131 junk files and 17 overwritten originals in a
   real folder (583 files instead of 452). Cleaned 24 Oct: 131 deleted, 11 originals restored
   from a download archive of 2 Oct, 6 moved to `_damaged_2026-10-21/` for the owner to redo.
   → `b50c053`: one owner per twin (`.doublecast-twin` marker), backup before any overwrite,
   more than 20 AI changes held, interrupted first runs never adopted. Lesson: never rebuild
   shared state the owner may be running.
3. **Models and the factor** (21 Oct). See section 4. → row labels, "1 is never scaled",
   recalculation, model check.
4. **Names beside the name column** (25 Oct). See the D365 table. → `a564d99`; also found that
   spreadsheet-learned names were never saved (`Engine.learn_value` never called `rules.learn`).
5. **CI red for three days** (21–24 Oct). The lint step failed on benchmark scripts; GitHub showed
   only "exit code 1". → `11d3d27`. Lesson: run `ruff check .` on the whole repo, not `src tests`.

## 6. Open items

**Defects**
- `*_D365_Items.xlsx`: 25 cells still not restored exactly; `DimItem.csv`: 13 lines (quotes and
  codes); two spellings differing only in spaces or quotes share one double.
- Search snippet scrambled the word "Doublecast" itself (over-protection, seen 24 Oct).
- 2–12 generic-word customer names per file stay visible.

**Unverified**
- Whether `11d3d27` turned CI green, and whether the 0.2.6 and build-history bundles were
  pulled and pushed.
- The menu-bar icon on a real Mac, and start at login.

**Decisions pending / next**
- Install LibreOffice on the Mac (owner was told roughly 1 GB **(unverified)**) so the P&L model
  can be answered through the gateway; that question is still unanswered.
- Six damaged files to redo (owner).
- Remove `Downloads` access from the build chat; a test file
  `IT/BI export/doublecast_test.md` was left for the owner to delete **(unverified)**.
- Optional "copy only what's opened" mode and a Finder "Send to AI" action (proposed, not built).
- Discovery on financial models; Greek and other-language row labels beyond the lists in
  `files/tabular.py`.
