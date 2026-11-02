import { guard, makeAppDb, setCredit } from "../lib/dashboard.js";

export default async function handler(req, res) {
  if (!(await guard(req, res, "POST"))) return;
  try {
    const { code, body } = await setCredit({
      db: makeAppDb(process.env, fetch),
      amount: req.body?.amount,
      currency: req.body?.currency,
    });
    return res.status(code).json(body);
  } catch (err) {
    console.error("credit failed:", err.message);
    return res.status(502).json({ error: "Das Guthaben konnte nicht gespeichert werden." });
  }
}
