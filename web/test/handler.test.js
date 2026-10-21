import assert from "node:assert/strict";
import { test } from "node:test";

import { handleUpdate, makeDb, parseCallback } from "../lib/handler.js";

const JOB = "123e4567-e89b-42d3-a456-426614174000";
const CHAT = "1234567890";

function fakes({ existing = [] } = {}) {
  const calls = [];
  const db = {
    hasDecision: async (id, action) => existing.includes(action),
    addDecision: async (id, action) => calls.push(["add", id, action]),
    setReason: async (id, tag) => calls.push(["reason", id, tag]),
    markSaved: async (id) => calls.push(["saved", id]),
  };
  const tg = {
    answer: async (id, text, alert) => calls.push(["answer", text, !!alert]),
    setKeyboard: async (chat, msg, markup) => calls.push(["keyboard", markup]),
  };
  return { db, tg, calls, chatId: CHAT };
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
  assert.equal(markup.inline_keyboard.flat().length, 6);
});

test("a reason is stored, skip stores nothing", async () => {
  const a = fakes();
  await handleUpdate(update(`why:boring_task:${JOB}`), a);
  assert.deepEqual(a.calls[0], ["reason", JOB, "boring_task"]);
  const b = fakes();
  await handleUpdate(update(`why:skip:${JOB}`), b);
  assert.equal(b.calls.filter((c) => c[0] === "reason").length, 0);
});

test("package button only answers for now", async () => {
  const f = fakes();
  assert.equal(await handleUpdate(update(`pkg:${JOB}`), f), "package_pending");
  assert.equal(f.calls.filter((c) => c[0] === "add").length, 0);
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
