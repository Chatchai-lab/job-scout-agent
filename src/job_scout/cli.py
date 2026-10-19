"""Command-line entry point used locally and by GitHub Actions."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="job-scout")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("triage", help="Fetch, filter, score and send the daily digest")
    sub.add_parser("discover", help="Find new companies and their job boards")
    seed = sub.add_parser("seed-companies", help="Load a companies YAML into Supabase")
    seed.add_argument("path")
    pkg = sub.add_parser("package", help="Build the application package for one job")
    pkg.add_argument("job_id")

    args = parser.parse_args()
    raise SystemExit(f"'{args.command}' is not implemented yet")


if __name__ == "__main__":
    main()
