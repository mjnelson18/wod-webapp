# External trigger — the reliable clock

GitHub Actions cron is best-effort, and for this account it delivers a small
fraction of firings, hours late (measured Oct–Nov 2026: the old ~50-firings/day
schedule delivered 6–12; during the Mon 2 Nov match the every-10-minutes window
produced exactly one run, before kick-off). This folder is the fix: a Cloudflare
Worker on a `*/10` cron — Cloudflare fires to the minute — that calls
`workflow_dispatch` on:

- **`wod-webapp` / `update.yml`** — every 10 min inside a match window (read
  from the deployed [`windows.json`](https://mjnelson18.github.io/wod-webapp/windows.json),
  which `update.yml` publishes from the same `pipeline/windows.py` computation
  that writes its cron block), plus a 3-hourly baseline tick.
- **`wod-draft-private` / `weekly.yml`** — hourly through waking hours, denser
  Thu–Sat, mirroring that workflow's own cron lines.

The repos' own GitHub crons stay in place as the free fallback. Both workflows
gate and dedupe their own work, so a duplicated firing costs one quiet
~20-second run.

**Budget:** every dispatch bills an Actions run (1-minute minimum, private
repos). At these cadences that is roughly 800 min/month for `wod-webapp`
(≈240 baseline + ≈560 in windows) and ≈650 for the assistant — inside the
3,000 included in GitHub Pro, and it is the cadence the schedules always
*intended*; GitHub just never delivered it. Don't broaden the cadences without
redoing this arithmetic.

## One-time setup

1. **Create a fine-grained GitHub PAT** at
   <https://github.com/settings/personal-access-tokens/new>:
   - Resource owner `mjnelson18`, **Only select repositories** →
     `wod-webapp` and `wod-draft-private`.
   - Repository permissions → **Actions: Read and write** (Metadata: read is
     added automatically). Nothing else.
   - Expiration: the maximum. **Diary the renewal** — when it expires the
     worker's dispatches start returning 401 and both sites silently degrade
     to the starved GitHub cron (slower, never broken).

   Sanity-check the token before putting it anywhere (expect HTTP 204, and a
   run to appear in the repo's Actions tab):

   ```bash
   curl -i -X POST -H "Authorization: Bearer <PAT>" -H "Accept: application/vnd.github+json" https://api.github.com/repos/mjnelson18/wod-webapp/actions/workflows/update.yml/dispatches -d '{"ref":"main","inputs":{"trigger":"cron"}}'
   ```

2. **Create a free Cloudflare account** at <https://dash.cloudflare.com/sign-up>
   (Workers Free includes cron triggers; this worker's ~4,300 ticks/month is
   nowhere near its limits).

3. **Deploy from this folder** (needs Node, which is already installed):

   ```bash
   cd trigger && npx wrangler@latest login
   ```

   ```bash
   cd trigger && npx wrangler@latest deploy
   ```

   ```bash
   cd trigger && npx wrangler@latest secret put GITHUB_TOKEN
   ```

   (paste the PAT when prompted)

4. **Watch one tick land** (≤10 min wait; each line logs what was dispatched
   or why nothing was):

   ```bash
   cd trigger && npx wrangler@latest tail
   ```

## Verifying / debugging later

- Live logs: `npx wrangler tail` from this folder, or the Cloudflare dashboard
  → Workers → `wod-trigger` → Logs. `401`/`404` on a dispatch means the PAT
  expired or lost a repo — mint a new one and `npx wrangler secret put
  GITHUB_TOKEN` again.
- Local dry-run without deploying (put `GITHUB_TOKEN=<PAT>` in `.dev.vars`
  first, or dispatches will 401):

  ```bash
  cd trigger && npx wrangler@latest dev --test-scheduled
  ```

  then hit `http://localhost:8787/__scheduled?cron=*/10+*+*+*+*`.
- `windows.json` stale or missing → the site updates on the 3-hourly baseline
  only. It refreshes with every data-driven deploy, and the daily-rewritten
  cron block in `update.yml` covers a kick-off moved in between.

## Changing the cadence

Match windows: nothing to do here — they come from `pipeline/windows.py` via
the deployed `windows.json`. Baseline and assistant cadences: edit
`assistantDue`/the baseline line in `worker.js` and `npx wrangler deploy`
(remember the budget note above). The `*/10` in `wrangler.toml` is the tick
resolution, not the firing rate.
