"""Load the master profile.

In GitHub Actions it comes from the PROFILE_YAML secret; locally from the
gitignored profile/profile.yaml. It never lives in the repo.
"""

from pathlib import Path

import yaml

from job_scout.config import Settings

DEFAULT_PATH = Path("profile/profile.yaml")


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
