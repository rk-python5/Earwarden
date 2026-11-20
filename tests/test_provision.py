"""`earwarden setup`: the helper source ships, models download with their checksums checked."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from earwarden import cli, paths, provision


def serve(folder: Path, files: dict[str, bytes]) -> dict[str, str]:
    """Write files into a folder, standing in for the release, and return their SHA-256s."""
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (folder / name).write_bytes(data)
    return {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}


def test_the_helpers_source_ships_in_the_package() -> None:
    source = provision.helper_source()
    for name in ("build.sh", "Package.swift", "Sources/EarwardenMotion/main.swift"):
        assert (source / name).exists(), name


def test_models_download_once_and_are_checked(tmp_path: Path) -> None:
    where = paths.resolve(str(tmp_path / "home"))
    hashes = serve(tmp_path / "release", {"a.onnx": b"graph", "a.onnx.data": b"weights"})
    said: list[str] = []
    base = (tmp_path / "release").as_uri()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(provision, "MODEL_FILES", hashes)
        assert not provision.models_ready(where)
        assert provision.fetch_models(where, said.append, base)
        assert provision.models_ready(where)
        assert (where.models_dir / "a.onnx.data").read_bytes() == b"weights"
        said.clear()
        assert provision.fetch_models(where, said.append, base)  # nothing left to fetch
        assert said == []


def test_a_model_that_fails_its_checksum_is_discarded(tmp_path: Path) -> None:
    where = paths.resolve(str(tmp_path / "home"))
    hashes = serve(tmp_path / "release", {"a.onnx": b"graph"})
    (tmp_path / "release" / "a.onnx").write_bytes(b"tampered")
    said: list[str] = []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(provision, "MODEL_FILES", hashes)
        assert not provision.fetch_models(where, said.append, (tmp_path / "release").as_uri())
    assert not (where.models_dir / "a.onnx").exists()
    assert not list(where.models_dir.glob("*.part"))
    assert "checksum" in said[-1]


def test_a_missing_model_is_reported_not_raised(tmp_path: Path) -> None:
    where = paths.resolve(str(tmp_path / "home"))
    said: list[str] = []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(provision, "MODEL_FILES", {"a.onnx": "0" * 64})
        assert not provision.fetch_models(where, said.append, (tmp_path / "nowhere").as_uri())
    assert "Couldn't download" in said[-1]


def test_the_default_helper_is_the_built_app_if_there_is_one(tmp_path: Path) -> None:
    where = paths.resolve(str(tmp_path))
    assert provision.default_helper(where) is None
    binary = provision.helper_app(where) / "Contents" / "MacOS" / "earwarden-motion"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"")
    assert provision.default_helper(where) == provision.helper_app(where)


def test_setup_without_voice_adds_only_the_hooks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text("{}")
    home = tmp_path / "home"
    code = cli.main(["setup", "--no-voice", "--home", str(home), "--settings", str(settings)])
    assert code == 0
    assert "earwarden-hook" in settings.read_text()
    assert "Voice skipped" in capsys.readouterr().out
    assert not (home / "helper").exists()
