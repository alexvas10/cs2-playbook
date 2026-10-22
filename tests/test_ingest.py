import gzip
import zipfile

from csanalysis import ingest
from csanalysis.config import Paths


def fake_demo(path, payload: bytes):
    path.write_bytes(b"PBDEMS2\0" + payload)
    return path


def test_ingest_files_archives_and_duplicates(tmp_path):
    src = tmp_path / "downloads"
    src.mkdir()
    fake_demo(src / "m1.dem", b"one")
    with gzip.open(src / "m2.dem.gz", "wb") as f:
        f.write(b"PBDEMS2\0two")
    with zipfile.ZipFile(src / "series.zip", "w") as z:
        z.writestr("../../evil/m3.dem", b"PBDEMS2\0three")  # path traversal attempt
        z.writestr("nested/m1-copy.dem", b"PBDEMS2\0one")   # duplicate content of m1
        z.writestr("readme.txt", "hi")
    (src / "notes.txt").write_text("ignored")

    paths = Paths(tmp_path / "data")
    res = ingest.ingest(paths, [src])
    assert len(res.added) == 3 and len(res.duplicates) == 1 and not res.errors
    stored = sorted(p.name for p in paths.demos.iterdir())
    assert len(stored) == 3 and all(n.endswith(".dem") for n in stored)
    assert not (tmp_path / "evil").exists()

    again = ingest.ingest(paths, [src])
    assert not again.added and len(again.duplicates) == 4


def test_catalog_status_flow(tmp_path):
    paths = Paths(tmp_path / "data")
    ingest.ingest(paths, [fake_demo(tmp_path / "a.dem", b"a")])
    [row] = ingest.pending(paths)
    ingest.mark(paths, row["match_id"], "failed", "boom")
    assert ingest.pending(paths) == []
    assert len(ingest.pending(paths, include_failed=True)) == 1
    ingest.mark(paths, row["match_id"], "parsed")
    assert ingest.status_counts(paths) == {"parsed": 1}
    assert len(ingest.pending(paths, force=True)) == 1


def test_bad_archive_is_reported_not_fatal(tmp_path):
    (tmp_path / "broken.zip").write_bytes(b"not a zip")
    res = ingest.ingest(Paths(tmp_path / "data"), [tmp_path / "broken.zip"])
    assert len(res.errors) == 1
