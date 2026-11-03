# External trigger — the reliable clock (and the /ask endpoint)

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
   Settings → Variables and Secrets → add Secret `GITHUB_TOKEN` = the PAT.
   (The `workers.dev` URL was disabled at bootstrap when the worker was
   cron-only; it is back on via `wrangler.toml` now that `/ask` exists — a CI
   deploy re-syncs it.)

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

## The /ask endpoint — natural-language Explorer queries

Since Nov 2026 the worker also serves **`POST /ask`**, the one HTTP route
(everything else 404s; `workers_dev` is back on in `wrangler.toml` to give it a
URL). It powers the question box above the site's Explorer tab:

1. The browser sends `{question, context}` — the question plus a whitelisted
   summary of the season (label, gameweek, drafter short-name list).
2. The worker asks the **Claude API** (`claude-sonnet-5-5`, structured output)
   to translate the question into a *query spec* — table, filters, aggregation,
   sort, limit — against a fixed catalogue of the site's tables. The schema and
   prompt live in `query-spec.mjs` (including the group lore the headlines can
   draw on); the client can't supply prompt text beyond the question itself, so
   the endpoint can't be repurposed as a general proxy, and off-topic questions
   are refused with a pointer back at the league data.
3. The browser executes the spec over the season JSON it already has
   (`web/src/lib/queryExec.js`) — Claude never sees the data, and every number
   shown comes from real rows.

The `scheduled()` cron handler is a separate entry point — an /ask failure
cannot affect the dispatches.

**Cost & abuse controls** (in order): CORS allow-list
(`https://mjnelson18.github.io` + localhost dev) → per-IP rate limit (10/min,
the `ASK_RATE` binding) → monthly cap (2,000 requests, the `ASK_BUDGET` KV
counter) → a single Sonnet call, `max_tokens` 1024, model and prompt pinned
server-side. A query costs ≈ $0.008 (Sonnet 5.5 at $2/$10 per MTok); the
monthly cap is worth ≈ $16 at absolute worst — realistic group usage is
pennies. Dropping `ASK_MODEL` back to `claude-haiku-5-5` cuts cost 20× if the
cap ever starts being hit.

**One-time setup** (both steps dashboard-side; the worker degrades gracefully
until they're done — no key means the box shows "unavailable", no KV means the
budget check is skipped while the rate limit still applies):

1. **`ANTHROPIC_API_KEY` worker secret** — create a key at
   <https://platform.claude.com/> and add it under the worker's Settings →
   Variables and Secrets, exactly like `GITHUB_TOKEN`. It survives deploys.
2. **`ASK_BUDGET` KV namespace** — dashboard → Storage & Databases → KV →
   Create namespace (call it `ask-budget`), then paste its id into the
   commented `[[kv_namespaces]]` block in `wrangler.toml` and push.

**After the first deploy**, confirm the workers.dev URL matches
`VITE_ASK_ENDPOINT` in `web/.env` / `web/.env.dunelmliga` (the subdomain is the
account's, usually `mjnelson18.workers.dev`) — fix the env files if not; the
Ask box hides itself wherever the variable is unset.

**Verify** (from any machine):

```bash
node trigger/scripts/ask-smoke.mjs
```

which asserts the preflight, the CORS allow-list, input validation and a real
question, and prints the returned spec. Eleven rapid runs should start
returning 429 (the rate limit). The contract itself — golden question→spec
pairs validating against the schema and executing in the app — is pinned by
`cd web && npm test`, which `deploy-trigger.yml` runs before every deploy.
After any deploy, watch one cron tick land in the live logs (the dashboard's
Logs stream) to confirm the clock is untouched.

## Changing the cadence

Match windows: nothing to do here — they come from `pipeline/windows.py` via
the deployed `windows.json`. Baseline and assistant cadences: edit
`assistantDue`/the baseline line in `worker.js` and push to main —
`deploy-trigger.yml` ships it (remember the budget note above). The `*/10` in
`wrangler.toml` is the tick resolution, not the firing rate.
