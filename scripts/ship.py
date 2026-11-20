"""Check, build, and deploy both extension bundles to the running Superset container.

Usage: uv run scripts/ship.py [--skip-check] [--smoke]
"""

import argparse
import sys

import build
import check
import deploy
import smoke
from _common import ROOT, extensions, run, step


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="deprecated: checks run by default")
    parser.add_argument("--skip-check", action="store_true", help="skip local tests, Ruff, and frontend typechecks")
    parser.add_argument("--smoke", action="store_true", help="run scripts/smoke.py after deploying")
    args = parser.parse_args(argv)

    if not args.skip_check:
        check.main([])
        agent = extensions()[0]
        for name, command, directory in (
            ("AI Agent Ruff", [sys.executable, "-m", "ruff", "check", str(agent.directory / "backend")], ROOT),
            (
                "AI Agent pytest",
                [sys.executable, "-m", "pytest", str(agent.directory / "backend" / "tests"), "-q"], ROOT,
            ),
            ("AI Agent TypeScript typecheck", ["npm", "run", "typecheck"], agent.directory / "frontend"),
        ):
            step(name)
            run(command, cwd=directory)
    build.main([])
    deploy.main([])
    if args.smoke:
        smoke.main([])


if __name__ == "__main__":
    main()
