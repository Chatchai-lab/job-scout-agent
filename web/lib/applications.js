// Views for the "Meine Bewerbungen" control center: a list and one card per application.

export const STATUS = {
  gemerkt: { icon: "👀", label: "Gemerkt" },
  paket: { icon: "📦", label: "Paket gebaut" },
  beworben: { icon: "📨", label: "Beworben" },
  interview: { icon: "🗣", label: "Interview" },
  absage: { icon: "🙁", label: "Absage" },
  angebot: { icon: "🎉", label: "Angebot" },
};
const ORDER = ["angebot", "interview", "beworben", "paket", "gemerkt", "absage"];
const MAX_ROWS = 40;

const esc = (text) =>
  String(text ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
const short = (text, max) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);

export function formatDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("de-DE", {
    timeZone: "Europe/Berlin",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

export function sortApplications(apps) {
  return [...apps].sort(
    (a, b) =>
      ORDER.indexOf(a.status) - ORDER.indexOf(b.status) ||
      String(b.updated_at).localeCompare(String(a.updated_at)),
  );
}

export function listView(apps) {
  if (!apps.length) {
    return {
      text: "📋 Noch keine Bewerbungen. Sobald du eine Stelle merkst (👀) oder ein Paket baust (📦), erscheint sie hier.",
      markup: { inline_keyboard: [] },
    };
  }
  const sorted = sortApplications(apps);
  const counts = ORDER.map((s) => [s, sorted.filter((a) => a.status === s).length])
    .filter(([, n]) => n > 0)
    .map(([s, n]) => `${STATUS[s].icon} ${n}`)
    .join(" · ");
  const rows = sorted.slice(0, MAX_ROWS).map((a) => [
    {
      text: `${STATUS[a.status].icon} ${a.jobs.company_name} – ${short(a.jobs.title.trim(), 38)}`,
      callback_data: `app:${a.job_id}`,
    },
  ]);
  return {
    text: `📋 <b>Meine Bewerbungen</b> (${apps.length})\n${counts}\n\nTippe auf eine Stelle, um den Status zu ändern.`,
    markup: { inline_keyboard: rows },
  };
}

export function letterPath(app) {
  if (app.letter_pdf_path) return app.letter_pdf_path;
  const old = /^packages\/([0-9a-f-]{36})\.pdf$/.exec(app.cv_pdf_path ?? "");
  return old ? `packages/${old[1]}-anschreiben.pdf` : null; // packages built before file names
}

export function cardView(app) {
  const job = app.jobs;
  const status = STATUS[app.status];
  const mark = (code, text) => ({
    text: app.status === code ? `• ${text}` : text,
    callback_data: `st:${code}:${app.job_id}`,
  });
  const lines = [
    `<b>${esc(job.title.trim())}</b>`,
    esc(job.company_name),
    "",
    `Status: ${status.icon} ${status.label}`,
  ];
  if (job.closed_at) {
    lines.push(`⚠️ Stelle nicht mehr ausgeschrieben seit ${formatDate(job.closed_at)}`);
  }
  if (app.applied_at) lines.push(`Beworben am: ${formatDate(app.applied_at)}`);
  lines.push(`Zuletzt geändert: ${formatDate(app.updated_at)}`);

  const reset = app.cv_pdf_path ? "paket" : "gemerkt";
  const rows = [
    [mark("beworben", "✅ Beworben"), mark("interview", "🗣 Interview")],
    [mark("absage", "🙁 Absage"), mark("angebot", "🎉 Angebot")],
    [{ text: "↩️ Zurücksetzen", callback_data: `st:${reset}:${app.job_id}` }],
  ];
  if (app.cv_pdf_path) {
    rows.push([
      { text: "📄 CV senden", callback_data: `cv:${app.job_id}` },
      { text: "✉️ Anschreiben senden", callback_data: `ltr:${app.job_id}` },
    ]);
  }
  rows.push([
    { text: "🔗 Anzeige", url: job.url },
    { text: "⬅️ Liste", callback_data: "apps" },
  ]);
  return { text: lines.join("\n"), markup: { inline_keyboard: rows } };
}

// Name the file the user will forward; older packages were stored under the job id.
export function sendName(path, kind) {
  const base = path.split("/").pop();
  if (/^[0-9a-f-]{36}(-anschreiben)?\.pdf$/.test(base)) {
    return kind === "cv" ? "Lebenslauf.pdf" : "Anschreiben.pdf";
  }
  return base;
}

export function initiativeListView(allJobs) {
  const seen = new Set(); // several open-application postings per company show up once
  const jobs = allJobs.filter((j) => !seen.has(j.company_name.trim()) && seen.add(j.company_name.trim()));
  if (!jobs.length) {
    return {
      text: "✉️ Noch keine Initiativ-Anzeigen. Schreibe mir „Initiativ Firmenname“, um selbst eine anzulegen.",
      markup: { inline_keyboard: [] },
    };
  }
  const rows = jobs.slice(0, MAX_ROWS).map((j) => [
    {
      text: `✉️ ${short(j.company_name.trim(), 30)}${j.location ? ` · ${short(j.location, 22)}` : ""}`,
      callback_data: `ini:${j.id}`,
    },
  ]);
  return {
    text:
      `✉️ <b>Initiativbewerbungen</b> (${jobs.length})\nFirmen, die Initiativbewerbungen annehmen.\n` +
      "Tippe auf eine Firma. Eigene Firma anlegen: „Initiativ Firmenname“ oder " +
      "„Initiativ Firmenname: ein Satz, was die Firma macht“.",
    markup: { inline_keyboard: rows },
  };
}

export function initiativeCard(job) {
  const lines = [`✉️ <b>Initiativbewerbung</b>`, esc(job.company_name.trim())];
  if (job.location) lines.push(`📍 ${esc(job.location)}`);
  if (job.description) lines.push("", esc(short(job.description.trim(), 400)));
  const rows = [[{ text: "📦 Paket", callback_data: `pkg:${job.id}` }]];
  const links = [];
  if (/^https?:\/\//.test(job.url ?? "")) links.push({ text: "🔗 Seite", url: job.url });
  links.push({ text: "⬅️ Liste", callback_data: "inis" });
  rows.push(links);
  return { text: lines.join("\n"), markup: { inline_keyboard: rows } };
}

// "Initiativ Firma" or "Initiativ Firma: Kontext" -> { company, context }, or null.
export function parseInitiativeRequest(text) {
  const match = /^initiativ(?:bewerbung)?\s+(.+)$/is.exec(String(text ?? "").trim());
  if (!match) return null;
  const [company, ...rest] = match[1].split(":");
  const name = company.trim().slice(0, 80);
  if (!name) return null;
  return { company: name, context: rest.join(":").trim().slice(0, 1500) };
}

const URL_RE = /https?:\/\/[^\s<>"]+/i;

// A job found by hand: a bare link, "Stelle <link>", or "Stelle Firma: Titel" plus the ad text.
// Returns { url } | { company, title, description, url } | { help: true } | null.
export function parseJobImport(text) {
  const raw = String(text ?? "").trim();
  if (/^https?:\/\/\S+$/i.test(raw)) return { url: raw.slice(0, 2000) };
  const match = /^(?:stelle|job)\s+([\s\S]+)$/i.exec(raw);
  if (!match) return null;
  const body = match[1].trim();
  if (/^https?:\/\/\S+$/i.test(body)) return { url: body.slice(0, 2000) };
  const [head, ...rest] = body.split("\n");
  const description = rest.join("\n").trim();
  const colon = head.indexOf(":");
  if (colon > 0 && description.length >= 80) {
    const company = head.slice(0, colon).trim().slice(0, 80);
    const title = head.slice(colon + 1).trim().slice(0, 200);
    if (company && title) {
      return {
        company,
        title,
        description: description.slice(0, 12000),
        url: (URL_RE.exec(description)?.[0] ?? "").slice(0, 2000),
      };
    }
  }
  return { help: true };
}

export const IMPORT_HELP =
  "So schickst du mir eine Stelle:\n" +
  "• Link: <code>Stelle https://…</code> (oder nur den Link)\n" +
  "• Text: <code>Stelle Firma: Jobtitel</code> und darunter den kopierten Anzeigentext";

// Mirrors config.py (fit_threshold, reach_threshold, monthly_budget_eur, eur_per_usd).
export const LIMITS = { fit: 5, reach: 4, budgetEur: 5, eurPerUsd: 0.92 };
export const NOT_FULL_TIME = /praktik|\bintern\b|internship|thesis|abschlussarbeit|ausbildung|studierende/i;

export function statusView(snap) {
  const apps = ORDER.map((s) => [s, snap.statuses[s] ?? 0])
    .filter(([, n]) => n > 0)
    .map(([s, n]) => `${STATUS[s].icon} ${n}`)
    .join(" · ");
  const costEur = snap.costUsd * LIMITS.eurPerUsd;
  const percent = Math.round((costEur / LIMITS.budgetEur) * 100);
  return [
    "📊 <b>Job Scout – Status</b>",
    `🏢 Firmen aktiv: ${snap.companies}`,
    `📄 Offene Stellen: ${snap.openJobs}`,
    `✅ Passende Stellen: ${snap.qualifying} (noch nicht gesehen: ${snap.unseen})`,
    `✉️ Initiativ-Firmen: ${snap.initiatives}`,
    `📋 Bewerbungen: ${apps || "keine"}`,
    `💶 Kosten im Monat: ${snap.costUsd.toFixed(2)} $ ≈ ${costEur.toFixed(2)} € von ${LIMITS.budgetEur} € (${percent} %)`,
    snap.paused
      ? "🔕 Benachrichtigungen pausiert (Digest und Sofort-Nachrichten still)"
      : "🔔 Benachrichtigungen aktiv",
  ].join("\n");
}
