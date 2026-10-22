"""Load the master profile.

Scoring uses the master profile stored in Supabase (`profile_private`) without contact data,
so there is a single source of truth. PROFILE_YAML (secret) or the gitignored
profile/profile.yaml are fallbacks. The profile never lives in the repo.
"""

from pathlib import Path

import yaml

from job_scout.config import Settings

DEFAULT_PATH = Path("profile/profile.yaml")
# Only these person fields go to the scoring model; contact and personal data stay private.
_SCORING_PERSON_KEYS = ("name", "headline", "github")


def scoring_profile_from_private(private_yaml: str) -> str:
    """The full master profile minus contact data, as used for scoring."""
    profile = yaml.safe_load(private_yaml)
    person = profile.get("person") or {}
    profile["person"] = {k: person[k] for k in _SCORING_PERSON_KEYS if k in person}
    return yaml.safe_dump(profile, allow_unicode=True, sort_keys=False)


def load_profile_text(settings: Settings, path: Path = DEFAULT_PATH) -> str:
    if settings.profile_yaml.strip():
        text = settings.profile_yaml
    elif path.exists():
        text = path.read_text()
    else:
        raise RuntimeError(
            "No profile found: set PROFILE_YAML (secret) or create profile/profile.yaml"
        )
    yaml.safe_load(text)  # fail early on broken YAML
    return text
