from pipeline.jobs.ingest import bronze_path, download


def test_download_fetches_once_and_leaves_no_partial_file(tmp_path, monkeypatch):
    remote = tmp_path / "remote"
    remote.mkdir()
    (remote / "yellow_tripdata_2025-01.parquet").write_bytes(b"first")
    monkeypatch.setenv("TLC_BASE_URL", remote.as_uri())
    monkeypatch.setenv("BRONZE_DIR", str(tmp_path / "bronze"))

    path = download("yellow", "2025-01")
    assert path == bronze_path("yellow", "2025-01")
    assert path.read_bytes() == b"first"
    assert [p.name for p in path.parent.iterdir()] == [path.name]

    (remote / "yellow_tripdata_2025-01.parquet").write_bytes(b"changed")
    assert download("yellow", "2025-01").read_bytes() == b"first"
