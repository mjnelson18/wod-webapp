// Manual smoke test for the deployed /ask endpoint. Not run in CI (it spends
// real API pennies); run it from any machine after a deploy:
//
//   node trigger/scripts/ask-smoke.mjs
//   node trigger/scripts/ask-smoke.mjs "who won gameweek 3?"
//
// Expects: 403 without an allowed Origin, 204 on preflight, and a query spec
// for a real question. The CORS check matters — curl bypasses the browser's
// own enforcement, so the headers are asserted here instead.

const ENDPOINT = process.env.ASK_ENDPOINT ?? "https://wod-trigger.mjnelson18.workers.dev/ask";
const ORIGIN = "https://mjnelson18.github.io";

const context = {
  label: "2026/27",
  gameweek: 10,
  leagues: [{ code: "DL", name: "Dunelmliga", scoring: "h2h" }],
  drafters: [
    { short_name: "MN", name: "Mike Nelson", league: "DL" },
    { short_name: "TS", name: "Tom Shiel", league: "DL" },
  ],
};

const question = process.argv[2] ?? "when did MN trade out Haaland?";

let failures = 0;
const check = (label, ok, detail = "") => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}${detail ? ` — ${detail}` : ""}`);
  if (!ok) failures += 1;
};

// 1. Preflight from the allowed origin.
const preflight = await fetch(ENDPOINT, {
  method: "OPTIONS",
  headers: { origin: ORIGIN, "access-control-request-method": "POST" },
});
check("preflight 204", preflight.status === 204, `got ${preflight.status}`);
check("preflight echoes origin",
  preflight.headers.get("access-control-allow-origin") === ORIGIN);

// 2. A disallowed origin is refused.
const stranger = await fetch(ENDPOINT, {
  method: "POST",
  headers: { origin: "https://evil.example", "content-type": "application/json" },
  body: JSON.stringify({ question, context }),
});
check("disallowed origin 403", stranger.status === 403, `got ${stranger.status}`);

// 3. An over-long question is a 400.
const tooLong = await fetch(ENDPOINT, {
  method: "POST",
  headers: { origin: ORIGIN, "content-type": "application/json" },
  body: JSON.stringify({ question: "x".repeat(400), context }),
});
check("over-long question 400", tooLong.status === 400, `got ${tooLong.status}`);

// 4. The real thing.
const res = await fetch(ENDPOINT, {
  method: "POST",
  headers: { origin: ORIGIN, "content-type": "application/json" },
  body: JSON.stringify({ question, context }),
});
const body = await res.json().catch(() => null);
check("question answered 200", res.status === 200,
  `got ${res.status} ${JSON.stringify(body)}`);
if (res.status === 200) {
  check("spec has a table", typeof body?.spec?.table === "string", body?.spec?.table);
  console.log("\nSpec:\n" + JSON.stringify(body.spec, null, 2));
}

process.exit(failures ? 1 : 0);
