import { STATUS } from "../lib/applications.js";
import { guard, isUuid } from "../lib/dashboard.js";
import { makeDb } from "../lib/handler.js";

export default async function handler(req, res) {
  if (!(await guard(req, res, "POST"))) return;
  const { id, status } = req.body ?? {};
  if (!isUuid(id) || !(status in STATUS)) return res.status(400).json({ error: "bad request" });
  try {
    const db = makeDb(process.env, fetch);
    if (!(await db.getApplication(id))) return res.status(404).json({ error: "not found" });
    await db.setStatus(id, status);
    return res.status(200).json({ ok: true, status });
  } catch (err) {
    console.error("status failed:", err.message);
    return res.status(502).json({ error: "data unavailable" });
  }
}
