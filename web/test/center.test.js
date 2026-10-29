import assert from "node:assert/strict";
import { test } from "node:test";

import {
  cardView,
  initiativeCard,
  initiativeListView,
  letterPath,
  listView,
  parseInitiativeRequest,
  sendName,
  sortApplications,
  statusView,
} from "../lib/applications.js";
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

function fakes({ apps = [], inits = [], snapshot = null, bytes = new Uint8Array([1, 2, 3]) } = {}) {
  const calls = [];
  const db = {
    listApplications: async () => apps,
    listInitiatives: async () => inits,
    statusSnapshot: async () => snapshot,
    getJob: async (id) => inits.find((j) => j.id === id) ?? null,
    createInitiative: async (company, context) => {
      calls.push(["createInitiative", company, context]);
      return { id: A, company_name: company, location: null, url: "", description: context || null };
    },
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

const init = (id, over = {}) => ({
  id,
  company_name: "Beispiel <GmbH>",
  location: "München",
  url: "https://example.com/karriere",
  description: "Softwarehaus & Beratung",
  ...over,
});

test("initiative requests are parsed from plain messages", () => {
  assert.deepEqual(parseInitiativeRequest("Initiativ Mayflower"), { company: "Mayflower", context: "" });
  assert.deepEqual(parseInitiativeRequest("initiativ Mayflower: KI-Beratung in Karlsruhe"), {
    company: "Mayflower",
    context: "KI-Beratung in Karlsruhe",
  });
  assert.equal(parseInitiativeRequest("Initiativ"), null);
  assert.equal(parseInitiativeRequest("Hallo"), null);
});

test("initiative list and card escape text and offer the package button", () => {
  const view = initiativeListView([init(A)]);
  assert.equal(view.markup.inline_keyboard[0][0].callback_data, `ini:${A}`);
  assert.ok(initiativeListView([]).text.includes("Noch keine Initiativ-Anzeigen"));
  assert.equal(initiativeListView([init(A), init(B)]).markup.inline_keyboard.length, 1);  // same company once
  const card = initiativeCard(init(A));
  assert.ok(card.text.includes("Beispiel &lt;GmbH&gt;") && card.text.includes("Softwarehaus &amp; Beratung"));
  const buttons = card.markup.inline_keyboard.flat();
  assert.ok(buttons.some((b) => b.callback_data === `pkg:${A}`));
  assert.ok(buttons.some((b) => b.callback_data === "inis"));
  const noUrl = initiativeCard(init(A, { url: "" })).markup.inline_keyboard.flat();
  assert.ok(!noUrl.some((b) => b.url));
});

test("/initiativ lists, a tap opens the card, and a message creates a new entry", async () => {
  const f = fakes({ inits: [init(A)] });
  assert.equal(await handleUpdate(message("/initiativ"), f), "initiatives");
  assert.equal(await handleUpdate(callback(`ini:${A}`), f), "initiative_card");
  assert.equal(await handleUpdate(callback(`ini:${B}`), f), "initiative_missing");
  assert.equal(await handleUpdate(callback("inis"), f), "initiatives");
  assert.equal(await handleUpdate(message("Initiativ Neue Firma: macht KI"), f), "initiative_created");
  assert.deepEqual(find(f.calls, "createInitiative"), ["createInitiative", "Neue Firma", "macht KI"]);
});

const SNAP = {
  companies: 180,
  openJobs: 9000,
  initiatives: 12,
  qualifying: 58,
  unseen: 58,
  statuses: { paket: 2, gemerkt: 1 },
  costUsd: 0.75,
  paused: true,
};

test("status view shows the counts, the budget share and the pause", () => {
  const text = statusView(SNAP);
  assert.ok(text.includes("Firmen aktiv: 180") && text.includes("Passende Stellen: 58"));
  assert.ok(text.includes("📦 2") && text.includes("👀 1"));
  assert.ok(text.includes("0.75 $ ≈ 0.69 € von 5 € (14 %)"));
  assert.ok(text.includes("🔕 Benachrichtigungen pausiert"));
  assert.ok(statusView({ ...SNAP, paused: false, statuses: {} }).includes("🔔 Benachrichtigungen aktiv"));
  assert.ok(statusView({ ...SNAP, statuses: {} }).includes("Bewerbungen: keine"));
});

test("/status sends the snapshot", async () => {
  const f = fakes({ snapshot: SNAP });
  assert.equal(await handleUpdate(message("/status"), f), "status");
  assert.ok(find(f.calls, "send")[1].includes("Job Scout – Status"));
});

test("initiative card shows the status and a way to change it once an application exists", () => {
  const plain = initiativeCard(init(A)).markup.inline_keyboard.flat();
  assert.ok(!plain.some((b) => b.callback_data === `app:${A}`));
  const withApp = initiativeCard(init(A), { status: "paket" });
  assert.ok(withApp.text.includes("Status: 📦 Paket gebaut"));
  assert.ok(withApp.markup.inline_keyboard.flat().some((b) => b.callback_data === `app:${A}`));
});

test("application card of an open application has no empty ad-link button", () => {
  const noUrl = cardView(app(A, "paket", { jobs: { company_name: "MDIS", title: "Initiativbewerbung", url: "" } }));
  const buttons = noUrl.markup.inline_keyboard.flat();
  assert.ok(!buttons.some((b) => "url" in b), "Telegram rejects an empty url");
  assert.ok(buttons.some((b) => b.callback_data === `st:beworben:${A}`));
  assert.ok(buttons.some((b) => b.callback_data === "apps"));
  const withUrl = cardView(app(A, "paket")).markup.inline_keyboard.flat();
  assert.ok(withUrl.some((b) => b.url === "https://example.com/j"));
});
