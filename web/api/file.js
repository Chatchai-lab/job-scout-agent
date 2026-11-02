import { FILE_COLUMNS, guard, isUuid, makeDetailDb } from "../lib/dashboard.js";

// Returns a link that works for five minutes; the PDF is opened from there.
export default async function handler(req, res) {
  if (!(await guard(req, res, "GET"))) return;
  const id = String(req.query?.id ?? "");
  const kind = String(req.query?.kind ?? "");
  if (!isUuid(id) || !(kind in FILE_COLUMNS)) return res.status(400).json({ error: "bad request" });
  try {
    const db = makeDetailDb(process.env, fetch);
    const row = await db.getDetail(id);
    const path = row?.[FILE_COLUMNS[kind]];
    if (!path) return res.status(404).json({ error: "no such file" });
    return res.status(200).json({ url: await db.signedUrl(path) });
  } catch (err) {
    console.error("file failed:", err.message);
    return res.status(502).json({ error: "data unavailable" });
  }
}
