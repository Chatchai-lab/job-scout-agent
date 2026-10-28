import { authorized, buildDashboard, makeDashboardDb } from "../lib/dashboard.js";

const REQUIRED = ["SUPABASE_URL", "SUPABASE_SERVICE_KEY", "DASHBOARD_PASSWORD"];

export default async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  if (req.method !== "GET") return res.status(405).end();
  const missing = REQUIRED.filter((k) => !process.env[k]);
  if (missing.length) {
    console.error("missing env:", missing.join(", "));
    return res.status(500).json({ error: "not configured" });
  }
  if (!authorized(req.headers["x-dashboard-password"], process.env.DASHBOARD_PASSWORD)) {
    await new Promise((resolve) => setTimeout(resolve, 500)); // slows down guessing
    return res.status(401).json({ error: "unauthorized" });
  }
  try {
    const data = await makeDashboardDb(process.env, fetch).load();
    return res.status(200).json(buildDashboard(data));
  } catch (err) {
    console.error("dashboard failed:", err.message);
    return res.status(502).json({ error: "data unavailable" });
  }
}
