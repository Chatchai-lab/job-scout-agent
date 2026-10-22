import assert from "node:assert/strict";
import { test } from "node:test";

import { cardView, letterPath, listView, sendName, sortApplications } from "../lib/applications.js";
import { handleUpdate, makeDb, parseCallback } from "../lib/handler.js";

const A = "123e4567-e89b-42d3-a456-426614174001";
const B = "123e4567-e89b-42d3-a456-426614174002";
const CHAT = "1234567890";

const app = (id, status, over = {}) => ({
  job_id: id,
  status,
  applied_at: null,
  updated_at: "2026-10-20T10:00:00Z",
  cv_pdf_path: null,
  letter_pdf_path: null,
  jobs: { company_name: "Firma & Co", title: "Forward Deployed <Engineer> ", url: "https://example.com/j" },
  ...over,
});

function fakes({ apps = [], bytes = new Uint8Array([1, 2, 3]) } = {}) {
  const calls = [];
  const db = {
    listApplications: async () => apps,
    getApplication: async (id) => apps.find((a) => a.job_id === id) ?? null,
    setStatus: async (id, status) => {
      calls.push(["setStatus", id, status]);
      const found = apps.find((a) => a.job_id === id);
      if (found) found.status = status;
    },
    downloadAsset: async (path) => {
      calls.push(["download", path]);
      return bytes;
    },
  };
  const tg = {
    answer: async (_id, text, alert) => calls.push(["answer", text, !!alert]),
    send: async (chat, text, markup) => calls.push(["send", text, markup]),
    edit: async (chat, msg, text, markup) => calls.push(["edit", text, markup]),
    sendDocument: async (chat, data, name, caption) => calls.push(["doc", name, caption, data.length]),
    setCommands: async () => calls.push(["commands"]),
  };
  return { db, tg, calls, chatId: CHAT };
}

const callback = (data, chat = CHAT) => ({
  callback_query: { id: "cb", data, message: { message_id: 9, chat: { id: Number(chat) } } },
});
const message = (text, chat = CHAT) => ({ message: { text, chat: { id: Number(chat) } } });
const find = (calls, kind) => calls.find((c) => c[0] === kind);

test("callback parsing for the control center", () => {
  assert.deepEqual(parseCallback("apps"), { kind: "apps" });
  assert.deepEqual(parseCallback(`app:${A}`), { kind: "app", jobId: A });
  assert.deepEqual(parseCallback(`st:beworben:${A}`), { kind: "st", status: "beworben", jobId: A });
  assert.deepEqual(parseCallback(`cv:${A}`), { kind: "cv", jobId: A });
  assert.equal(parseCallback(`st:wrong:${A}`).kind, "invalid");
  assert.equal(parseCallback("app:not-a-uuid").kind, "invalid");
});

test("list is sorted by progress and every row opens its card", () => {
  const sorted = sortApplications([app(A, "gemerkt"), app(B, "interview")]);
  assert.deepEqual(sorted.map((a) => a.job_id), [B, A]);
  const view = listView([app(A, "gemerkt"), app(B, "interview")]);
  assert.ok(view.text.includes("(2)") && view.text.includes("🗣 1") && view.text.includes("👀 1"));
  assert.equal(view.markup.inline_keyboard[0][0].callback_data, `app:${B}`);
  assert.ok(view.markup.inline_keyboard[0][0].text.startsWith("🗣 Firma & Co"));
  assert.ok(listView([]).text.includes("Noch keine Bewerbungen"));
});

test("card escapes text, marks the current status and offers files only with a package", () => {
  const plain = cardView(app(A, "gemerkt"));
  assert.ok(plain.text.includes("Forward Deployed &lt;Engineer&gt;") && plain.text.includes("Firma &amp; Co"));
  const buttons = plain.markup.inline_keyboard.flat();
  assert.ok(!buttons.some((b) => b.callback_data?.startsWith("cv:")));
  assert.equal(buttons.find((b) => b.callback_data === `st:gemerkt:${A}`).text, "↩️ Zurücksetzen");

  const withPackage = cardView(app(A, "beworben", { cv_pdf_path: "packages/x/CV.pdf", applied_at: "2026-10-21T10:00:00Z" }));
  const all = withPackage.markup.inline_keyboard.flat();
  assert.ok(all.some((b) => b.callback_data === `cv:${A}`) && all.some((b) => b.callback_data === `ltr:${A}`));
  assert.equal(all.find((b) => b.callback_data === `st:beworben:${A}`).text, "• ✅ Beworben");
  assert.ok(withPackage.text.includes("Beworben am: 21.10.2026"));
  assert.equal(all.find((b) => b.callback_data === `st:paket:${A}`).text, "↩️ Zurücksetzen");
  assert.equal(all.find((b) => b.url).url, "https://example.com/j");
});

