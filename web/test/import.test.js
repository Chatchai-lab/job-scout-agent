import assert from "node:assert/strict";
import { test } from "node:test";

import { parseJobImport } from "../lib/applications.js";
import { handleUpdate, makeDb, makeGithub } from "../lib/handler.js";

const CHAT = "1234567890";
const JOB = "123e4567-e89b-42d3-a456-426614174009";
const TEXT = "Aufgaben: Entwicklung von KI-Anwendungen mit Python und Cloud. ".repeat(3);

function fakes({ configured = true, failDispatch = false } = {}) {
  const calls = [];
  const db = {
    createImport: async (entry) => {
      calls.push(["createImport", entry]);
      return JOB;
    },
  };
  const tg = { send: async (chat, text) => calls.push(["send", text]) };
  const gh = {
    configured,
    dispatchImport: async (id) => {
      calls.push(["dispatchImport", id]);
      if (failDispatch) throw new Error("github dispatch -> 500");
    },
  };
  return { db, tg, gh, calls, chatId: CHAT };
}
const message = (text) => ({ message: { text, chat: { id: Number(CHAT) } } });

test("parsing: bare link, Stelle + link, Stelle + pasted text, help, and unrelated text", () => {
  assert.deepEqual(parseJobImport("https://firma.de/jobs/1"), { url: "https://firma.de/jobs/1" });
  assert.deepEqual(parseJobImport("Stelle https://firma.de/jobs/1"), { url: "https://firma.de/jobs/1" });
  assert.deepEqual(parseJobImport("job   https://firma.de/x?a=1&b=2 "), { url: "https://firma.de/x?a=1&b=2" });
  const pasted = parseJobImport(`Stelle Beispiel GmbH: Software Engineer (m/w/d)\n${TEXT}\nhttps://firma.de/j/2`);
  assert.equal(pasted.company, "Beispiel GmbH");
  assert.equal(pasted.title, "Software Engineer (m/w/d)");
  assert.equal(pasted.url, "https://firma.de/j/2");
  assert.ok(pasted.description.startsWith("Aufgaben"));
  assert.deepEqual(parseJobImport("Stelle Beispiel GmbH: Titel\nzu kurz"), { help: true });
  assert.deepEqual(parseJobImport("Stelle irgendwas"), { help: true });
  assert.equal(parseJobImport("Hallo, schau mal https://firma.de"), null);
  assert.equal(parseJobImport("Initiativ Merck: Werkstudent"), null);
  assert.equal(parseJobImport(""), null);
});

test("a link creates the placeholder and starts the import", async () => {
  const f = fakes();
  assert.equal(await handleUpdate(message("https://firma.de/jobs/1"), f), "import_started");
  assert.deepEqual(f.calls.find((c) => c[0] === "createImport")[1], { url: "https://firma.de/jobs/1" });
  assert.deepEqual(f.calls.find((c) => c[0] === "dispatchImport"), ["dispatchImport", JOB]);
  assert.ok(f.calls.find((c) => c[0] === "send")[1].includes("Ich lese die Stelle"));
});

test("unparsable 'Stelle' message sends the help text and creates nothing", async () => {
  const f = fakes();
  assert.equal(await handleUpdate(message("Stelle irgendwas"), f), "import_help");
  assert.ok(!f.calls.some((c) => c[0] === "createImport"));
  assert.ok(f.calls.find((c) => c[0] === "send")[1].includes("Stelle https://"));
});

test("without a GitHub token nothing is created", async () => {
  const f = fakes({ configured: false });
  assert.equal(await handleUpdate(message("https://firma.de/jobs/1"), f), "import_unconfigured");
  assert.ok(!f.calls.some((c) => c[0] === "createImport"));
});

test("a failed dispatch tells the user and rethrows for the log", async () => {
  const f = fakes({ failDispatch: true });
  await assert.rejects(handleUpdate(message("https://firma.de/jobs/1"), f), /github dispatch/);
  assert.ok(f.calls.filter((c) => c[0] === "send").some((c) => c[1].includes("nicht starten")));
});

test("other chats are ignored", async () => {
  const f = fakes();
  const other = { message: { text: "https://firma.de/jobs/1", chat: { id: 1 } } };
  assert.equal(await handleUpdate(other, f), "wrong_chat");
  assert.equal(f.calls.length, 0);
});

test("db: new link inserts a closed placeholder, a known link reuses its row", async () => {
  const calls = [];
  let existing = [];
  const fetchFn = async (url, init) => {
    calls.push([init.method, url, init.body ? JSON.parse(init.body) : null]);
    if (init.method === "GET") return { ok: true, json: async () => existing };
    return { ok: true, json: async () => [{ id: JOB }] };
  };
  const db = makeDb({ SUPABASE_URL: "https://x.supabase.co", SUPABASE_SERVICE_KEY: "k" }, fetchFn);
  assert.equal(await db.createImport({ url: "https://firma.de/a?x=1&y=2" }), JOB);
  const post = calls.find((c) => c[0] === "POST")[2];
  assert.equal(post.source, "manual");
  assert.equal(post.kind, "posting");
  assert.equal(post.url, "https://firma.de/a?x=1&y=2");
  assert.ok(post.closed_at, "placeholder must be hidden until it is imported");
  assert.ok(calls.find((c) => c[0] === "GET")[1].includes(encodeURIComponent("https://firma.de/a?x=1&y=2")));

  calls.length = 0;
  existing = [{ id: "123e4567-e89b-42d3-a456-426614174111" }];
  assert.equal(await db.createImport({ url: "https://firma.de/a" }), existing[0].id);
  assert.ok(!calls.some((c) => c[0] === "POST"));

  calls.length = 0;
  await db.createImport({ company: "Acme", title: "IT", description: TEXT, url: "" });
  assert.ok(!calls.some((c) => c[0] === "GET"));
  assert.equal(calls.find((c) => c[0] === "POST")[2].company_name, "Acme");
});

test("github: import and package use their own workflow files", async () => {
  const urls = [];
  const gh = makeGithub(
    { GITHUB_DISPATCH_TOKEN: "t" },
    async (url) => { urls.push(url); return { status: 204 }; },
  );
  await gh.dispatchImport(JOB);
  await gh.dispatchPackage(JOB);
  assert.ok(urls[0].endsWith("/workflows/import-job.yml/dispatches"));
  assert.ok(urls[1].endsWith("/workflows/package.yml/dispatches"));
});
