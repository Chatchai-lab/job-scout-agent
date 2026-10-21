import assert from "node:assert/strict";
import { test } from "node:test";

import {
  handleUpdate,
  jobKeyboard,
  makeDb,
  makeGithub,
  PACKAGE_COOLDOWN_MS,
  parseCallback,
} from "../lib/handler.js";

const JOB = "123e4567-e89b-42d3-a456-426614174000";
const CHAT = "1234567890";

function fakes({ existing = [], lastPackage = null, githubOk = true, configured = true } = {}) {
  const calls = [];
  const gh = {
    configured,
    dispatchPackage: async (id) => {
      if (!githubOk) throw new Error("github dispatch -> 403");
      calls.push(["dispatch", id]);
    },
  };
  const db = {
    lastDecisionAt: async () => lastPackage,
    hasDecision: async (id, action) => existing.includes(action),
    addDecision: async (id, action) => calls.push(["add", id, action]),
    setReason: async (id, tag) => calls.push(["reason", id, tag]),
    markSaved: async (id) => calls.push(["saved", id]),
    removeDecisions: async (id) => calls.push(["removed", id]),
  };
  const tg = {
    answer: async (id, text, alert) => calls.push(["answer", text, !!alert]),
    setKeyboard: async (chat, msg, markup) => calls.push(["keyboard", markup]),
  };
  return { db, tg, gh, calls, chatId: CHAT };
}

const update = (data, chat = CHAT) => ({
  callback_query: { id: "cb1", data, message: { message_id: 5, chat: { id: Number(chat) } } },
});

test("parseCallback accepts the known shapes and rejects the rest", () => {
  assert.deepEqual(parseCallback(`save:${JOB}`), { kind: "save", jobId: JOB });
  assert.deepEqual(parseCallback(`why:too_senior:${JOB}`), { kind: "why", tag: "too_senior", jobId: JOB });
  assert.equal(parseCallback("save:not-a-uuid").kind, "invalid");
  assert.equal(parseCallback(`why:made_up:${JOB}`).kind, "invalid");
  assert.equal(parseCallback(undefined).kind, "invalid");
});

test("save writes a decision and the tracker row", async () => {
  const f = fakes();
  assert.equal(await handleUpdate(update(`save:${JOB}`), f), "saved");
  assert.deepEqual(f.calls[0], ["add", JOB, "save"]);
  assert.deepEqual(f.calls[1], ["saved", JOB]);
});

test("double tap on save does not create a second decision", async () => {
  const f = fakes({ existing: ["save"] });
  await handleUpdate(update(`save:${JOB}`), f);
  assert.equal(f.calls.filter((c) => c[0] === "add").length, 0);
});

test("reject stores the decision and offers the reason keyboard", async () => {
  const f = fakes();
  assert.equal(await handleUpdate(update(`rej:${JOB}`), f), "rejected");
  assert.deepEqual(f.calls[0], ["add", JOB, "reject"]);
  const markup = f.calls.find((c) => c[0] === "keyboard")[1];
  assert.equal(markup.inline_keyboard.flat().length, 7); // 5 reasons + skip + undo
});

test("a reason is stored, skip stores nothing", async () => {
  const a = fakes();
  await handleUpdate(update(`why:boring_task:${JOB}`), a);
  assert.deepEqual(a.calls[0], ["reason", JOB, "boring_task"]);
  const b = fakes();
  await handleUpdate(update(`why:skip:${JOB}`), b);
  assert.equal(b.calls.filter((c) => c[0] === "reason").length, 0);
});

test("package button starts the workflow and records the decision", async () => {
  const f = fakes();
  assert.equal(await handleUpdate(update(`pkg:${JOB}`), f), "package_started");
  assert.deepEqual(f.calls.filter((c) => c[0] !== "answer"), [["dispatch", JOB], ["add", JOB, "package"]]);
  assert.ok(f.calls.find((c) => c[0] === "answer")[1].includes("2 bis 3 Minuten"));
});

test("a second tap while the package is being built does not start it again", async () => {
  const now = new Date("2026-10-22T10:00:00Z");
  const f = { ...fakes({ lastPackage: new Date(now - 60 * 1000) }), now: () => now };
  assert.equal(await handleUpdate(update(`pkg:${JOB}`), f), "package_running");
  assert.equal(f.calls.filter((c) => c[0] === "dispatch").length, 0);
});