test("card warns when the posting is no longer listed", () => {
  const open = cardView(app(A, "gemerkt"));
  assert.ok(!open.text.includes("nicht mehr ausgeschrieben"));
  const gone = app(A, "gemerkt");
  gone.jobs.closed_at = "2026-10-20T10:00:00Z";
  assert.ok(cardView(gone).text.includes("⚠️ Stelle nicht mehr ausgeschrieben seit 20.10.2026"));
});

test("old packages are found under their former names and sent with friendly file names", () => {
  assert.equal(letterPath({ cv_pdf_path: `packages/${A}.pdf` }), `packages/${A}-anschreiben.pdf`);
  assert.equal(letterPath({ cv_pdf_path: "packages/x/CV.pdf", letter_pdf_path: "packages/x/Brief.pdf" }), "packages/x/Brief.pdf");
  assert.equal(letterPath({ cv_pdf_path: null }), null);
  assert.equal(sendName(`packages/${A}.pdf`, "cv"), "Lebenslauf.pdf");
  assert.equal(sendName(`packages/${A}-anschreiben.pdf`, "ltr"), "Anschreiben.pdf");
  assert.equal(sendName("packages/x/Lebenslauf_Max_Mustermann.pdf", "cv"), "Lebenslauf_Max_Mustermann.pdf");
});

test("/start registers the menu command, /bewerbungen sends the list", async () => {
  const f = fakes({ apps: [app(A, "paket")] });
  assert.equal(await handleUpdate(message("/start"), f), "start");
  assert.ok(find(f.calls, "commands"));
  assert.equal(await handleUpdate(message("/bewerbungen@job_bot"), f), "list");
  const sends = f.calls.filter((c) => c[0] === "send");
  assert.equal(sends.length, 2);
  assert.ok(sends[0][1].includes("bereit"));
  assert.equal(sends[1][2].inline_keyboard.length, 1);  // the list, one row per application
  assert.equal(await handleUpdate(message("hallo"), f), "ignored");
});

test("messages from other chats are ignored", async () => {
  const f = fakes({ apps: [app(A, "paket")] });
  assert.equal(await handleUpdate(message("/bewerbungen", "999"), f), "wrong_chat");
  assert.equal(f.calls.length, 0);
});

test("opening a card edits the list message in place", async () => {
  const f = fakes({ apps: [app(A, "paket")] });
  assert.equal(await handleUpdate(callback(`app:${A}`), f), "card");
  assert.ok(find(f.calls, "edit")[1].includes("Paket gebaut"));
  assert.equal(await handleUpdate(callback("apps"), f), "list");
  assert.equal(await handleUpdate(callback(`app:${B}`), f), "app_missing");
});

test("a status tap stores the status and refreshes the card", async () => {
  const f = fakes({ apps: [app(A, "paket", { cv_pdf_path: "packages/x/CV.pdf" })] });
  assert.equal(await handleUpdate(callback(`st:beworben:${A}`), f), "status_set");
  assert.deepEqual(find(f.calls, "setStatus"), ["setStatus", A, "beworben"]);
  assert.ok(find(f.calls, "edit")[1].includes("Beworben"));
});

test("CV and letter are sent again from storage under their file names", async () => {
  const f = fakes({
    apps: [app(A, "paket", { cv_pdf_path: "packages/x/Lebenslauf_Max.pdf", letter_pdf_path: "packages/x/Anschreiben_Firma_Max.pdf" })],
  });
  assert.equal(await handleUpdate(callback(`cv:${A}`), f), "file_sent");
  assert.equal(await handleUpdate(callback(`ltr:${A}`), f), "file_sent");
  const docs = f.calls.filter((c) => c[0] === "doc");
  assert.deepEqual(docs.map((d) => d[1]), ["Lebenslauf_Max.pdf", "Anschreiben_Firma_Max.pdf"]);
  assert.equal(docs[0][3], 3);
});

test("file request without a package explains instead of failing", async () => {
  const f = fakes({ apps: [app(A, "gemerkt")] });
  assert.equal(await handleUpdate(callback(`cv:${A}`), f), "file_missing");
  assert.equal(f.calls.filter((c) => c[0] === "doc").length, 0);
});

test("makeDb status update clears or sets the application date", async () => {
  const seen = [];
  const fetchFn = async (url, init) => {
    seen.push([init.method, url, init.body]);
    return { ok: true, status: 204, json: async () => [] };
  };
  const db = makeDb({ SUPABASE_URL: "https://x.supabase.co", SUPABASE_SERVICE_KEY: "k" }, fetchFn);
  await db.setStatus(A, "beworben");
  assert.equal(seen.length, 2);
  assert.ok(seen[1][1].includes("applied_at=is.null"));
  seen.length = 0;
  await db.setStatus(A, "paket");
  assert.equal(seen.length, 1);
  assert.equal(JSON.parse(seen[0][2]).applied_at, null);
});
