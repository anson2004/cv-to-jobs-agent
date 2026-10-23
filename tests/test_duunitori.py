from pathlib import Path
from types import SimpleNamespace

from jobad.sources.duunitori import DuunitoriSource

RAW = {
    "results": [
        {"slug": "a-1", "heading": "Backend Developer", "company_name": "Pareto", "municipality_name": "Tampere", "date_posted": "2026-10-05T10:00:00", "descr": "<p>Python ja AWS. Etätyö mahdollista.</p>"},
        {"slug": "b-2", "heading": "Myyntiedustaja", "company_name": "Infin", "municipality_name": None, "date_posted": "2026-10-09", "descr": "<p>B2B-myynti.</p>"},
    ]
}


def test_parse(tmp_path: Path):
    jobs = DuunitoriSource(tmp_path, offline=True)._parse(RAW)
    assert jobs[0].id == "duunitori:a-1" and jobs[0].location == "Tampere, Finland" and jobs[0].remote
    assert jobs[1].location == "Finland, Finland" and not jobs[1].remote
    assert jobs[0].url.endswith("/tyopaikat/tyo/a-1")


def test_each_query_word_is_searched_and_merged(tmp_path: Path, monkeypatch):
    src = DuunitoriSource(tmp_path, offline=True)
    by_word = {"treasury": [RAW["results"][0]], "treasury analyst": RAW["results"]}
    asked = []
    monkeypatch.setattr(src, "_fetch", lambda term: asked.append(term) or {"results": by_word.get(term, [])})
    jobs = src.search("treasury analyst")
    assert asked == ["treasury analyst", "treasury"]  # whole query, then words specific enough to go alone
    assert [j.id for j in jobs] == ["duunitori:a-1", "duunitori:b-2"]  # merged, no duplicates


def test_new_words_are_capped_per_run(tmp_path: Path, monkeypatch):
    import jobad.sources.duunitori as d

    monkeypatch.setattr(d, "MAX_TERMS", 2)
    src = DuunitoriSource(tmp_path)
    asked = []
    monkeypatch.setattr(src, "_fetch", lambda term: asked.append(term) or {"results": []})
    src.search("treasury controller")
    assert asked == ["treasury controller", "treasury"]


def test_cache_key_includes_area(tmp_path: Path):
    a, b = DuunitoriSource(tmp_path), DuunitoriSource(tmp_path)
    b.area = "Tampere"
    assert a._key("__feed__") != b._key("__feed__")


def test_several_areas_are_searched_separately_and_merged(tmp_path: Path, monkeypatch):
    import jobad.sources.duunitori as d

    monkeypatch.setattr(d, "PAUSE_S", 0)

    class Client:
        areas = []

        def get(self, url, params):
            self.areas.append(params.get("area"))
            slug = "shared" if params["area"] == "Helsinki" else params["area"]
            return SimpleNamespace(status_code=200, json=lambda: {"results": [{"slug": slug}, {"slug": "shared"}], "next": None})

    src = DuunitoriSource(tmp_path)
    src.area = "Tampere, Helsinki"
    body = src._request(Client(), "python")
    assert Client.areas == ["Tampere", "Helsinki"]
    assert sorted(it["slug"] for it in body["results"]) == ["Tampere", "shared"]


def test_generic_role_words_are_not_searched_alone():
    from jobad.sources.duunitori import search_terms

    assert search_terms("cash manager") == ["cash manager", "cash"]
    assert search_terms("kirjanpitäjä") == ["kirjanpitäjä"]
    assert search_terms("asiantuntija") == []
