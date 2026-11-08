"""The `earshotd` command. launchd starts it at login (milestone 8); for now, run it by hand."""

from __future__ import annotations

import argparse
import logging
import sys

from earshot import paths
from earshot.daemon.server import AlreadyRunningError, Decider, hand_off, run_forever


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="earshotd", description="Earshot's background service. Stop it with Ctrl-C."
    )
    parser.add_argument(
        "--home",
        help="keep the socket, token and logs in this folder instead of the usual places",
    )
    parser.add_argument(
        "--observe",
        action="store_true",
        help="log every permission prompt (tool, mode, would voice be allowed), never answer",
    )
    parser.add_argument(
        "--voice",
        action="store_true",
        help="ask by voice through the headset (macOS; needs `uv sync --group voice`)",
    )
    parser.add_argument(
        "--pin-voice",
        action="store_true",
        help="use voice even while you're at the keyboard (for testing)",
    )
    parser.add_argument("--headset", default="AirPods", help="part of the headset's device name")
    parser.add_argument(
        "--keep-audio",
        action="store_true",
        help="save each reply's audio, and what became of it, in the home's audio folder "
        "(for tuning; off by default, as audio isn't stored)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s earshotd %(levelname)s %(message)s")
    decider: Decider = hand_off
    if args.voice:
        from earshot.voice.decider import VoiceDecider
        from earshot.voice.mac import MacVoice
        from earshot.voice.presence import KeyboardPresence

        keep = paths.resolve(args.home).audio_dir if args.keep_audio else None
        if keep is not None:
            print(f"Keeping each reply's audio in {keep}", file=sys.stderr)
        voice = MacVoice(headset=args.headset, keep_audio=keep)
        print("Loading the voice models (the first time, they download)…", file=sys.stderr)
        voice.load()  # until this finishes, there's no socket, so prompts go to the screen
        decider = VoiceDecider(voice, KeyboardPresence(pinned=args.pin_voice))
    try:
        run_forever(paths.resolve(args.home), observe=args.observe, decider=decider)
    except AlreadyRunningError as exc:
        print(f"earshotd: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
