import runpy


def test_packaged_backend_binds_only_to_loopback(monkeypatch) -> None:
    calls = []
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "8000")
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: calls.append((args, kwargs)))

    runpy.run_path("backend/desktop_server.py", run_name="__main__")

    assert calls[0][1]["host"] == "127.0.0.1"
    assert calls[0][1]["port"] == 8000
