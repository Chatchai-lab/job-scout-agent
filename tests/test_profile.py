import yaml

from job_scout.profile import scoring_profile_from_private

PRIVATE = """
person:
  name: Max Beispiel
  headline: Angehender Softwareentwickler
  address: Musterstr. 1
  phone: "+49 000"
  email: max@example.com
  github: https://github.com/example
  birthdate: 01.01.2000
  photo: foto.jpg
target:
  roles: [Forward Deployed Engineer]
skills:
  languages: [Python]
"""


def test_scoring_profile_drops_contact_and_personal_data():
    text = scoring_profile_from_private(PRIVATE)
    profile = yaml.safe_load(text)
    assert profile["person"] == {
        "name": "Max Beispiel",
        "headline": "Angehender Softwareentwickler",
        "github": "https://github.com/example",
    }
    assert profile["target"]["roles"] == ["Forward Deployed Engineer"]
    for secret in ("Musterstr", "max@example.com", "+49 000", "01.01.2000", "foto.jpg"):
        assert secret not in text
