// Telegram button callbacks: 👀 save, ❌ reject (+ one-tap reason), 📦 package (later).
// All state lives in Supabase; this function only writes `decisions` and edits the message.

import { STATUS, cardView, letterPath, listView, sendName } from "./applications.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const REASONS = {
  too_senior: "Zu senior",
  too_much_sales: "Zu viel Sales",
  company_uninteresting: "Firma uninteressant",
  boring_task: "Tätigkeit langweilig",
  other: "Sonstiges",
};

// Same three buttons the Python notifier attaches to every job message.
export function jobKeyboard(jobId) {
  return {
    inline_keyboard: [
      [
        { text: "📦 Paket", callback_data: `pkg:${jobId}` },
        { text: "👀 Merken", callback_data: `save:${jobId}` },
        { text: "❌ Verwerfen", callback_data: `rej:${jobId}` },
      ],
    ],
  };
}

const undoButton = (jobId) => ({ text: "↩️ Rückgängig", callback_data: `undo:${jobId}` });

export function reasonKeyboard(jobId) {
  const btn = (tag) => ({ text: REASONS[tag], callback_data: `why:${tag}:${jobId}` });
  return {
    inline_keyboard: [
      [btn("too_senior"), btn("too_much_sales")],
      [btn("company_uninteresting"), btn("boring_task")],
      [btn("other"), { text: "Überspringen", callback_data: `why:skip:${jobId}` }],
      [undoButton(jobId)],
    ],
  };
}

const done = (text, jobId) => ({
  inline_keyboard: [[{ text, callback_data: "noop" }, undoButton(jobId)]],
});

export function parseCallback(data) {
  const parts = String(data ?? "").split(":");
  if (parts[0] === "noop") return { kind: "noop" };
  if (parts[0] === "apps") return { kind: "apps" };
  if (parts[0] === "st" && parts[1] in STATUS && UUID.test(parts[2] ?? "")) {
    return { kind: "st", status: parts[1], jobId: parts[2] };
  }
  if (["pkg", "save", "rej", "undo", "app", "cv", "ltr"].includes(parts[0]) && UUID.test(parts[1] ?? "")) {
    return { kind: parts[0], jobId: parts[1] };
  }
  if (parts[0] === "why" && (parts[1] === "skip" || parts[1] in REASONS) && UUID.test(parts[2] ?? "")) {
    return { kind: "why", tag: parts[1], jobId: parts[2] };
  }
  return { kind: "invalid" };
}

export function makeDb(env, fetchFn) {
  const base = `${env.SUPABASE_URL}/rest/v1`;
  const headers = {
    apikey: env.SUPABASE_SERVICE_KEY,
    Authorization: `Bearer ${env.SUPABASE_SERVICE_KEY}`,
    "Content-Type": "application/json",
  };
  const call = async (path, init) => {
    const res = await fetchFn(`${base}/${path}`, { ...init, headers: { ...headers, ...init.headers } });
    if (!res.ok) throw new Error(`supabase ${path} -> ${res.status}`);
    return res;
  };
  return {
    async hasDecision(jobId, action) {
      const res = await call(`decisions?job_id=eq.${jobId}&action=eq.${action}&select=id&limit=1`, {
        method: "GET",
      });
      return (await res.json()).length > 0;
    },
    async lastDecisionAt(jobId, action) {
      const res = await call(
        `decisions?job_id=eq.${jobId}&action=eq.${action}&select=at&order=at.desc&limit=1`,
        { method: "GET" },
      );
      const rows = await res.json();
      return rows.length ? new Date(rows[0].at) : null;
    },
    async addDecision(jobId, action) {
      await call("decisions", {
        method: "POST",
        headers: { Prefer: "return=minimal" },
        body: JSON.stringify({ job_id: jobId, action }),
      });
    },
    async setReason(jobId, tag) {
      await call(`decisions?job_id=eq.${jobId}&action=eq.reject&reason_tag=is.null`, {
        method: "PATCH",
        headers: { Prefer: "return=minimal" },
        body: JSON.stringify({ reason_tag: tag }),
      });
    },
    async removeDecisions(jobId) {
      await call(`decisions?job_id=eq.${jobId}&action=in.(save,reject)`, {
        method: "DELETE",
        headers: { Prefer: "return=minimal" },
      });
      await call(`applications?job_id=eq.${jobId}&status=eq.gemerkt`, {
        method: "DELETE",
        headers: { Prefer: "return=minimal" },
      });
    },
    async listApplications() {
      const res = await call(
        "applications?select=job_id,status,applied_at,updated_at,cv_pdf_path,letter_pdf_path," +
          "jobs(company_name,title,url,closed_at)&order=updated_at.desc&limit=100",
        { method: "GET" },
      );
      return (await res.json()).filter((a) => a.jobs);
    },
    async getApplication(jobId) {
      const res = await call(
        `applications?job_id=eq.${jobId}&select=*,jobs(company_name,title,url,closed_at)&limit=1`,
        { method: "GET" },
      );
      const rows = (await res.json()).filter((a) => a.jobs);
      return rows[0] ?? null;
    },
    async setStatus(jobId, status) {
      const now = new Date().toISOString();
      const body = { status, updated_at: now };
      if (status === "gemerkt" || status === "paket") body.applied_at = null;
      await call(`applications?job_id=eq.${jobId}`, {
        method: "PATCH",
        headers: { Prefer: "return=minimal" },
        body: JSON.stringify(body),
      });
      if (status === "beworben") {
        await call(`applications?job_id=eq.${jobId}&applied_at=is.null`, {
          method: "PATCH",
          headers: { Prefer: "return=minimal" },
          body: JSON.stringify({ applied_at: now }),
        });
      }
    },
    async downloadAsset(path) {
      const res = await fetchFn(`${env.SUPABASE_URL}/storage/v1/object/cv-assets/${encodeURI(path)}`, {
        headers: { apikey: env.SUPABASE_SERVICE_KEY, Authorization: `Bearer ${env.SUPABASE_SERVICE_KEY}` },
      });
      if (!res.ok) throw new Error(`storage ${path} -> ${res.status}`);
      return new Uint8Array(await res.arrayBuffer());
    },
    async markSaved(jobId) {
      await call("applications?on_conflict=job_id", {
        method: "POST",
        headers: { Prefer: "resolution=ignore-duplicates,return=minimal" },
        body: JSON.stringify({ job_id: jobId, status: "gemerkt" }),
      });
    },
  };
}

