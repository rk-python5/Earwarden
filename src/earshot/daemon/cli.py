"""The `earshotd` command. launchd starts it at login (milestone 8); for now, run it by hand."""

from __future__ import annotations

import argparse
import logging
import sys

from earshot import paths
from earshot.daemon.server import AlreadyRunningError, run_forever


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="earshotd", description="Earshot's background service. Stop it with Ctrl-C."
    )
    parser.add_argument(
        "--home",
        help="keep the socket, token and logs in this folder instead of the usual places",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s earshotd %(levelname)s %(message)s")
    try:
        run_forever(paths.resolve(args.home))
    except AlreadyRunningError as exc:
        print(f"earshotd: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
