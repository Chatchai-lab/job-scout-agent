"""Command-line entry point used locally and by GitHub Actions."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="job-scout")
    sub = parser.add_subparsers(dest="command", required=True)
    triage = sub.add_parser("triage", help="Fetch, filter and score new jobs; push top hits")
    triage.add_argument(
        "--no-notify", action="store_true", help="Score and store only, no Telegram messages"
    )
    sub.add_parser("digest", help="Send the daily Telegram digest")
    sub.add_parser("discover", help="Find job boards for pending company candidates")
    seed = sub.add_parser("seed-companies", help="Load a companies YAML into Supabase")
    seed.add_argument("path")
    resend = sub.add_parser("resend", help="Send one stored job to Telegram again")
    resend.add_argument("job_id")
    maint = sub.add_parser("maintenance", help="Run an allow-listed data fix (needs DELETE)")
    maint.add_argument("task")
    pkg = sub.add_parser("package", help="Build the application package for one job")
    pkg.add_argument("job_id")

    args = parser.parse_args()

    if args.command == "seed-companies":
        from job_scout.seed import seed_companies

        count = seed_companies(args.path)
        print(f"Seeded {count} companies into Supabase.")
        return

    if args.command == "triage":
        from job_scout.runner import run_triage_command

        run_triage_command(notify=not args.no_notify)
        return

    if args.command == "resend":
        from job_scout.runner import run_resend_command

        run_resend_command(args.job_id)
        return

    if args.command == "package":
        from job_scout.runner import run_package_command

        run_package_command(args.job_id)
        return

    if args.command == "digest":
        from job_scout.runner import run_digest_command

        run_digest_command()
        return

    if args.command == "maintenance":
        from job_scout.runner import run_maintenance_command

        run_maintenance_command(args.task)
        return

    if args.command == "discover":
        from job_scout.runner import run_discover_command

        run_discover_command()
        return

    raise SystemExit(f"'{args.command}' is not implemented yet")


if __name__ == "__main__":
    main()