// Starts the "Package" workflow for one job. The token needs "Actions: write" on this repo only.
export function makeGithub(env, fetchFn) {
  const repo = env.GITHUB_REPOSITORY || "Chatchai-lab/job-scout-agent";
  return {
    configured: Boolean(env.GITHUB_DISPATCH_TOKEN),
    async dispatchPackage(jobId) {
      const res = await fetchFn(
        `https://api.github.com/repos/${repo}/actions/workflows/package.yml/dispatches`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`,
            Accept: "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ ref: "main", inputs: { job_id: jobId } }),
        },
      );
      if (res.status !== 204) throw new Error(`github dispatch -> ${res.status}`);
    },
  };
}

export const PACKAGE_COOLDOWN_MS = 5 * 60 * 1000;

export function makeTelegram(env, fetchFn) {
  const call = (method, payload) =>
    fetchFn(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  return {
    answer: (id, text, alert = false) =>
      call("answerCallbackQuery", { callback_query_id: id, text, show_alert: alert }),
    send: (chatId, text, markup) =>
      call("sendMessage", {
        chat_id: chatId,
        text,
        parse_mode: "HTML",
        disable_web_page_preview: true,
        ...(markup ? { reply_markup: markup } : {}),
      }),
    edit: (chatId, messageId, text, markup) =>
      call("editMessageText", {
        chat_id: chatId,
        message_id: messageId,
        text,
        parse_mode: "HTML",
        disable_web_page_preview: true,
        reply_markup: markup,
      }),
    sendDocument: (chatId, bytes, filename, caption) => {
      const form = new FormData();
      form.append("chat_id", String(chatId));
      if (caption) form.append("caption", caption);
      form.append("document", new Blob([bytes], { type: "application/pdf" }), filename);
      return fetchFn(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendDocument`, {
        method: "POST",
        body: form,
      });
    },
    setCommands: () =>
      call("setMyCommands", {
        commands: [{ command: "bewerbungen", description: "Meine Bewerbungen" }],
      }),
    setKeyboard: (chatId, messageId, markup) =>
      call("editMessageReplyMarkup", { chat_id: chatId, message_id: messageId, reply_markup: markup }),
  };
}

async function handleMessage(message, { db, tg, chatId }) {
  if (String(message.chat?.id) !== String(chatId)) return "wrong_chat";
  const command = String(message.text ?? "").trim().split(/[\s@]/)[0].toLowerCase();
  if (command === "/start") {
    await tg.setCommands();
    await tg.send(
      chatId,
      "✅ Job Scout ist bereit.\nÖffne das Menü ☰ neben dem Eingabefeld und wähle „Meine Bewerbungen“.",
    );
    return "start";
  }
  if (command === "/bewerbungen") {
    const view = listView(await db.listApplications());
    await tg.send(chatId, view.text, view.markup);
    return "list";
  }
  return "ignored";
}

