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
//
// Since Nov 2026 the worker also serves one HTTP route, POST /ask — the natural
// language query box above the site's Explorer. The browser sends a question;
// the worker asks the Claude API to turn it into a structured QUERY SPEC
// (schema + prompt in query-spec.mjs) and returns it; the browser executes the
// spec over the season JSON it already has. The scheduled() handler above is
// completely independent of this — an /ask failure cannot touch the cron.

import { QUERY_SPEC_SCHEMA, buildSystemPrompt } from "./query-spec.mjs";

const OWNER = "mjnelson18";
const WINDOWS_URL = "https://mjnelson18.github.io/wod-webapp/windows.json";
const UA = "wod-trigger-worker";

// Browsers allowed to call /ask: the Pages site (both published sites share
// this origin — only paths differ) and local dev servers.
const ASK_ORIGINS = [
  "https://mjnelson18.github.io",
  "http://localhost:5173",
  "http://127.0.0.1:5173",
];

const ASK_MODEL = "claude-sonnet-5-5"; // $2/$10 per MTok ≈ 1p per query; worth it over Haiku for nickname mapping and trade logic
const ASK_MAX_QUESTION = 300;
// Hard monthly ceiling on accepted requests. 2,000 Haiku calls ≈ $0.60 — the
// cap is about abuse, not spend. KV is eventually consistent, so treat it as a
// soft cap backed by the per-IP rate limit.
const ASK_MONTHLY_CAP = 2000;

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

  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/ask") return new Response("not found", { status: 404 });

    const origin = request.headers.get("origin") ?? "";
    const allowed = ASK_ORIGINS.includes(origin);

    if (request.method === "OPTIONS") {
      if (!allowed) return new Response(null, { status: 403 });
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }
    if (request.method !== "POST") return new Response("method not allowed", { status: 405 });
    if (!allowed) return askError(origin, 403, "forbidden");

    return ask(request, env, origin);
  },
};

function corsHeaders(origin) {
  return {
    "access-control-allow-origin": origin,
    "access-control-allow-methods": "POST, OPTIONS",
    "access-control-allow-headers": "content-type",
    "access-control-max-age": "86400",
    vary: "origin",
  };
}

function askError(origin, status, code) {
  return new Response(JSON.stringify({ error: code }), {
    status,
    headers: { "content-type": "application/json", ...corsHeaders(origin) },
  });
}

async function ask(request, env, origin) {
  if (!env.ANTHROPIC_API_KEY) {
    // Secret not configured yet (see README) — the site shows a friendly
    // "unavailable" state rather than erroring.
    console.log("ask: ANTHROPIC_API_KEY not configured");
    return askError(origin, 503, "unavailable");
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return askError(origin, 400, "bad_request");
  }
  const question = typeof body?.question === "string" ? body.question.trim() : "";
  if (!question || question.length > ASK_MAX_QUESTION) {
    return askError(origin, 400, "bad_request");
  }

  // Burst control: per-IP token bucket via the Workers rate-limiting binding.
  const ip = request.headers.get("cf-connecting-ip") ?? "unknown";
  if (env.ASK_RATE) {
    const { success } = await env.ASK_RATE.limit({ key: ip });
    if (!success) {
      console.log(`ask: rate limited (${ip})`);
      return askError(origin, 429, "busy");
    }
  }

  // Monthly budget: a KV counter, skipped gracefully until the namespace is
  // bound (README's one-time setup). The rate limit above still applies.
  const month = new Date().toISOString().slice(0, 7);
  if (env.ASK_BUDGET) {
    const used = Number((await env.ASK_BUDGET.get(`budget:${month}`)) ?? 0);
    if (used >= ASK_MONTHLY_CAP) {
      console.log(`ask: monthly cap reached (${used})`);
      return askError(origin, 429, "budget");
    }
    // 40-day TTL: the key dies on its own shortly after the month does.
    await env.ASK_BUDGET.put(`budget:${month}`, String(used + 1), { expirationTtl: 3456000 });
  }

  // buildSystemPrompt whitelists and length-caps everything it takes from the
  // client context, so the question is the only free text that reaches Claude.
  const payload = {
    model: ASK_MODEL,
    max_tokens: 1024,
    output_config: {
      effort: "low",
      format: { type: "json_schema", schema: QUERY_SPEC_SCHEMA },
    },
    system: buildSystemPrompt(body.context ?? {}),
    messages: [{ role: "user", content: question }],
  };

  let upstream;
  try {
    upstream = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "x-api-key": env.ANTHROPIC_API_KEY,
        "anthropic-version": "2026-10-21",
        "content-type": "application/json",
        "user-agent": UA,
      },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    console.log(`ask: upstream unreachable (${err})`);
    return askError(origin, 502, "upstream");
  }

  if (upstream.status === 429) return askError(origin, 429, "busy");
  if (!upstream.ok) {
    console.log(`ask: upstream ${upstream.status} ${await upstream.text()}`);
    return askError(origin, 502, "upstream");
  }

  const message = await upstream.json();
  const text = (message.content ?? []).find((b) => b.type === "text")?.text;
  if (message.stop_reason !== "end_turn" || !text) {
    console.log(`ask: unusable response (stop_reason=${message.stop_reason})`);
    return askError(origin, 502, "upstream");
  }

  let spec;
  try {
    spec = JSON.parse(text); // structured output: guaranteed to fit the schema
  } catch {
    console.log("ask: response was not JSON");
    return askError(origin, 502, "upstream");
  }

  const usage = message.usage ?? {};
  console.log(`ask: ok q=${question.length}ch table=${spec.table} answerable=${spec.answerable} ` +
              `tokens=${usage.input_tokens}/${usage.output_tokens}`);
  return new Response(JSON.stringify({ spec }), {
    headers: { "content-type": "application/json", ...corsHeaders(origin) },
  });
}

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
