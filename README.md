# What's On Draft — data packs

[![Tests](https://github.com/mjnelson18/wod-webapp/actions/workflows/test.yml/badge.svg)](https://github.com/mjnelson18/wod-webapp/actions/workflows/test.yml)
[![Update data pack](https://github.com/mjnelson18/wod-webapp/actions/workflows/update.yml/badge.svg)](https://github.com/mjnelson18/wod-webapp/actions/workflows/update.yml)

**Live:** https://mjnelson18.github.io/wod-webapp/

A near-live data pack for a draft Fantasy Premier League among friends. Supports a weekly podcast
(two hosts reviewing the previous gameweek plus long-term trends) and casual viewers who just want
the stats.

```
FPL APIs ──(scheduled GitHub Action)──> pipeline (Python) ──> JSON ──> React SPA on GitHub Pages
```

No server, no database. A scheduled job writes static JSON and force-deploys it with the site, so
`main` never accumulates data commits.

- `pipeline/` — fetchers, pure transforms, per-season config, orchestrator
- `web/` — Vite + React SPA, mobile-first
- `reference/` — read-only inputs: the original notebook (the spec), historical CSVs (the
  validation oracle), the 2526 raw snapshot, and the old rendered reports
- `docs/` — [notebook recon](docs/notebook-recon.md), [content inventory](docs/content-inventory.md),
  [data contract](docs/data-contract.md)
- `data/` — generated output, gitignored

## Running locally

```bash
pip install -r requirements-dev.txt
```

```bash
python -m pipeline.build --season 2526 --source snapshot
```

```bash
python -m pipeline.build --season 2425
```

```bash
cd web && npm install && npm run dev
```

The frontend reads `web/public/data/`, so copy the pipeline output across after building:

```bash
rm -rf web/public/data && mkdir -p web/public && cp -r data web/public/data
```

Other useful commands:

```bash
python -m pipeline.validate --season 2526
```

```bash
python -m pipeline.schedule --season 2627
```

```bash
pytest
```

`pytest` includes the full 2526 regression (~2 min). Skip it with `pytest -m "not slow"`.

### Continuous integration

`.github/workflows/test.yml` runs the whole suite on any push or PR touching `pipeline/`,
`tests/`, the reference data or the requirements — fast tests first for quick feedback, then the
2526 regression. Run it manually with **diff_report** ticked to get the full column-by-column diff
printed to the run summary.

It does not gate the deploy. `update.yml` builds and deploys independently, so a red test run
won't block a data refresh; check the badge above rather than assuming a green deploy means the
pipeline is still correct. Frontend breakage isn't covered here either — that already fails the
site build inside `update.yml`.

### Local note: ThreatLocker and `.py` files

On the current dev machine `python.exe` is blocked from reading `.py` files outside
`site-packages`, so `python -m pipeline.build` fails with `PermissionError` and `import` cannot
work. Until the ThreatLocker exclusion for this folder is in place, prefix commands with the dev
shim, which copies the tree somewhere Python is allowed to read it:

```bash
bash scripts/devsync.sh python -m pipeline.build --season 2526 --source snapshot
```

```bash
bash scripts/devsync.sh pytest
```

This affects only local development — CI runs on Linux and is unaffected. Delete
`scripts/devsync.sh` once the exclusion lands.

## How the scheduled update works

`.github/workflows/update.yml` runs on cron, decides whether the run is worth doing, rebuilds the
JSON, and force-deploys site + data to Pages. Deployment uses a Pages artifact, so nothing is ever
committed.

### Cron (UTC)

| Cron | Covers |
|---|---|
| `*/10 11-22 * * 0,6` | weekend match windows |
| `*/10 18-22 * * 1-5` | weekday evening match windows |
| `17 * * * *` | hourly otherwise, for bonus, waivers and trades |

Kick-offs run roughly 11:00–23:00 UTC at weekends and 18:00–23:00 UTC midweek, allowing for BST.
GitHub enforces a 5-minute minimum and delays or drops short schedules under load, so treat 10
minutes as "about 10–20 minutes in practice" — near-live, not live.

### Throttling

The cron fires far more often than the pipeline builds. `pipeline.schedule` classifies the game
state from two cheap requests (`/api/game`, 162 bytes, plus one gameweek of fixtures, ~3 KB) and
applies a minimum interval:

| State | Meaning | Minimum interval |
|---|---|---|
| `live` | a match is in progress | every run (~10 min) |
| `settling` | matches finished, bonus not yet final | 15 min |
| `gameweek_open` | gameweek open, no match live right now | 1 hour |
| `between_gameweeks` | gameweek done, next one pending | 6 hours |
| `off_season` | no next gameweek | 7 days |
| `not_configured` | league codes still `<FILL IN>` | daily; archives only |
| `rate_limited` | API returned 429/503 | skip, retry next run |

### What happens at the season rollover

The FPL API only ever serves the current season, and the two hosts flip
*independently* — in July 2026 the draft host still served completed 2526 while the
fantasy host had already moved to 2627. Three guarantees cover that window:

1. **Archived seasons never touch the API again.** 2526 builds from the committed
   raw snapshot and 2425 from the committed CSVs, so both are reproducible from
   files in the repo. There is a test that builds them with `urlopen` patched to
   raise, so this can't regress.
2. **The gap between the rollover and draft night doesn't block deploys.** The new
   season's league codes don't exist until the leagues are created, so the gate
   reports `not_configured` and skips *only the current season* — archives still
   build and the site still deploys. Without this the site would be frozen for the
   whole pre-season.
3. **Wrong-season data is refused.** Every build checks GW1's deadline year against
   the season being built and aborts on a mismatch, so a run started mid-rollover
   can't write last season's numbers out under this season's id.

The gate is stdlib-only and runs *before* dependencies are installed, so a quiet run costs about 15
seconds and does not install pandas. Roughly 66 runs a day fire; only a handful do real work.

Two further brakes:

- **Raw response cache.** Finalised gameweeks are fetched once and cached (restored from the
  Actions cache each run), so a build refetches only game status, the in-progress gameweek and
  anything uncached. A gameweek is cached only when the API reports it `finished` *and*
  `data_checked`, so provisional bonus points are never frozen.
- **Digest comparison.** If the generated JSON is byte-identical to the last deployed set, a
  scheduled run skips the site build and the deploy entirely. Pushes and manual runs always deploy.

The frozen 2425 and 2526 archives are cached against a hash of `pipeline/**/*.py` and the
historical CSVs, so they are not rebuilt on every run — 2526 takes about two minutes. Bump
`ARCHIVE_CACHE_VERSION` in the workflow to force a rebuild, or run the workflow manually with
**rebuild_archives**.

### ⚠️ The cron switches itself off each summer

GitHub disables scheduled workflows on public repos after **60 days with no new commits**. The
off-season is longer than that, so the cron will lapse around midsummer every year.

Re-enable it from the Actions tab when onboarding the new season — you are editing config then
anyway. This is deliberate; there is no keepalive workflow.

## Onboarding a new season

1. **Get the league codes.** Once the new leagues exist, find them from the draft UI or the league
   details endpoint, then fill in `pipeline/config/seasons.py`:

   ```python
   League(code="Prem", name="Premiership", league_code=<NEW CODE>, size=6, relegated=2)
   ```

   Until these are set the workflow skips every run with `not_configured` rather than failing, so
   there is no alarm noise before the draft.

2. **Add the season** to `SEASONS` in the same file, modelled on `SEASON_2627`. Entry ids are
   discovered from the league details endpoint, so they do not need to be listed.

3. **Check for an excluded entry.** If someone sets up a team they will not play (as the organiser
   did in 2526), add its `league_entry` id to that league's `exclude_entries`. Its draft picks are
   removed and the survivors renumbered, but it stays visible in trades.

4. **Point the workflow at it** — set `CURRENT_SEASON` in `.github/workflows/update.yml`, and move
   the season that just ended into `ARCHIVE_SEASONS`.

5. **Snapshot the outgoing season before the rollover.** This is time-critical and easy to lose:
   the FPL API only ever serves the current season, and the two hosts roll over *independently*.

   ```bash
   python pipeline/snapshot_raw_season.py --out reference/raw_<season>
   ```

   Commit the result. Without it that season can never be rebuilt from raw. See
   [docs/notebook-recon.md](docs/notebook-recon.md) §6.1 for what was already lost this way.

6. **Re-enable the cron** in the Actions tab if it lapsed over the summer.

7. **Write the outgoing season's review.** The pipeline emits
   `data/<season>/season_review_facts.json` — every story beat as data. The write-up itself
   is a hand-written markdown file at `web/src/content/season-review/<season>.md`; add one
   and the **Season Review** tab appears for that season automatically. It is never
   generated in CI, so nothing rewrites it on the cron.

## Validation

The refactor's acceptance test is that the pipeline reproduces the old notebook's numbers on
identical input:

```bash
python -m pipeline.validate --season 2526
```

Every shared column matches the 2526 CSVs, except a short list of deliberate cleanups and the
columns the API can no longer supply (reported separately as `INTENTIONAL` and `BACKFILL`). 2425
cannot be validated — its raw data is gone and was never snapshotted — so it gets schema and
plausibility checks only.
