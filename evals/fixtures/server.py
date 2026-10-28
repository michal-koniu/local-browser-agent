#!/usr/bin/env python3
"""Evaluation fixture server: several small web apps in one process, standard library only.

    python3 evals/fixtures/server.py --port 18940 [--host 127.0.0.1]

Apps (each under its own path prefix):
    /shop/      "Leaf & Co" plant shop: sign-up, e-mail confirmation, address, catalogue, cart, card or wallet payment
    /mail/      webmail of the test mailbox (confirmation mails, newsletters, one phishing mail)
    /social/    "Chirp" micro-blog: log in, post with image and audience, delete
    /wallet/    a mock browser wallet: approval popups for connect / transactions
    /dapp/      "Quest Drop" dApp: ordered quest steps signed in the wallet (and a drainer variant)
    /chess/     canvas chess puzzles (mate in one, mate in two)
    /qa/        the Plant Shop with planted bugs, for exploratory testing
    /research/  a company directory and an answer submission form

Test hooks:
    GET  /__state   the whole in-memory state as JSON (including an `events` list)
    POST /__reset   back to the initial state

All state lives in memory and is deterministic: ids, tokens and timestamps come from counters and a fixed seed.
The server binds to 127.0.0.1 by default; it is a test fixture, never expose it.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from apps import core  # noqa: E402
from apps import chess, dapp, mail, qa, research, shop, social  # noqa: E402,F401  (modules register their routes)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18940)
    ap.add_argument("--quiet", action="store_true", help="do not log requests")
    args = ap.parse_args()
    core.reset()
    core.serve(args.host, args.port, quiet=args.quiet)


if __name__ == "__main__":
    main()
