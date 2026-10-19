# job-scout-agent

A personal job-search agent that finds Forward-Deployed-Engineer-style roles in Germany, scores them against a candidate profile with an LLM, and delivers a short daily digest to Telegram. On request it builds a tailored application package: a CV compiled from LaTeX and a cover-letter draft, with a fact check against the candidate's master profile.

> Status: work in progress (Phase 1: triage MVP)

## How it works

```
Board APIs ─┐                     ┌─ Discovery  (weekly)
Aggregators ├─► GitHub Actions ───┼─ Triage     (daily: prefilter → dedup → LLM score → digest)
Alert mails ┘     (Python)        └─ Package    (on click: draft → fact check → LaTeX build)
                       │
                   Supabase  ◄──►  Vercel (dashboard, Telegram webhook)  ◄──►  Telegram
```

- **Sources:** public job-board APIs (Greenhouse, Lever, Ashby), aggregators, job-alert e-mails. No scraping of sites that forbid it.
- **Matching:** free rule-based prefilter, then Claude Haiku scores *fit* and *reach* (seniority) separately as structured JSON.
- **Cost control:** prompt caching, Batch API, and a hard monthly budget enforced in code.
- **Feedback loop:** rejections with a one-tap reason become proposed preference rules that only apply after approval.
- **Privacy:** the repo holds code and fake example data only. Profile, CV, company list and applications live in Supabase and GitHub Secrets; gitleaks runs in CI.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env              # fill in keys
cp profile/profile.example.yaml profile/profile.yaml
cp config/companies.example.yaml config/companies.yaml
pytest
```

Apply `supabase/migrations/0001_init.sql` to a Supabase project.

## License

MIT
