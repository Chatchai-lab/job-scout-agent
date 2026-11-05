import assert from "node:assert/strict";
import { test } from "node:test";

import file from "../api/file.js";
import application from "../api/application.js";
import status from "../api/status.js";
import {
  applicationDetail, creditFrom, guard, isUuid, makeDetailDb, setCredit, startImport, startPackage,
} from "../lib/dashboard.js";
import { makeGithub } from "../lib/handler.js";

const ID = "123e4567-e89b-42d3-a456-426614174000";
const ENV = { SUPABASE_URL: "https://x.supabase.co", SUPABASE_SERVICE_KEY: "svc", DASHBOARD_PASSWORD: "geheim" };

const ROW = {
  job_id: ID, status: "paket", applied_at: null, updated_at: "2026-11-02T10:00:00Z",
  cover_letter: "Sehr geehrte Damen und Herren,", gaps: [{ requirement: "Python", status: "erfüllt", note: "ok" }],
  cv_pdf_path: `packages/${ID}/Lebenslauf_Max.pdf`, letter_pdf_path: `packages/${ID}/Anschreiben_X_Max.pdf`,
  en_cv_pdf_path: null, en_letter_pdf_path: null,
  jobs: { company_name: "MDIS Consulting", title: "Initiativbewerbung", url: "", closed_at: null },
};

function mockRes() {
  const res = { headers: {}, code: 200, body: undefined };
  res.setHeader = (k, v) => { res.headers[k] = v; };
  res.status = (c) => { res.code = c; return res; };
  res.json = (b) => { res.body = b; return res; };
  res.end = () => res;
  return res;
}
const req = (over = {}) => ({ method: "GET", headers: { "x-dashboard-password": "geheim" }, query: {}, ...over });

async function withEnv(fetchImpl, run) {
  const saved = { fetch: globalThis.fetch, env: { ...process.env } };
  Object.assign(process.env, ENV);
  globalThis.fetch = fetchImpl;
  try {
    return await run();
  } finally {
    globalThis.fetch = saved.fetch;
    for (const k of Object.keys(ENV)) {
      if (k in saved.env) process.env[k] = saved.env[k]; else delete process.env[k];
    }
  }
}

test("detail shows which files exist, never their paths", () => {
  const d = applicationDetail(ROW);
  assert.deepEqual(d.files, { cv: true, letter: true, cv_en: false, letter_en: false });
  assert.equal(d.company, "MDIS Consulting");
  assert.ok(!JSON.stringify(d).includes("packages/"));
  assert.equal(isUuid(ID), true);
  assert.equal(isUuid("../etc/passwd"), false);
});

test("guard needs the right method and password and a configured server", async () => {
  const noEnv = {};
  assert.equal(await guard(req({ method: "POST" }), mockRes(), "GET", ENV), false);
  const res = mockRes();
  assert.equal(await guard(req({ headers: {} }), res, "GET", ENV), false);
  assert.equal(res.code, 401);
  const unconfigured = mockRes();
  assert.equal(await guard(req(), unconfigured, "GET", noEnv), false);
  assert.equal(unconfigured.code, 500);
  const ok = mockRes();
  assert.equal(await guard(req(), ok, "GET", ENV), true);
  assert.equal(ok.headers["Cache-Control"], "no-store");
});

test("signed link: asks storage for a five-minute link on the private bucket", async () => {
  const seen = [];
  const db = makeDetailDb(ENV, async (url, init) => {
    seen.push([url, init.method, init.body]);
    return { ok: true, json: async () => ({ signedURL: "/object/sign/cv-assets/p.pdf?token=abc" }) };
  });
  const url = await db.signedUrl("packages/a b/Lebenslauf.pdf");
  assert.equal(url, "https://x.supabase.co/storage/v1/object/sign/cv-assets/p.pdf?token=abc");
  assert.ok(seen[0][0].endsWith("/object/sign/cv-assets/packages/a%20b/Lebenslauf.pdf"));
  assert.equal(JSON.parse(seen[0][2]).expiresIn, 300);
});

