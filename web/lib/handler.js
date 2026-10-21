// Telegram button callbacks: 👀 save, ❌ reject (+ one-tap reason), 📦 package (later).
// All state lives in Supabase; this function only writes `decisions` and edits the message.

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
  if (["pkg", "save", "rej", "undo"].includes(parts[0]) && UUID.test(parts[1] ?? "")) {
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
    async markSaved(jobId) {
      await call("applications?on_conflict=job_id", {
        method: "POST",
        headers: { Prefer: "resolution=ignore-duplicates,return=minimal" },
        body: JSON.stringify({ job_id: jobId, status: "gemerkt" }),
      });
    },
  };
}

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
    setKeyboard: (chatId, messageId, markup) =>
      call("editMessageReplyMarkup", { chat_id: chatId, message_id: messageId, reply_markup: markup }),
  };
}

export async function handleUpdate(update, { db, tg, chatId }) {
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
    case "pkg":
      await tg.answer(cq.id, "📦 Die Paket-Funktion kommt in Kürze.", true);
      return "package_pending";
    default:
      await tg.answer(cq.id, "Unbekannte Aktion");
      return "invalid";
  }
}
