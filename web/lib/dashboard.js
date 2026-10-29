// Read-only dashboard: one JSON payload for the phone app, behind a shared password.

import { createHash, timingSafeEqual } from "node:crypto";

import { LIMITS, NOT_FULL_TIME, STATUS } from "./applications.js";

// Mirrors config.py (working_student_fit_threshold).
export const WORKING_STUDENT_FIT = 3;
const KINDS = ["posting", "working_student"];
const JOB_COLUMNS =
  "fit,reach,ring,reason,start_ok,notified_at," +
  "jobs!inner(id,company_name,title,location,remote,url,kind,source,closed_at,first_seen_at)";

// Compare through a hash so the length of the password never leaks and the compare is constant-time.
export function authorized(provided, expected) {
  if (!expected || !provided) return false;
  const digest = (value) => createHash("sha256").update(String(value)).digest();
  return timingSafeEqual(digest(provided), digest(expected));
}

export function qualifies(score) {
  const job = score.jobs;
  if (!job || job.closed_at) return false;
  if (job.source === "manual" && job.kind === "posting") return true; // added by hand: always shown
  if (score.ring === "raus" || score.start_ok === false) return false;
  if (score.reach < LIMITS.reach) return false;
  if (job.kind === "working_student") return score.fit >= WORKING_STUDENT_FIT;
  if (job.kind === "posting") return score.fit >= LIMITS.fit && !NOT_FULL_TIME.test(job.title);
  return false;
}

export function jobEntry(score) {
  const job = score.jobs;
  return {
    id: job.id,
    company: job.company_name,
    title: job.title,
    location: job.location ?? "",
    remote: Boolean(job.remote),
    kind: job.kind,
    manual: job.source === "manual",
    url: job.url,
    fit: score.fit,
    reach: score.reach,
    ring: score.ring,
    reason: score.reason ?? "",
    seen: Boolean(score.notified_at),
    firstSeenAt: job.first_seen_at,
  };
}

export function applicationEntry(app) {
  return {
    id: app.job_id,
    status: app.status,
    company: app.jobs.company_name,
    title: app.jobs.title,
    url: app.jobs.url ?? "",
    appliedAt: app.applied_at,
    updatedAt: app.updated_at,
    hasPackage: Boolean(app.cv_pdf_path),
    closed: Boolean(app.jobs.closed_at),
  };
}

export function buildDashboard({ scores, apps, initiatives, cost, counts, paused, now = new Date() }) {
  const jobs = scores
    .filter(qualifies)
    .map(jobEntry)
    .sort(
      (a, b) =>
        Number(b.manual) - Number(a.manual) ||
        b.fit * b.reach - a.fit * a.reach ||
        a.company.localeCompare(b.company),
    );
  const applications = apps.filter((a) => a.jobs).map(applicationEntry);
  const statuses = {};
  for (const a of applications) statuses[a.status] = (statuses[a.status] ?? 0) + 1;
  const costUsd = Number(cost ?? 0);
  const costEur = costUsd * LIMITS.eurPerUsd;
  return {
    generatedAt: now.toISOString(),
    status: {
      costUsd,
      costEur,
      budgetEur: LIMITS.budgetEur,
      percent: Math.round((costEur / LIMITS.budgetEur) * 100),
      companies: counts.companies,
      openJobs: counts.openJobs,
      qualifying: jobs.length,
      unseen: jobs.filter((j) => !j.seen).length,
      initiatives: initiatives.length,
      statuses,
      paused: Boolean(paused),
    },
    statusLabels: STATUS,
    applications,
    jobs,
    initiatives: initiatives.map((i) => ({
      id: i.id,
      company: i.company_name,
      location: i.location ?? "",
      url: i.url ?? "",
    })),
  };
}

export function makeDashboardDb(env, fetchFn) {
  const call = async (path, extra = {}) => {
    const res = await fetchFn(`${env.SUPABASE_URL}/rest/v1/${path}`, {
      method: "GET",
      ...extra,
      headers: {
        apikey: env.SUPABASE_SERVICE_KEY,
        Authorization: `Bearer ${env.SUPABASE_SERVICE_KEY}`,
        ...(extra.headers ?? {}),
      },
    });
    if (!res.ok) throw new Error(`supabase ${path.split("?")[0]} ${res.status}`);
    return res;
  };
  const rows = async (path) => (await call(path)).json();
  const count = async (path) => {
    const res = await call(`${path}&limit=1`, { headers: { Prefer: "count=exact" } });
    return Number((res.headers.get("content-range") ?? "").split("/")[1]) || 0;
  };
  return {
    async load() {
      const month = `${new Date().toISOString().slice(0, 7)}-01`;
      const [scored, manual, apps, initiatives, cost, companies, openJobs, paused] = await Promise.all([
        rows(
          `scores?select=${JOB_COLUMNS}` +
            `&reach=gte.${LIMITS.reach}&fit=gte.${WORKING_STUDENT_FIT}&ring=neq.raus` +
            `&jobs.closed_at=is.null&jobs.kind=in.(${KINDS.join(",")})&limit=1000`,
        ),
        rows(
          `scores?select=${JOB_COLUMNS}&jobs.source=eq.manual&jobs.kind=eq.posting` +
            "&jobs.closed_at=is.null&limit=200",
        ),
        rows(
          "applications?select=job_id,status,applied_at,updated_at,cv_pdf_path," +
            "jobs(company_name,title,url,closed_at)&order=updated_at.desc&limit=200",
        ),
        rows(
          "jobs?kind=eq.initiative&closed_at=is.null&select=id,company_name,location,url" +
            "&order=company_name.asc&limit=200",
        ),
        rows(`monthly_cost?select=cost_usd&month=eq.${month}`),
        count("companies?active=eq.true&select=id"),
        count("jobs?closed_at=is.null&kind=eq.posting&select=id"),
        rows("app_state?select=value&key=eq.notifications_paused"),
      ]);
      const seen = new Set(scored.map((r) => r.jobs.id));
      const scores = [...scored, ...manual.filter((r) => !seen.has(r.jobs.id))];
      return {
        scores,
        apps,
        initiatives,
        cost: cost[0]?.cost_usd ?? 0,
        counts: { companies, openJobs },
        paused: paused[0]?.value === "true",
      };
    },
  };
}