export async function handleUpdate(update, { db, tg, gh, chatId, now = () => new Date() }) {
  if (update?.message) return handleMessage(update.message, { db, tg, chatId });
  const cq = update?.callback_query;
  if (!cq) return "ignored";
  if (String(cq.message?.chat?.id) !== String(chatId)) return "wrong_chat";

  const cmd = parseCallback(cq.data);
  const msg = cq.message;

  switch (cmd.kind) {
    case "noop":
      await tg.answer(cq.id, "");
      return "noop";
    case "save":
      if (!(await db.hasDecision(cmd.jobId, "save"))) await db.addDecision(cmd.jobId, "save");
      await db.markSaved(cmd.jobId);
      await tg.answer(cq.id, "Gemerkt 👀");
      await tg.setKeyboard(msg.chat.id, msg.message_id, done("👀 Gemerkt", cmd.jobId));
      return "saved";
    case "rej":
      if (!(await db.hasDecision(cmd.jobId, "reject"))) await db.addDecision(cmd.jobId, "reject");
      await tg.answer(cq.id, "Verworfen. Grund?");
      await tg.setKeyboard(msg.chat.id, msg.message_id, reasonKeyboard(cmd.jobId));
      return "rejected";
    case "why":
      if (cmd.tag !== "skip") await db.setReason(cmd.jobId, cmd.tag);
      await tg.answer(cq.id, "Danke");
      await tg.setKeyboard(msg.chat.id, msg.message_id, done("❌ Verworfen", cmd.jobId));
      return "reason";
    case "undo":
      await db.removeDecisions(cmd.jobId);
      await tg.answer(cq.id, "Rückgängig gemacht");
      await tg.setKeyboard(msg.chat.id, msg.message_id, jobKeyboard(cmd.jobId));
      return "undone";
    case "apps": {
      const view = listView(await db.listApplications());
      await tg.edit(msg.chat.id, msg.message_id, view.text, view.markup);
      await tg.answer(cq.id, "");
      return "list";
    }
    case "app":
    case "st": {
      if (cmd.kind === "st") await db.setStatus(cmd.jobId, cmd.status);
      const app = await db.getApplication(cmd.jobId);
      if (!app) {
        await tg.answer(cq.id, "Diese Bewerbung gibt es nicht mehr.", true);
        return "app_missing";
      }
      const view = cardView(app);
      await tg.edit(msg.chat.id, msg.message_id, view.text, view.markup);
      await tg.answer(cq.id, cmd.kind === "st" ? `${STATUS[cmd.status].icon} ${STATUS[cmd.status].label}` : "");
      return cmd.kind === "st" ? "status_set" : "card";
    }
    case "cv":
    case "ltr": {
      const app = await db.getApplication(cmd.jobId);
      const path = app && (cmd.kind === "cv" ? app.cv_pdf_path : letterPath(app));
      if (!path) {
        await tg.answer(cq.id, "Dazu gibt es noch kein Paket. Tippe in der Stelle auf 📦.", true);
        return "file_missing";
      }
      const bytes = await db.downloadAsset(path);
      await tg.sendDocument(msg.chat.id, bytes, sendName(path, cmd.kind), `${app.jobs.company_name} – ${app.jobs.title.trim()}`.slice(0, 200));
      await tg.answer(cq.id, "📄 Wird gesendet");
      return "file_sent";
    }
    case "pkg": {
      if (!gh?.configured) {
        await tg.answer(cq.id, "📦 Die Paket-Funktion ist noch nicht eingerichtet.", true);
        return "package_unconfigured";
      }
      const last = await db.lastDecisionAt(cmd.jobId, "package");
      if (last && now() - last < PACKAGE_COOLDOWN_MS) {
        await tg.answer(cq.id, "📦 Das Paket wird schon gebaut. Es kommt gleich.", true);
        return "package_running";
      }
      try {
        await gh.dispatchPackage(cmd.jobId);
      } catch (err) {
        console.error("package dispatch failed:", err.message);
        await tg.answer(cq.id, "📦 Das Paket konnte nicht gestartet werden.", true);
        return "package_failed";
      }
      await db.addDecision(cmd.jobId, "package");
      await tg.answer(cq.id, "📦 Paket wird gebaut. Es kommt in 2 bis 3 Minuten.");
      return "package_started";
    }
    default:
      await tg.answer(cq.id, "Unbekannte Aktion");
      return "invalid";
  }
}
