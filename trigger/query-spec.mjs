// The /ask contract: the JSON schema Claude's answer must fit, and the system
// prompt that teaches it the season's tables. Shared between the worker (which
// sends both to the Claude API) and the web app's tests (which validate the
// golden examples against the same schema), so the contract lives in one file.
//
// Design: Claude never sees the data and never writes prose over it. It turns
// the question into a QUERY SPEC — table, filters, aggregation, sort, limit,
// plus a headline template with {column} placeholders — and the browser
// executes the spec over the season JSON it already has (web/src/lib/
// queryExec.js). Numbers in the answer therefore always come from real rows.

// The seven tables the Explorer exposes; the executor refuses anything else.
export const QUERY_TABLES = [
  "weekly_summary", "weekly_points", "draft_picks",
  "transfers", "trades", "players", "league_table",
];

// Structured-output schema: every object closed (additionalProperties: false)
// with every key required, optionality expressed as nullable types — the shape
// the API's json_schema format needs.
export const QUERY_SPEC_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["answerable", "reason", "table", "where", "group_by", "aggregate",
             "select", "sort", "limit", "headline"],
  properties: {
    answerable: { type: "boolean" },
    reason: { type: ["string", "null"] },
    table: { type: "string", enum: QUERY_TABLES },
    // OR of AND-groups: rows match when any group's conditions all hold.
    where: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["all"],
        properties: {
          all: {
            type: "array",
            items: {
              type: "object",
              additionalProperties: false,
              required: ["col", "op", "value"],
              properties: {
                col: { type: "string" },
                op: { type: "string", enum: ["eq", "neq", "contains", "gte", "lte", "in"] },
                value: {
                  anyOf: [
                    { type: ["string", "number", "boolean", "null"] },
                    { type: "array", items: { type: ["string", "number"] } },
                  ],
                },
              },
            },
          },
        },
      },
    },
    group_by: {
      anyOf: [{ type: "null" }, { type: "array", items: { type: "string" } }],
    },
    aggregate: {
      anyOf: [
        { type: "null" },
        {
          type: "array",
          items: {
            type: "object",
            additionalProperties: false,
            required: ["fn", "col", "as"],
            properties: {
              fn: { type: "string", enum: ["sum", "count", "mean", "min", "max"] },
              col: { type: ["string", "null"] },
              as: { type: "string" },
            },
          },
        },
      ],
    },
    select: {
      anyOf: [{ type: "null" }, { type: "array", items: { type: "string" } }],
    },
    sort: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["col", "dir"],
        properties: {
          col: { type: "string" },
          dir: { type: "string", enum: ["asc", "desc"] },
        },
      },
    },
    limit: { type: "integer" },
    headline: { type: ["string", "null"] },
  },
};

// Golden question → spec pairs. Embedded in the prompt as few-shot examples and
// exercised by web/src/lib/querySpec.test.js against the schema and the executor.
export const GOLDEN_EXAMPLES = [
  {
    question: "when did MN trade out Haaland?",
    spec: {
      answerable: true, reason: null, table: "trades",
      where: [
        { all: [{ col: "offered_by", op: "eq", value: "MN" },
                { col: "player_out", op: "contains", value: "Haaland" }] },
        { all: [{ col: "received_by", op: "eq", value: "MN" },
                { col: "player_in", op: "contains", value: "Haaland" }] },
      ],
      group_by: null, aggregate: null,
      select: ["gameweek", "offered_by", "received_by", "player_in", "player_out", "state"],
      sort: [{ col: "gameweek", dir: "asc" }], limit: 20,
      headline: "Traded in gameweek {gameweek}: {player_in} for {player_out}",
    },
  },
  {
    question: "who has left the most points on the bench?",
    spec: {
      answerable: true, reason: null, table: "weekly_summary",
      where: [{ all: [{ col: "place", op: "gte", value: 12 }] }],
      group_by: ["short_name"],
      aggregate: [{ fn: "sum", col: "total_points", as: "bench_points" }],
      select: null,
      sort: [{ col: "bench_points", dir: "desc" }], limit: 10,
      headline: "{short_name} has left {bench_points} points sitting on the bench",
    },
  },
  {
    question: "top scorers in gameweek 5",
    spec: {
      answerable: true, reason: null, table: "weekly_points",
      where: [{ all: [{ col: "gameweek", op: "eq", value: 5 }] }],
      group_by: null, aggregate: null,
      select: ["web_name", "team_name", "position", "owner", "total_points"],
      sort: [{ col: "total_points", dir: "desc" }], limit: 10,
      headline: "{web_name} top-scored gameweek 5 with {total_points} points",
    },
  },
  {
    question: "which waivers failed for TS?",
    spec: {
      answerable: true, reason: null, table: "transfers",
      where: [{ all: [{ col: "short_name", op: "eq", value: "TS" },
                      { col: "result", op: "neq", value: "successful" }] }],
      group_by: null, aggregate: null,
      select: ["gameweek", "kind", "player_in", "player_out", "result"],
      sort: [{ col: "gameweek", dir: "asc" }], limit: 50,
      headline: null,
    },
  },
];

