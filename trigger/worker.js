// The reliable clock for the WOD data pack and the private weekly assistant.
//
// GitHub Actions cron is best-effort: in practice it delivers a small fraction
// of firings, hours late (observed Oct–Nov 2026 — during a Monday-night match
// the site's every-10-minutes window produced one run all evening). Cloudflare
// cron fires to the minute, so this worker is the primary clock and the repos'
// own cron blocks are the free fallback.
//
// It holds no scheduling intelligence of its own. The match windows are
// computed by pipeline/windows.py and published with the site as windows.json;
// the assistant cadence below mirrors weekly.yml's own cron lines. The worker
// only answers "is now one of the moments the repos asked for?" and, when it
// is, fires workflow_dispatch:
//
//   wod-webapp         update.yml   inside a match window, every 10 minutes,
//                                   plus a 3-hourly baseline tick
//   wod-draft-private  weekly.yml   hourly probe through waking hours, denser
//                                   Thu–Sat for waiver/deadline reminders
//
// Every dispatch bills a GitHub Actions run (1-minute minimum on a private
// repo), so the cadences here ARE the Actions budget — don't broaden them
// without redoing the quota arithmetic in the repo README. Duplicates against
// a rare GitHub-delivered cron firing cost one gated quiet run; both
// workflows' gates make that cheap.
//
// Setup and failure modes: README.md in this folder.

const OWNER = "mjnelson18";
const WINDOWS_URL = "https://mjnelson18.github.io/wod-webapp/windows.json";
const UA = "wod-trigger-worker";

export default {
  async scheduled(event, env, ctx) {
    // The *scheduled* time, not the wall clock: exact minutes, no drift.
    const now = new Date(event.scheduledTime);
    const jobs = [];
    if (await updateDue(now)) {
      jobs.push(dispatch(env, "wod-webapp", "update.yml", { trigger: "cron" }));
    }
    if (assistantDue(now)) {
      jobs.push(dispatch(env, "wod-draft-private", "weekly.yml", {}));
    }
    await Promise.all(jobs);
  },
};

async function updateDue(now) {
  // Inside a published match window → every tick (i.e. every 10 minutes).
  // windows.json missing or unreachable → baseline only, the same degradation
  // as a stale cron block: slower, never broken.
  try {
    const res = await fetch(WINDOWS_URL, {
      headers: { "user-agent": UA },
      cf: { cacheTtl: 0 },
    });
    if (res.ok) {
      const { windows = [] } = await res.json();
      if (windows.some((w) => new Date(w.start) <= now && now <= new Date(w.end))) {
        return true;
      }
    } else {
      console.log(`windows.json: HTTP ${res.status}; baseline only`);
    }
  } catch (err) {
    console.log(`windows.json unreachable (${err}); baseline only`);
  }
  // 3-hourly baseline: waivers, trades, bonus stragglers. Same hours as the
  // repo's own '17 */3 * * *' fallback, at :20 so the rare GitHub-delivered
  // firing lands a few minutes apart instead of racing it.
  return now.getUTCHours() % 3 === 0 && now.getUTCMinutes() === 20;
}

function assistantDue(now) {
  // Mirrors weekly.yml's own schedule ('23 6-23 * * *' and '53 9-18 * * 4,5,6'):
  // an hourly probe through waking hours — no FPL event moves 00:00–06:00 UTC —
  // plus a denser Thu–Sat line around waiver and deadline reminders. The
  // dispatcher is idempotent, so this is a sampling rate, not a schedule.
  const h = now.getUTCHours();
  const m = now.getUTCMinutes();
  const day = now.getUTCDay(); // 0 = Sunday
  if (h >= 6 && m === 20) return true;
  return [4, 5, 6].includes(day) && h >= 9 && h <= 18 && m === 50;
}

async function dispatch(env, repo, workflow, inputs) {
  const url = `https://api.github.com/repos/${OWNER}/${repo}/actions/workflows/${workflow}/dispatches`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.GITHUB_TOKEN}`,
      accept: "application/vnd.github+json",
      "x-github-api-version": "2022-11-28",
      "user-agent": UA,
      "content-type": "application/json",
    },
    body: JSON.stringify({ ref: "main", inputs }),
  });
  // 204 = dispatched. Anything else (401/404 = token expired or unscoped)
  // shows up in `wrangler tail` and the Cloudflare dashboard logs.
  const detail = res.status === 204 ? "dispatched" : await res.text();
  console.log(`${repo}/${workflow}: ${res.status} ${detail}`);
}
