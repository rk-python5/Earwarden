"""The `earshotd` command. launchd starts it at login (milestone 8); for now, run it by hand."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Awaitable, Callable

from earshot import auth, paths
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
    parser.add_argument(
        "--helper",
        help="start the signed helper app (EarshotMotion.app) for the mic and head motion",
    )
    parser.add_argument(
        "--nods",
        action="store_true",
        help="let a strict double nod approve tier 1 (off by default, D-018); shakes always count",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s earshotd %(levelname)s %(message)s")
    decider: Decider = hand_off
    on_start: Callable[[], Awaitable[None]] | None = None
    on_stop: Callable[[], Awaitable[None]] | None = None
    if args.voice:
        from earshot.voice.decider import VoiceDecider
        from earshot.voice.helper import HelperLink
        from earshot.voice.mac import MacVoice
        from earshot.voice.presence import KeyboardPresence

        where = paths.resolve(args.home)
        keep = where.audio_dir if args.keep_audio else None
        if keep is not None:
            print(f"Keeping each reply's audio in {keep}", file=sys.stderr)
        link = HelperLink(where.helper_socket, auth.ensure_token(where.token))
        voice = MacVoice(
            headset=args.headset,
            keep_audio=keep,
            profile=where.voiceprint,
            models=where.models_dir,
            helper=link,
            nods=args.nods,
        )

        async def start_link() -> None:
            await link.start()
            if args.helper:
                launch_helper(args.helper, where, args.headset)

        on_start, on_stop = start_link, link.stop
        print("Loading the voice models (the first time, they download)…", file=sys.stderr)
        voice.load()  # until this finishes, there's no socket, so prompts go to the screen
        decider = VoiceDecider(voice, KeyboardPresence(pinned=args.pin_voice), where=where)
    try:
        run_forever(
            paths.resolve(args.home),
            observe=args.observe,
            decider=decider,
            on_start=on_start,
            on_stop=on_stop,
        )
    except AlreadyRunningError as exc:
        print(f"earshotd: {exc}", file=sys.stderr)
        return 1
    return 0


def launch_helper(app: str, where: paths.Paths, headset: str) -> None:
    from earshot.voice import helper

    problem = helper.launch(app, where.helper_socket, where.token, headset)
    if problem:
        logging.getLogger("earshotd").warning("couldn't open the helper: %s", problem)


if __name__ == "__main__":
    sys.exit(main())