test("after the cooldown a package can be rebuilt", async () => {
  const now = new Date("2026-10-22T10:00:00Z");
  const old = new Date(now - PACKAGE_COOLDOWN_MS - 1000);
  const f = { ...fakes({ lastPackage: old }), now: () => now };
  assert.equal(await handleUpdate(update(`pkg:${JOB}`), f), "package_started");
});

test("a failed dispatch tells the user and records nothing", async () => {
  const f = fakes({ githubOk: false });
  assert.equal(await handleUpdate(update(`pkg:${JOB}`), f), "package_failed");
  assert.equal(f.calls.filter((c) => c[0] === "add").length, 0);
});

test("without a GitHub token the package button explains instead of failing silently", async () => {
  const f = fakes({ configured: false });
  assert.equal(await handleUpdate(update(`pkg:${JOB}`), f), "package_unconfigured");
  assert.equal(f.calls.filter((c) => c[0] === "dispatch" || c[0] === "add").length, 0);
});

test("makeGithub posts the dispatch with the token, the job id and only this repo", async () => {
  let seen;
  const fetchFn = async (url, init) => {
    seen = { url, init };
    return { status: 204 };
  };
  const gh = makeGithub({ GITHUB_DISPATCH_TOKEN: "t0k" }, fetchFn);
  await gh.dispatchPackage(JOB);
  assert.ok(seen.url.endsWith("/actions/workflows/package.yml/dispatches"));
  assert.equal(seen.init.headers.Authorization, "Bearer t0k");
  assert.deepEqual(JSON.parse(seen.init.body), { ref: "main", inputs: { job_id: JOB } });
  assert.equal(makeGithub({}, fetchFn).configured, false);
  await assert.rejects(() => makeGithub({ GITHUB_DISPATCH_TOKEN: "x" }, async () => ({ status: 404 })).dispatchPackage(JOB));
});

test("clicks from another chat are ignored", async () => {
  const f = fakes();
  assert.equal(await handleUpdate(update(`save:${JOB}`, "999"), f), "wrong_chat");
  assert.equal(f.calls.length, 0);
});

test("makeDb sends the service key and throws on errors", async () => {
  const seen = [];
  const fetchFn = async (url, init) => {
    seen.push([url, init.headers.apikey]);
    return { ok: false, status: 500, json: async () => [] };
  };
  const db = makeDb({ SUPABASE_URL: "https://x.supabase.co", SUPABASE_SERVICE_KEY: "k" }, fetchFn);
  await assert.rejects(() => db.addDecision(JOB, "save"));
  assert.equal(seen[0][1], "k");
  assert.ok(seen[0][0].startsWith("https://x.supabase.co/rest/v1/decisions"));
});

test("undo removes the decisions and restores the three original buttons", async () => {
  const f = fakes();
  assert.equal(await handleUpdate(update(`undo:${JOB}`), f), "undone");
  assert.deepEqual(f.calls[0], ["removed", JOB]);
  const markup = f.calls.find((c) => c[0] === "keyboard")[1];
  assert.deepEqual(markup, jobKeyboard(JOB));
  assert.deepEqual(
    markup.inline_keyboard[0].map((b) => b.callback_data),
    [`pkg:${JOB}`, `save:${JOB}`, `rej:${JOB}`],
  );
});

test("finished states and the reason keyboard offer an undo button", async () => {
  const saved = fakes();
  await handleUpdate(update(`save:${JOB}`), saved);
  const savedButtons = saved.calls.find((c) => c[0] === "keyboard")[1].inline_keyboard.flat();
  assert.ok(savedButtons.some((b) => b.callback_data === `undo:${JOB}`));

  const rejected = fakes();
  await handleUpdate(update(`rej:${JOB}`), rejected);
  const reasonButtons = rejected.calls.find((c) => c[0] === "keyboard")[1].inline_keyboard.flat();
  assert.ok(reasonButtons.some((b) => b.callback_data === `undo:${JOB}`));
});

test("makeDb undo deletes only save and reject decisions and the tracker row", async () => {
  const seen = [];
  const fetchFn = async (url, init) => {
    seen.push([init.method, url]);
    return { ok: true, status: 204, json: async () => [] };
  };
  const db = makeDb({ SUPABASE_URL: "https://x.supabase.co", SUPABASE_SERVICE_KEY: "k" }, fetchFn);
  await db.removeDecisions(JOB);
  assert.equal(seen.length, 2);
  assert.ok(seen[0][1].includes("decisions?") && seen[0][1].includes("action=in.(save,reject)"));
  assert.ok(seen[1][1].includes("applications?") && seen[1][1].includes("status=eq.gemerkt"));
  assert.ok(seen.every(([method]) => method === "DELETE"));
});
