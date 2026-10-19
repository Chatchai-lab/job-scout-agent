"""Normalized data model shared by all sources."""

import re
import unicodedata
from datetime import datetime

from pydantic import BaseModel, computed_field

_LEGAL_FORMS = re.compile(
    r"\b(gmbh|ag|se|kg|co|inc|ltd|llc|bv|sas|technologies|group)\b", re.IGNORECASE
)
_GENDER_TAGS = re.compile(r"\((?:[mwfdx]\s*/\s*)+[mwfdx]\)|\(all genders\)", re.IGNORECASE)


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def normalize_company(name: str) -> str:
    return _slug(_LEGAL_FORMS.sub(" ", name))


def normalize_title(title: str) -> str:
    return _slug(_GENDER_TAGS.sub(" ", title))


def normalize_city(location: str | None) -> str:
    if not location:
        return ""
    first = re.split(r"[,;/|]", location)[0]
    city = _slug(first)
    return {"munchen": "munich", "muenchen": "munich", "koln": "cologne"}.get(city, city)


class JobPosting(BaseModel):
    """One posting as returned by a source, before it touches the database."""

    source: str
    external_id: str
    company_name: str
    title: str
    url: str
    location: str | None = None
    remote: bool | None = None
    description: str | None = None
    posted_at: datetime | None = None

    @computed_field
    @property
    def dedup_key(self) -> str:
        """Same job from API, Bundesagentur and a LinkedIn mail maps to one key."""
        return "|".join(
            (
                normalize_company(self.company_name),
                normalize_title(self.title),
                normalize_city(self.location),
            )
        )
