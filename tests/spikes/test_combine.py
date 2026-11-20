"""combine.py works out a two-stage recogniser from two result files, with Earwarden's rules."""

import csv
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMBINE = ROOT / "spikes" / "speech" / "combine.py"
FIELDS = ["condition", "id", "text", "intent", "challenge", "transcript", "latency_ms"]
REPLIES = [  # id, said, wanted, challenge
    ("yes", "yes", "approve", ""),
    ("no", "no", "deny", ""),
    ("ch-lantern", "approve lantern", "approve", "lantern"),
    ("decoy-orchid", "approve orchid", "unclear", "orchard"),
]


def write(path: Path, heard: list[str], latency_ms: float) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for (reply_id, said, wanted, challenge), transcript in zip(REPLIES, heard, strict=True):
            writer.writerow(
                {
                    "condition": "quiet",
                    "id": reply_id,
                    "text": said,
                    "intent": wanted,
                    "challenge": challenge,
                    "transcript": transcript,
                    "latency_ms": latency_ms,
                }
            )


def test_second_listen_only_when_the_first_is_unclear(tmp_path: Path) -> None:
    # The fast recogniser drops the lone "yes" and garbles the decoy; the slow one hears both.
    write(
        tmp_path / "asr_results-fast-trim.csv",
        ["", "No.", "A proof lantern.", "Approve or kid?"],
        60,
    )
    write(
        tmp_path / "asr_results-slow-trim.csv",
        ["Yes.", "No.", "Approved lantern", "Approve ORCID"],
        1100,
    )
    result = subprocess.run(
        [sys.executable, str(COMBINE), "fast", "slow", "--dir", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    fast, _, both = out.split("\n\n")[0:3]
    assert "yes/no 1/2 (50.0%)" in fast  # the lone "yes" came back empty
    assert "approvals missed 1" in fast
    assert "yes/no 2/2 (100.0%)" in both
    assert "false approvals 0" in both
    assert "approvals missed 0" in both
    # The empty "yes" and the garbled decoy got a second listen; the rest didn't.
    assert "second listen on 2/4 replies" in both
    assert "median 610 ms" in both  # the middle two replies take 60 and 1,160 ms


def test_missing_results_say_what_to_run(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(COMBINE), "fast", "slow", "--dir", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Run asr_eval.py --trim" in result.stderr
