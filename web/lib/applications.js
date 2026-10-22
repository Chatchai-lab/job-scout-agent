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
