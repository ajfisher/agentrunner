#!/usr/bin/env python3
"""Canonical top-level CLI router for the AgentRunner MVP surface.

This module intentionally stays thin: it routes operator-facing commands to the
existing script entrypoints so mechanics behavior and exit semantics remain owned
by those scripts.
"""
from __future__ import annotations

import argparse
import sys
from typing import Callable

from agentrunner.scripts import enqueue_initiative, operator_api, operator_cli

Router = Callable[[list[str]], int]


def route_brief(argv: list[str]) -> int:
    return enqueue_initiative.main(argv)


def route_operator(command: str, argv: list[str]) -> int:
    return operator_cli.main([command, *argv])


def route_api(argv: list[str]) -> int:
    return operator_api.main(argv)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentrunner",
        description="Canonical AgentRunner MVP CLI surface",
        add_help=True,
    )
    parser.add_argument(
        "command",
        choices=["brief", "status", "queue", "initiatives", "watch", "api"],
        help="Top-level MVP command to run",
    )
    parser.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="Arguments passed through unchanged to the routed command",
    )
    return parser


def normalize_passthrough_args(args: list[str]) -> list[str]:
    if args[:1] == ["--"]:
        return args[1:]
    return args


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    ns = parser.parse_args(raw_argv)
    passthrough = normalize_passthrough_args(list(ns.args))

    if ns.command == "brief":
        return route_brief(passthrough)
    if ns.command == "api":
        return route_api(passthrough)
    return route_operator(ns.command, passthrough)


if __name__ == "__main__":
    raise SystemExit(main())
