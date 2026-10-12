from jobad.schemas import Job
from jobad.sources.base import matches_query, query_terms


def test_query_terms_drop_generic_words():
    assert query_terms("backend engineer python") == ["backend", "python"]
    assert query_terms("Senior AI Engineer") == ["ai"]
    assert query_terms("engineer") == []


def test_matches_query_requires_all_terms():
    j = Job(id="1", source="t", title="Backend Engineer", company="c", url="u", description="We use Python and Kafka.")
    assert matches_query(j, "backend engineer python")
    assert matches_query(j, "kafka")
    assert not matches_query(j, "backend golang")
    assert matches_query(j, "engineer")  # no informative terms -> pass through
