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

3. **Bootstrap the worker in the Cloudflare dashboard** — local `wrangler`
   does NOT run on the dev machine (endpoint security blocks npx executables),
   so the first deploy is a paste job (done 2026-11-03): Workers & Pages →
   Create → Worker named `wod-trigger` → Edit code → paste `worker.js` →
   Deploy. Then Settings → Triggers → Add Cron Trigger `*/10 * * * *`;
   Settings → Variables and Secrets → add Secret `GITHUB_TOKEN` = the PAT;
   Settings → Domains & Routes → disable the `workers.dev` URL (no fetch
   handler, nothing to serve).

4. **Wire up CI deploys** so `worker.js` edits ship from the repo instead of
   re-pasting: `.github/workflows/deploy-trigger.yml` runs
   `cloudflare/wrangler-action` on any push to main touching `trigger/`.
   It needs two repo secrets (GitHub → Settings → Secrets and variables →
   Actions):
   - `CLOUDFLARE_API_TOKEN` — <https://dash.cloudflare.com/profile/api-tokens>
     → Create Token → **Edit Cloudflare Workers** template.
   - `CLOUDFLARE_ACCOUNT_ID` — shown in the right rail of the dashboard's
     Workers & Pages overview.

   Until both exist the workflow warns and exits green, leaving the deployed
   worker untouched. A CI deploy makes the repo the source of truth: it
   overwrites dashboard code edits and syncs the cron + `workers.dev` setting
   from `wrangler.toml` (which pins both, so nothing regresses). The
   `GITHUB_TOKEN` worker secret survives deploys — renewing the PAT stays a
   dashboard job.

5. **Watch one tick land**: the worker's page → Logs → live stream (≤10 min
   wait; each tick logs what was dispatched or why nothing was).

## Verifying / debugging later

- Live logs: Cloudflare dashboard → Workers & Pages → `wod-trigger` → Logs
  (enable Workers Logs under Observability for history, not just live tail).
  `401`/`404` on a dispatch means the PAT expired or lost a repo — mint a new
  one and replace the `GITHUB_TOKEN` secret in Settings → Variables and
  Secrets.
- `windows.json` stale or missing → the site updates on the 3-hourly baseline
  only. It refreshes with every data-driven deploy, and the daily-rewritten
  cron block in `update.yml` covers a kick-off moved in between.
- The `npx wrangler` CLI (`tail`, `dev --test-scheduled`, `deploy`) works
  fine from any machine whose security tooling allows it — just not the
  current dev machine.

## Changing the cadence

Match windows: nothing to do here — they come from `pipeline/windows.py` via
the deployed `windows.json`. Baseline and assistant cadences: edit
`assistantDue`/the baseline line in `worker.js` and push to main —
`deploy-trigger.yml` ships it (remember the budget note above). The `*/10` in
`wrangler.toml` is the tick resolution, not the firing rate.
