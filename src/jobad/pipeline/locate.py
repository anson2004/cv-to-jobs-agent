"""Step 5c: hard location filter. No LLM.

`--location Tampere` keeps a posting if its location names the wanted place
(city or country), or it is remote and open to a region that includes it.
A remote posting restricted to a list of countries that does not include the
wanted country is dropped; "Remote (USA)" is not a job in Tampere.
"""

from __future__ import annotations

import re

from ..schemas import Job

_WORD = re.compile(r"[a-zäöå]+", re.I)

# Country names and demonyms per wanted city/country, so "Tampere" also accepts "Finland".
_COUNTRY_OF = {
    "tampere": ["finland", "suomi"], "helsinki": ["finland", "suomi"], "espoo": ["finland", "suomi"], "oulu": ["finland", "suomi"], "turku": ["finland", "suomi"],
    "berlin": ["germany", "deutschland"], "munich": ["germany", "deutschland"], "münchen": ["germany", "deutschland"], "hamburg": ["germany", "deutschland"],
    "stockholm": ["sweden", "sverige"], "oslo": ["norway", "norge"], "copenhagen": ["denmark", "danmark"], "amsterdam": ["netherlands", "nederland"],
    "london": ["uk", "united kingdom", "england"], "paris": ["france"], "zurich": ["switzerland", "schweiz"], "zürich": ["switzerland", "schweiz"],
}
_OPEN_REGIONS = {"europe", "eu", "emea", "worldwide", "anywhere", "global", "nordics", "nordic", "scandinavia", "international", "homeoffice", "remote"}
_EU_COUNTRIES = {"finland", "sweden", "norway", "denmark", "germany", "netherlands", "france", "spain", "italy", "poland", "estonia", "ireland", "austria", "belgium", "portugal", "czech", "latvia", "lithuania"}


def wanted_terms(location: str) -> set[str]:
    words = {w.lower() for w in _WORD.findall(location)}
    out = set(words)
    for w in words:
        out.update(_COUNTRY_OF.get(w, []))
    return out


def location_ok(job: Job, location: str) -> bool:
    wanted = wanted_terms(location)
    loc_words = {w.lower() for w in _WORD.findall(job.location)}
    if loc_words & wanted:
        return True
    if not job.remote:
        return False
    # Remote: a bare "Remote" or an open region passes; an explicit country list
    # passes only if it includes ours.
    loc_words -= {"remote", "job", "from", "only"}
    if not loc_words or loc_words & _OPEN_REGIONS:
        return True
    listed_countries = loc_words & (_EU_COUNTRIES | {"usa", "us", "canada", "uk", "india", "australia", "mexico", "brazil"})
    return bool(listed_countries & wanted)


def filter_by_location(jobs: list[Job], location: str | None) -> list[Job]:
    if not location:
        return jobs
    return [j for j in jobs if location_ok(j, location)]
