import { applicationDetail, guard, isUuid, makeDetailDb } from "../lib/dashboard.js";

export default async function handler(req, res) {
  if (!(await guard(req, res, "GET"))) return;
  const id = String(req.query?.id ?? "");
  if (!isUuid(id)) return res.status(400).json({ error: "bad id" });
  try {
    const row = await makeDetailDb(process.env, fetch).getDetail(id);
    if (!row) return res.status(404).json({ error: "not found" });
    return res.status(200).json(applicationDetail(row));
  } catch (err) {
    console.error("application failed:", err.message);
    return res.status(502).json({ error: "data unavailable" });
  }
}
