import { handleUpdate, makeDb, makeGithub, makeTelegram } from "../lib/handler.js";

const REQUIRED = [
  "SUPABASE_URL",
  "SUPABASE_SERVICE_KEY",
  "TELEGRAM_BOT_TOKEN",
  "TELEGRAM_CHAT_ID",
  "TELEGRAM_WEBHOOK_SECRET",
];

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).end();
  const missing = REQUIRED.filter((k) => !process.env[k]);
  if (missing.length) {
    console.error("missing env:", missing.join(", "));
    return res.status(500).end();
  }
  if (req.headers["x-telegram-bot-api-secret-token"] !== process.env.TELEGRAM_WEBHOOK_SECRET) {
    return res.status(401).end();
  }
  try {
    const outcome = await handleUpdate(req.body, {
      db: makeDb(process.env, fetch),
      tg: makeTelegram(process.env, fetch),
      gh: makeGithub(process.env, fetch),
      chatId: process.env.TELEGRAM_CHAT_ID,
    });
    console.log("callback:", outcome);
  } catch (err) {
    // Telegram retries non-2xx responses; a failed write should not trigger a retry storm.
    console.error("callback failed:", err.message);
  }
  return res.status(200).json({ ok: true });
}
