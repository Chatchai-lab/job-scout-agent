import { PACKAGE_COOLDOWN_MS, makeDb, makeGithub } from "../lib/handler.js";
import { guard, startPackage } from "../lib/dashboard.js";

export default async function handler(req, res) {
  if (!(await guard(req, res, "POST"))) return;
  const { id, language } = req.body ?? {};
  try {
    const { code, body } = await startPackage({
      db: makeDb(process.env, fetch),
      gh: makeGithub(process.env, fetch),
      id,
      language: language ?? "de",
      cooldownMs: PACKAGE_COOLDOWN_MS,
    });
    return res.status(code).json(body);
  } catch (err) {
    console.error("package failed:", err.message);
    return res.status(502).json({ error: "Das Paket konnte nicht gestartet werden." });
  }
}
