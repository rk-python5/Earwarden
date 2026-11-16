"""`earshot setup`: everything a new user's Mac needs, from an installed package (Phase 5).

The wheel carries the helper's Swift source (`helper_app/`), so no repository checkout is
needed. Setup does, in order, and says what it did and what failed:

1. adds the hooks to Claude Code's settings (the same as `earshot init`);
2. builds the signed helper app from that source with `swift build` (Xcode's command line tools),
   signed ad hoc, into Earshot's own folder, so macOS asks for the mic and motion in Earshot's
   name once;
3. installs spaCy's English model, which the text front-end needs and which PyPI can't list as a
   dependency (D-022);
4. downloads the voiceprint's ONNX model, checking its SHA-256 (D-038).

Nothing here runs at request time: a missing piece means voice stays off and every prompt goes
to the screen, as the fail-toward-the-screen rule says.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path

from earshot import paths

SPACY_MODEL = "en_core_web_sm"
SPACY_MODEL_URL = (
    "https://github.com/explosion/spacy-models/releases/download/"
    "en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
)
MODEL_URL_ENV = "EARSHOT_MODEL_URL"  # a folder of the model files, for mirrors and tests
MODEL_URL = "https://github.com/rk-python5/Earshot/releases/download/model-ecapa-1"
# The voiceprint network (SpeechBrain's ECAPA-TDNN, exported by dev/export_ecapa.py): its
# graph and its weights, with the hashes `setup` checks.
MODEL_FILES: dict[str, str] = {
    "ecapa_embedding.onnx": "3a0153691f869d1be63bf76a11b5d646214a1892761143d61674304e442eb616",
    "ecapa_embedding.onnx.data": "d88fdd8d56b3328a3ae3b32f13bcbf08bc5981ee1cabbf249aefd8b6411fdb5c",
}
CHUNK = 1 << 20

Say = Callable[[str], None]


def helper_source() -> Path:
    """The Swift source that ships inside the package."""
    return Path(__file__).resolve().parent / "helper_app"


def helper_dir(where: paths.Paths) -> Path:
    return where.state_dir / "helper"


def helper_app(where: paths.Paths) -> Path:
    """Where `earshot setup` puts the built helper app."""
    return helper_dir(where) / ".build" / "EarshotMotion.app"


def default_helper(where: paths.Paths) -> Path | None:
    """The built helper, if setup has made it."""
    app = helper_app(where)
    return app if (app / "Contents" / "MacOS" / "earshot-motion").exists() else None


def build_helper(where: paths.Paths, say: Say = print) -> Path | None:
    """Build the helper from the packaged source. None, with the reason said, if it can't be."""
    if sys.platform != "darwin":
        say("The helper is for macOS; skipping it.")
        return None
    if shutil.which("swift") is None:
        say(
            "Swift isn't installed. Run `xcode-select --install` (about 5 minutes), then "
            "`earshot setup` again. Until then Earshot works on the screen only."
        )
        return None
    source, target = helper_source(), helper_dir(where)
    if not (source / "build.sh").exists():
        say(f"The helper's source isn't in this install ({source}).")
        return None
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(".build", ".swiftpm"))
    say("Building the helper (about a minute the first time)…")
    done = subprocess.run(  # noqa: S603 - our own script, in our own folder
        ["/bin/sh", str(target / "build.sh")], capture_output=True, text=True, check=False
    )
    app = helper_app(where)
    if done.returncode != 0 or default_helper(where) is None:
        say("The helper didn't build:\n" + (done.stdout + done.stderr).strip()[-1500:])
        return None
    return app


def ensure_spacy_model(say: Say = print) -> bool:
    """Make sure spaCy's English model is installed, for the text front-end (D-022)."""
    if importlib.util.find_spec(SPACY_MODEL) is not None:
        return True
    say("Installing spaCy's English model (about 12 MB)…")
    uv = shutil.which("uv")
    if uv:
        command = [uv, "pip", "install", "--python", sys.executable, SPACY_MODEL_URL]
    else:  # a venv without uv or pip: bring pip in, which every Python ships the means for
        subprocess.run(
            [sys.executable, "-m", "ensurepip", "--upgrade"], capture_output=True, check=False
        )
        command = [sys.executable, "-m", "pip", "install", SPACY_MODEL_URL]
    done = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if done.returncode != 0:
        say("spaCy's model didn't install:\n" + (done.stdout + done.stderr).strip()[-800:])
        return False
    importlib.invalidate_caches()
    return importlib.util.find_spec(SPACY_MODEL) is not None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while block := file.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def models_ready(where: paths.Paths) -> bool:
    return all(
        (where.models_dir / name).exists() and sha256(where.models_dir / name) == want
        for name, want in MODEL_FILES.items()
    )


def fetch_models(where: paths.Paths, say: Say = print, base: str | None = None) -> bool:
    """Download the voiceprint model, keeping each file only if its SHA-256 matches."""
    base = (base or os.environ.get(MODEL_URL_ENV) or MODEL_URL).rstrip("/")
    where.models_dir.mkdir(parents=True, exist_ok=True)
    for name, want in MODEL_FILES.items():
        target = where.models_dir / name
        if target.exists() and sha256(target) == want:
            continue
        say(f"Downloading {name}…")
        part = target.with_suffix(target.suffix + ".part")
        try:
            with (
                urllib.request.urlopen(f"{base}/{name}", timeout=60) as reply,  # noqa: S310
                part.open("wb") as file,
            ):
                while block := reply.read(CHUNK):
                    file.write(block)
        except OSError as error:
            part.unlink(missing_ok=True)
            say(f"Couldn't download {name} from {base}: {error}")
            return False
        if sha256(part) != want:
            part.unlink(missing_ok=True)
            say(f"{name} didn't match its checksum, so it was discarded.")
            return False
        part.replace(target)
    return True
