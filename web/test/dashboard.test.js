import assert from "node:assert/strict";
import { test } from "node:test";

import { authorized, buildDashboard, makeDashboardDb, qualifies } from "../lib/dashboard.js";

const score = (over = {}, job = {}) => ({
  fit: 6,
  reach: 7,
  ring: "nah",
  reason: "",
  start_ok: null,
  notified_at: null,
  jobs: {
    id: "j1",
    company_name: "Firma",
    title: "Applied AI Engineer",
    location: "Berlin",
    remote: false,
    url: "https://example.com/1",
    kind: "posting",
    closed_at: null,
    first_seen_at: "2026-10-20T10:00:00Z",
    ...job,
  },
  ...over,
});

test("only the exact password is accepted", () => {
  assert.equal(authorized("geheim", "geheim"), true);
  assert.equal(authorized("falsch", "geheim"), false);
  assert.equal(authorized("", "geheim"), false);
  assert.equal(authorized(undefined, "geheim"), false);
  assert.equal(authorized("geheim", ""), false);
  assert.equal(authorized("geheim", undefined), false);
});

test("full-time jobs need fit 5 and reach 4, working students fit 3", () => {
  assert.equal(qualifies(score({ fit: 5, reach: 4 })), true);
  assert.equal(qualifies(score({ fit: 4 })), false);
  assert.equal(qualifies(score({ reach: 3 })), false);
  assert.equal(qualifies(score({ fit: 3 }, { kind: "working_student" })), true);
  assert.equal(qualifies(score({ fit: 2 }, { kind: "working_student" })), false);
});

test("closed, out-of-ring, wrong-start, other kinds and internships are left out", () => {
  assert.equal(qualifies(score({}, { closed_at: "2026-10-25T00:00:00Z" })), false);
  assert.equal(qualifies(score({ ring: "raus" })), false);
  assert.equal(qualifies(score({ start_ok: false })), false);
  assert.equal(qualifies(score({}, { kind: "initiative" })), false);
  assert.equal(qualifies(score({}, { title: "Praktikum KI" })), false);
});

test("dashboard payload sorts jobs, counts statuses and converts the cost", () => {
  const data = buildDashboard({
    scores: [
      score({ fit: 5, reach: 5 }, { id: "a", company_name: "Alpha" }),
      score({ fit: 8, reach: 9, notified_at: "2026-10-27T10:00:00Z" }, { id: "b", company_name: "Beta" }),
      score({ fit: 2 }, { id: "c" }),
    ],
    apps: [
      { job_id: "a", status: "paket", applied_at: null, updated_at: "2026-10-28T10:00:00Z", cv_pdf_path: "x.pdf", jobs: { company_name: "Alpha", title: "T", url: "https://e.com", closed_at: null } },
      { job_id: "z", status: "gemerkt", applied_at: null, updated_at: "2026-10-28T10:00:00Z", cv_pdf_path: null, jobs: null },
    ],
    initiatives: [{ id: "i1", company_name: "Merck", location: null, url: "" }],
    cost: "0.5",
    counts: { companies: 195, openJobs: 1200 },
    paused: false,
    now: new Date("2026-10-28T12:00:00Z"),
  });
  assert.deepEqual(data.jobs.map((j) => j.company), ["Beta", "Alpha"]);
  assert.equal(data.jobs[0].seen, true);
  assert.equal(data.status.unseen, 1);
  assert.equal(data.status.qualifying, 2);
  assert.deepEqual(data.status.statuses, { paket: 1 });
  assert.equal(data.applications.length, 1);
  assert.equal(data.applications[0].hasPackage, true);
  assert.equal(data.status.costEur, 0.5 * 0.92);
  assert.equal(data.status.percent, Math.round((0.46 / 5) * 100));
  assert.equal(data.initiatives[0].company, "Merck");
  assert.equal(data.generatedAt, "2026-10-28T12:00:00.000Z");
});

test("db loader asks Supabase for the right tables with the service key", async () => {
  const calls = [];
  const fetchFn = async (url, init) => {
    calls.push({ url, key: init.headers.apikey });
    const body = url.includes("monthly_cost") ? [{ cost_usd: "0.2" }] : url.includes("app_state") ? [{ value: "true" }] : [];
    return { ok: true, json: async () => body, headers: { get: () => "0-0/42" } };
  };
  const db = makeDashboardDb({ SUPABASE_URL: "https://x.supabase.co", SUPABASE_SERVICE_KEY: "k" }, fetchFn);
  const data = await db.load();
  assert.equal(data.cost, "0.2");
  assert.equal(data.paused, true);
  assert.deepEqual(data.counts, { companies: 42, openJobs: 42 });
  assert.ok(calls.every((c) => c.key === "k"));
  const tables = calls.map((c) => c.url.split("/rest/v1/")[1].split("?")[0]).sort();
  assert.deepEqual(tables, ["app_state", "applications", "companies", "jobs", "jobs", "monthly_cost", "scores"]);
});

test("db loader fails loudly when Supabase answers with an error", async () => {
  const fetchFn = async () => ({ ok: false, status: 500, headers: { get: () => "" }, json: async () => [] });
  const db = makeDashboardDb({ SUPABASE_URL: "https://x.supabase.co", SUPABASE_SERVICE_KEY: "k" }, fetchFn);
  await assert.rejects(db.load(), /supabase/);
});
