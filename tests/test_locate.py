from jobad.pipeline.locate import filter_by_location, location_ok
from jobad.schemas import Job


def j(location, remote=False):
    return Job(id=location, source="t", title="Engineer", company="c", url="u", description="d", location=location, remote=remote)


def test_city_and_country_match():
    assert location_ok(j("Tampere, Finland"), "Tampere")
    assert location_ok(j("Helsinki, Finland"), "Tampere")  # same country counts
    assert not location_ok(j("Berlin"), "Tampere")


def test_remote_rules():
    assert location_ok(j("Remote (Europe)", remote=True), "Tampere")
    assert location_ok(j("Remote", remote=True), "Tampere")
    assert location_ok(j("", remote=True), "Tampere")
    assert not location_ok(j("Remote (USA)", remote=True), "Tampere")
    assert not location_ok(j("Remote (Germany, Ireland, Spain)", remote=True), "Tampere")
    assert location_ok(j("Remote (Germany, Finland, Spain)", remote=True), "Tampere")


def test_no_filter_when_location_unset():
    jobs = [j("Berlin"), j("Remote (USA)", remote=True)]
    assert filter_by_location(jobs, None) == jobs
    assert filter_by_location(jobs, "Tampere") == []


def test_several_places():
    assert location_ok(j("Helsinki, Finland"), "Tampere, Helsinki")
    assert location_ok(j("Tampere"), "Tampere,Helsinki")
    assert not location_ok(j("Berlin"), "Tampere, Helsinki")


def test_search_places_become_acceptable_locations():
    from jobad.pipeline.locate import with_search_places
    from jobad.schemas import CandidateProfile, Seniority

    p = CandidateProfile(name="A", headline="h", years_experience=1, seniority=Seniority.mid, skills=[], domains=[], locations_ok=["Berlin", "Tampere"], remote_ok=True, must_haves=[], dealbreakers=[], summary="s")
    assert with_search_places(p, "Tampere, Helsinki").locations_ok == ["Tampere", "Helsinki", "Berlin"]