// What each table holds — grain first, then the columns worth filtering on.
// Mirrors docs/data-contract.md; update both together.
const TABLE_CATALOGUE = `
TABLES (grain — useful columns):
- weekly_summary: one row per drafter per squad slot per gameweek — gameweek,
  league, short_name (the drafter), element, place (1-11 = started XI after
  auto-subs, 12-15 = bench), web_name (the player), position (GKP/DEF/MID/FWD),
  team_name, total_points (what the player scored that week), points_scored
  (what was banked; 0 when benched), points_before_auto_subs,
  originally_starting (1/0), optimal_points, round (draft round), opposition,
  home_away.
- weekly_points: one row per player per gameweek (owned players plus top
  undrafted) — gameweek, league, element, web_name, position, team_name,
  total_points, rank_in_week, owner (drafter short_name, or a "Not Drafted"
  label), is_benched.
- draft_picks: one row per draft pick — league, short_name, index (overall
  pick number), pick, round, web_name, position, team_name, total_points (the
  player's season total), points_realised_by_drafter, prior_points (last
  season).
- transfers: one row per waiver or free-agent move INCLUDING failed attempts —
  league, gameweek, short_name, kind ('waiver' | 'free agent'), result
  ('successful', or an 'unsuccessful - …' reason), player_in, player_out,
  player_in_points, player_out_points, net_points (that gameweek).
- trades: one row per drafter-to-drafter trade — league, gameweek, offered_by,
  received_by, player_in, player_out, net_points (from the trade onward), state
  ('p' = processed and executed; anything else never happened). The OFFERING
  drafter receives player_in and gives up player_out.
- players: one row per footballer, season totals — web_name, position,
  team_name, total_points, goals_scored, assists, bonus, clean_sheets, minutes.
- league_table: one row per drafter — league, short_name, name, rank, total,
  gameweek_points, form_points.
`;

const RULES = `
RULES:
- Drafters are referred to by short_name — map any name or nickname in the
  question to a short_name from the context list. League codes likewise.
- Player names go in 'contains' filters against web_name (or player_in /
  player_out), since web_name is usually a surname.
- "X traded out P" can sit on either side of a trade: match
  (offered_by=X AND player_out contains P) OR (received_by=X AND player_in
  contains P).
- Only include executed trades (state = 'p') unless the question asks about
  offers or rejections.
- Use group_by + aggregate for "who has the most …" questions; sort on the
  aggregate alias and keep limit small.
- limit must be between 1 and 50.
- headline is a one-sentence answer template whose {column} placeholders are
  filled from the FIRST result row; use only column names present in the
  result. Set it null when a sentence would add nothing over the table.
- If the tables above cannot answer the question (future fixtures, minute-by-
  minute events, anything outside this season), set answerable=false and
  explain briefly in reason.
`;

const cap = (value, max) => String(value ?? "").slice(0, max);

/**
 * The full system prompt. `context` comes from the browser but only these
 * whitelisted, length-capped fields ever reach the prompt — the endpoint
 * cannot be repurposed as a general proxy by stuffing instructions into it.
 */
export function buildSystemPrompt(context = {}) {
  const label = cap(context.label, 32);
  const gameweek = Number.isFinite(Number(context.gameweek)) ? Number(context.gameweek) : null;
  const leagues = (Array.isArray(context.leagues) ? context.leagues : [])
    .slice(0, 4)
    .map((l) => `${cap(l?.code, 12)} (${cap(l?.name, 32)}, ${l?.scoring === "h2h" ? "head-to-head" : "classic"})`)
    .join("; ");
  const drafters = (Array.isArray(context.drafters) ? context.drafters : [])
    .slice(0, 20)
    .map((d) => `${cap(d?.short_name, 8)} = ${cap(d?.name, 48)} [${cap(d?.league, 12)}]`)
    .join("; ");

  const examples = GOLDEN_EXAMPLES
    .map((e) => `Q: ${e.question}\nSPEC: ${JSON.stringify(e.spec)}`)
    .join("\n\n");

  return `You translate a fan's question about a draft Fantasy Premier League season into a query spec (JSON) that is executed over the season's data tables in their browser. You never see the data itself — only describe the query.

Season: ${label || "unknown"}${gameweek ? `, currently gameweek ${gameweek}` : ""}.
Leagues: ${leagues || "unknown"}.
Drafters: ${drafters || "unknown"}.
${TABLE_CATALOGUE}
${RULES}
EXAMPLES:

${examples}`;
}
