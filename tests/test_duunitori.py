from pathlib import Path
from types import SimpleNamespace

from jobad.sources.duunitori import DuunitoriSource

RAW = {
    "results": [
        {"slug": "a-1", "heading": "Backend Developer", "company_name": "Pareto", "municipality_name": "Tampere", "date_posted": "2026-10-05T10:00:00", "descr": "<p>Python ja AWS. Etätyö mahdollista.</p>"},
        {"slug": "b-2", "heading": "Myyntiedustaja", "company_name": "Infin", "municipality_name": None, "date_posted": "2026-10-09", "descr": "<p>B2B-myynti.</p>"},
    ]
}


def test_parse_and_any_term_filter(tmp_path: Path):
    src = DuunitoriSource(tmp_path, offline=True)
    jobs = src._parse(RAW)
    assert jobs[0].id == "duunitori:a-1" and jobs[0].location == "Tampere, Finland" and jobs[0].remote
    assert jobs[1].location == "Finland, Finland" and not jobs[1].remote
    assert jobs[0].url.endswith("/tyopaikat/tyo/a-1")
    src._feed = jobs
    assert [x.id for x in src.search("backend engineer python")] == ["duunitori:a-1"]  # any term matches
    assert len(src.search("engineer")) == 2  # no informative terms -> whole feed


def test_cache_key_includes_area(tmp_path: Path):
    a, b = DuunitoriSource(tmp_path), DuunitoriSource(tmp_path)
    b.area = "Tampere"
    assert a._key("__feed__") != b._key("__feed__")


def test_several_areas_are_swept_separately_and_merged(tmp_path: Path, monkeypatch):
    import jobad.sources.duunitori as d

    monkeypatch.setattr(d, "SWEEP_TERMS", ["python"])
    monkeypatch.setattr(d, "PAUSE_S", 0)

    class Client:
        areas = []

        def get(self, url, params):
            self.areas.append(params.get("area"))
            slug = "shared" if params["area"] == "Helsinki" else params["area"]
            return SimpleNamespace(status_code=200, json=lambda: {"results": [{"slug": slug}, {"slug": "shared"}], "next": None})

    src = DuunitoriSource(tmp_path)
    src.area = "Tampere, Helsinki"
    body = src._request(Client(), "__feed__")
    assert Client.areas == ["Tampere", "Helsinki"]
    assert sorted(it["slug"] for it in body["results"]) == ["Tampere", "shared"]