test("/api/file returns a link only for files that exist and rejects bad input", async () => {
  const fetchImpl = async (url) => {
    if (url.includes("/storage/v1/object/sign/")) {
      return { ok: true, json: async () => ({ signedURL: "/object/sign/cv-assets/x?token=t" }) };
    }
    return { ok: true, json: async () => [ROW] };
  };
  await withEnv(fetchImpl, async () => {
    const good = mockRes();
    await file(req({ query: { id: ID, kind: "cv" } }), good);
    assert.equal(good.code, 200);
    assert.ok(good.body.url.startsWith("https://x.supabase.co/storage/v1/object/sign/"));
    const missing = mockRes();
    await file(req({ query: { id: ID, kind: "cv_en" } }), missing);
    assert.equal(missing.code, 404);
    const bad = mockRes();
    await file(req({ query: { id: ID, kind: "../../x" } }), bad);
    assert.equal(bad.code, 400);
    const wrongPassword = mockRes();
    await file(req({ headers: { "x-dashboard-password": "nope" }, query: { id: ID, kind: "cv" } }), wrongPassword);
    assert.equal(wrongPassword.code, 401);
  });
});

test("/api/application returns the detail and 404 for unknown ids", async () => {
  let rows = [ROW];
  await withEnv(async () => ({ ok: true, json: async () => rows }), async () => {
    const res = mockRes();
    await application(req({ query: { id: ID } }), res);
    assert.equal(res.code, 200);
    assert.equal(res.body.coverLetter, "Sehr geehrte Damen und Herren,");
    rows = [];
    const none = mockRes();
    await application(req({ query: { id: ID } }), none);
    assert.equal(none.code, 404);
  });
});

test("/api/status changes the status of an existing application only", async () => {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push([init.method, url, init.body ? JSON.parse(init.body) : null]);
    if (init.method === "GET") return { ok: true, json: async () => [ROW] };
    return { ok: true, json: async () => [] };
  };
  await withEnv(fetchImpl, async () => {
    const res = mockRes();
    await status(req({ method: "POST", body: { id: ID, status: "beworben" } }), res);
    assert.equal(res.code, 200);
    const patch = calls.find((c) => c[0] === "PATCH");
    assert.equal(patch[2].status, "beworben");
    const bad = mockRes();
    await status(req({ method: "POST", body: { id: ID, status: "hacked" } }), bad);
    assert.equal(bad.code, 400);
    const wrongMethod = mockRes();
    await status(req({ method: "GET" }), wrongMethod);
    assert.equal(wrongMethod.code, 405);
  });
});

function packageFakes({ app = { cv_pdf_path: "p.pdf", selection: { headline: "x" } }, last = null, configured = true } = {}) {
  const calls = [];
  return {
    calls,
    db: {
      getApplication: async () => app,
      lastDecisionAt: async () => last,
      addDecision: async (id, action) => calls.push(["decision", id, action]),
    },
    gh: { configured, dispatchPackage: async (id, lang) => calls.push(["dispatch", id, lang]) },
  };
}
const COOLDOWN = 5 * 60 * 1000;

test("startPackage builds German for any job and records the decision", async () => {
  const f = packageFakes({ app: null });
  const r = await startPackage({ ...f, id: ID, language: "de", cooldownMs: COOLDOWN });
  assert.equal(r.code, 200);
  assert.deepEqual(f.calls, [["dispatch", ID, "de"], ["decision", ID, "package"]]);
});

test("startPackage builds English only on top of a stored German package", async () => {
  const ok = packageFakes();
  assert.equal((await startPackage({ ...ok, id: ID, language: "en", cooldownMs: COOLDOWN })).code, 200);
  assert.deepEqual(ok.calls[0], ["dispatch", ID, "en"]);
  for (const app of [null, { cv_pdf_path: "p.pdf", selection: null }, { cv_pdf_path: null, selection: {} }]) {
    const f = packageFakes({ app });
    const r = await startPackage({ ...f, id: ID, language: "en", cooldownMs: COOLDOWN });
    assert.equal(r.code, 409);
    assert.equal(f.calls.length, 0);
  }
});

