# job-scout-agent

A personal job-search agent for Forward-Deployed-Engineer-style roles in Germany. It collects postings from public job-board APIs every day, filters them with cheap rules, lets an LLM score what is left against a candidate profile, and sends the best matches to Telegram. On a button tap it prepares an application package: a tailored CV and a cover letter as PDFs, plus a gap analysis against the posting.

It never applies on its own. A human reads everything and sends the application.

## How it works

```
 Public job-board APIs        GitHub Actions (Python)             Supabase
 Greenhouse · Lever · Ashby ─► triage  ─► digest        ─────►  Postgres + private Storage
 Personio · Recruitee · SmartRecruiters · Workable · BambooHR
                              │  fetch → dedupe → prefilter        ▲
                              │  → LLM scoring → budget guard      │
                              ▼                                    │
                          Telegram bot  ◄────  Vercel webhook ─────┘
                          digest + buttons     button clicks → decisions
                              │
                              └─ package: LLM draft → fact check → LaTeX → PDFs
```

1. **Triage (daily):** Fetch postings, drop duplicates, apply a hard prefilter, and score the rest. Postings that disappear from a company board in two polls in a row are marked closed and are no longer shown. Open applications ("Initiativbewerbung", "talent pool") are not scored; they are collected for the `/initiativ` list.
2. **Scoring:** Claude Haiku rates each posting as structured JSON: `fit` (tasks and tech vs. the profile), `reach` (seniority match), a role category, and a short reasoning with the main doubt. A posting qualifies from fit 5 and reach 4. The scoring profile is the master profile from Supabase without contact data.
3. **Digest (daily):** Up to 7 jobs, ranked by fit × reach, one Telegram message each with action buttons. Strong matches are pushed immediately. A switch in the database (`app_state.notifications_paused`) silences all scheduled messages; manual workflow runs still send, for testing.
4. **Buttons:** Save, reject (with a one-tap reason) and undo. The decisions are stored for later preference learning.
5. **Applications (`/bewerbungen`):** A list of everything saved or applied to, with a card per application: set the status (saved, package built, applied, interview, rejection, offer) and send the stored CV or cover letter again. The digest adds one line with the number of open applications and the age of the oldest.
6. **Initiative applications (`/initiativ`):** Companies with an open-application posting, one entry per company. You can also add any company by writing the bot "Initiativ Company" (optionally ": one sentence about the company"). The package for these has no job posting to match; the letter may only state what is in the profile and in the given company notes.
7. **Jobs found by hand:** Send the bot a link (or "Stelle Company: Title" plus the pasted ad text). The `import-job` workflow reads the page, scores it and sends the usual card with the package button. Pages behind a login cannot be read; paste the text instead.
7. **Status (`/status`):** Companies, open and qualifying postings, applications by status, monthly cost against the budget, and whether notifications are paused.
8. **Package (on demand):** Claude Sonnet selects and rephrases CV bullets and drafts the letter and gap analysis. A fact check then compares every claim with the profile before anything is rendered.

## Design decisions

- **Minimal hard filters.** Only senior titles, non-matching locations, quota sales and clearly unrelated titles are dropped before the LLM. Everything else (travel, industry, language, contract type, salary) is judged by the model, not by rules.
- **The profile is the single source of truth.** The model may only select, reorder and reword existing bullets. A deterministic check (numbers and technology names must appear in the profile) and a second LLM check run on every generated text. Flagged parts fall back to the original wording, and a flagged letter is regenerated once.
- **Hard monthly budget.** Warning at 80 %, scoring pauses at 100 %. Package builds keep working. Token usage is logged per call.
- **Public APIs only.** No scraping of sites that forbid it.
- **No secrets, no personal data in this repo.** The real profile, company list, CV photo and generated documents live in Supabase (row level security on, no policies, service role only) or in GitHub secrets. gitleaks runs in CI.

## Tech stack

- Python 3.12: `httpx`, `pydantic`, `anthropic`, `supabase`, `jinja2`
- Supabase: Postgres with RLS, private Storage bucket
- GitHub Actions: scheduler and runner (LaTeX build for the package workflow)
- Vercel: serverless function for Telegram button callbacks (`web/`, plain Node)
- Telegram Bot API for delivery
- LaTeX (Jinja2 templates in `templates/`) for the CV and the cover letter

## Repository layout

```
src/job_scout/   pipeline code (sources, prefilter, scoring, digest, package, rendering)
templates/       CV and cover-letter LaTeX templates (no personal data)
supabase/        SQL migrations
web/             Telegram webhook (Vercel function) and its tests
tests/           pytest suite with in-memory fakes, no network
.github/         CI and the scheduled / manual workflows
profile/, config/  example files only; real files are gitignored
```

## Getting started

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                     # fill in the keys
cp profile/profile.example.yaml profile/profile.yaml
cp config/companies.example.yaml config/companies.yaml
pytest && ruff check .
(cd web && node --test test/*.test.js)
```

**Supabase.** Apply the migrations in `supabase/migrations/` in order. `profile_private` holds one row (`id = 'main'`) with the full profile YAML including contact data; the CV photo goes into the private `cv-assets` bucket. See `profile/profile.example.yaml` for the structure.

**Companies.** List the companies and their job boards in `config/companies.yaml`, then load them with `job-scout seed-companies config/companies.yaml`.

**GitHub secrets.** `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` and `TELEGRAM_WEBHOOK_SECRET`. `PROFILE_YAML` is only a fallback: scoring reads the master profile from Supabase.

**Button webhook.** Deploy `web/` to Vercel (root directory `web`) with `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` and `TELEGRAM_WEBHOOK_SECRET`, then register the function URL as the bot's webhook with the same secret token.

## Commands and workflows

| Command | What it does |
|---|---|
| `job-scout triage [--no-notify]` | Fetch, filter and score new jobs; push strong matches |
| `job-scout digest` | Send the daily digest |
| `job-scout package <job_id>` | Build and deliver the application package |
| `job-scout resend <job_id>` | Send a stored job to Telegram again |
| `job-scout discover` | Find job boards for the pending company candidates |
| `job-scout maintenance <task>` | Run one allow-listed data fix (needs DELETE rights) |

The `Telegram Webhook` workflow re-registers the bot webhook with the secrets stored in GitHub, so the token never has to be typed into a browser.

The same commands run as GitHub Actions workflows: `triage` and `digest` on a daily schedule (GitHub often starts scheduled runs hours late, so the digest has no clock guard), `package` and `resend` manually with a job id, `discover` and `maintenance` manually. `ci` runs gitleaks, ruff and both test suites.

## Status

Working: eight job-board sources, company discovery, prefilter, scoring with budget guard, closed-posting detection, digest and instant push, notification pause, button actions with undo, application package with fact check and PDF output, the application tracker with follow-up reminders after 14 days, initiative applications, and the status view in Telegram.

Planned: a feedback loop that proposes preference rules from rejections (applied only after approval), more sources for mid-sized companies (no public API found for Join; Softgarden unverified), a web dashboard.

## License

MIT
