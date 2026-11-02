import { guard, startImport } from "../lib/dashboard.js";
import { makeDb, makeGithub } from "../lib/handler.js";

// Used by the app and by the iPhone share-sheet shortcut: {"url": "https://..."}.
export default async function handler(req, res) {
  if (!(await guard(req, res, "POST"))) return;
  try {
    const { code, body } = await startImport({
      db: makeDb(process.env, fetch),
      gh: makeGithub(process.env, fetch),
      body: req.body,
    });
    return res.status(code).json(body);
  } catch (err) {
    console.error("import failed:", err.message);
    return res.status(502).json({ error: "Der Import konnte nicht gestartet werden." });
  }
}