test("startPackage respects the cooldown, the setup and bad input", async () => {
  const now = () => new Date("2026-11-02T12:00:00Z");
  const busy = packageFakes({ last: new Date("2026-11-02T11:58:00Z") });
  assert.equal((await startPackage({ ...busy, id: ID, language: "de", now, cooldownMs: COOLDOWN })).code, 429);
  assert.equal(busy.calls.length, 0);
  const idle = packageFakes({ last: new Date("2026-11-02T11:50:00Z") });
  assert.equal((await startPackage({ ...idle, id: ID, language: "de", now, cooldownMs: COOLDOWN })).code, 200);
  assert.equal((await startPackage({ ...packageFakes({ configured: false }), id: ID, language: "de", cooldownMs: COOLDOWN })).code, 503);
  assert.equal((await startPackage({ ...packageFakes(), id: "nope", language: "de", cooldownMs: COOLDOWN })).code, 400);
  assert.equal((await startPackage({ ...packageFakes(), id: ID, language: "fr", cooldownMs: COOLDOWN })).code, 400);
});

test("the package workflow gets the language as input", async () => {
  let body;
  const gh = makeGithub({ GITHUB_DISPATCH_TOKEN: "t" }, async (url, init) => { body = JSON.parse(init.body); return { status: 204 }; });
  await gh.dispatchPackage(ID, "en");
  assert.deepEqual(body.inputs, { job_id: ID, language: "en" });
  await gh.dispatchPackage(ID);
  assert.equal(body.inputs.language, "de");
});

test("remaining credit counts down from the value entered, not from zero", () => {
  assert.equal(creditFrom({}, 5), null);
  const c = creditFrom({ api_credit_usd: "20", api_credit_base_cost: "3", api_credit_set_at: "2026-11-02T10:00:00Z" }, 5.5);
  assert.equal(c.startUsd, 20);
  assert.equal(c.remainingUsd, 17.5); // 20 - (5.5 - 3)
  assert.equal(c.percent, 88);
  assert.ok(Math.abs(c.remainingEur - 17.5 * 0.92) < 1e-9);
  assert.equal(creditFrom({ api_credit_usd: "1", api_credit_base_cost: "0" }, 9).percent, 0); // never negative percent
});

test("setCredit stores the amount in USD with the spend so far", async () => {
  const stored = [];
  const db = { totalCost: async () => 2.5, setState: async (e) => stored.push(e) };
  assert.equal((await setCredit({ db, amount: "18,40", currency: "USD" })).code, 200);
  assert.equal(stored[0].api_credit_usd, "18.4000");
  assert.equal(stored[0].api_credit_base_cost, "2.500000");
  await setCredit({ db, amount: "9.2", currency: "EUR" });
  assert.equal(stored[1].api_credit_usd, "10.0000"); // 9.2 EUR / 0.92
  for (const bad of [{ amount: "abc", currency: "USD" }, { amount: "-1", currency: "USD" }, { amount: "5", currency: "GBP" }]) {
    assert.equal((await setCredit({ db, ...bad })).code, 400);
  }
});

test("startImport accepts a link or pasted text and rejects the rest", async () => {
  const calls = [];
  const f = { db: { createImport: async (e) => { calls.push(["create", e]); return ID; } }, gh: { configured: true, dispatchImport: async (id) => calls.push(["dispatch", id]) } };
  assert.equal((await startImport({ ...f, body: { url: " https://firma.de/job/1 " } })).code, 200);
  assert.deepEqual(calls[0], ["create", { url: "https://firma.de/job/1" }]);
  assert.deepEqual(calls[1], ["dispatch", ID]);
  const text = "Aufgaben: Entwicklung von KI-Anwendungen mit Python und Cloud. ".repeat(3);
  assert.equal((await startImport({ ...f, body: { company: "Acme", title: "Dev", description: text } })).code, 200);
  assert.equal(calls[2][1].company, "Acme");
  const bare = await startImport({ ...f, body: { description: text + text } }); // no company/title: the model reads them
  assert.equal(bare.code, 200);
  assert.equal(calls.at(-2)[1].company, undefined);
  for (const body of [{}, { url: "ftp://x" }, { url: "javascript:alert(1)" }, { company: "A", title: "B", description: "zu kurz" }, { description: "kurz" }]) {
    assert.equal((await startImport({ ...f, body })).code, 400, JSON.stringify(body));
  }
  assert.equal((await startImport({ db: f.db, gh: { configured: false }, body: { url: "https://a.de" } })).code, 503);
});
