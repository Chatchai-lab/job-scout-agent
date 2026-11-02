import { buildDashboard, guard, makeDashboardDb } from "../lib/dashboard.js";

export default async function handler(req, res) {
  if (!(await guard(req, res, "GET"))) return;
  try {
    const data = await makeDashboardDb(process.env, fetch).load();
    return res.status(200).json(buildDashboard(data));
  } catch (err) {
    console.error("dashboard failed:", err.message);
    return res.status(502).json({ error: "data unavailable" });
  }
}
