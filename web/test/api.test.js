import assert from "node:assert/strict";
import { test } from "node:test";

import file from "../api/file.js";
import application from "../api/application.js";
import status from "../api/status.js";
import { applicationDetail, guard, isUuid, makeDetailDb } from "../lib/dashboard.js";

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
