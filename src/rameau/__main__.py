"""Entry point for ``python -m rameau`` and the packaged app.

    rameau-studio                      open the app
    rameau-studio harmonize tune.abc   command-line tools (same as the ``rameau`` command)
    rameau-studio --run-mma LOG ARGS   internal: run the MMA engine (used by packaged builds)
"""

import os
import sys

CLI_COMMANDS = {"harmonize", "band", "styles", "fingerprint", "train-folder"}


def _log_to_file_if_windowed() -> None:
    """Packaged windowed apps have no console: keep errors in <user data>/rameau.log instead of losing them."""
    if sys.stderr is not None and sys.stdout is not None:
        return
    import faulthandler

    from rameau.audio import user_data_dir

    log_dir = user_data_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log = open(log_dir / "rameau.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or log
    sys.stderr = sys.stderr or log
    faulthandler.enable(log)


def main() -> int:
    args = sys.argv[1:]
    if args[:1] != ["--run-mma"]:
        _log_to_file_if_windowed()
    if args[:1] == ["--run-mma"]:
        from rameau.band import run_mma_inprocess

        return run_mma_inprocess(args[1], args[2:])
    if args and args[0] in CLI_COMMANDS:
        from rameau.cli import main as cli_main

        try:
            return cli_main(args)
        except Exception:
            # Report and exit instead of letting a packaged windowed app show a blocking error dialog.
            import traceback

            traceback.print_exc()
            return 1
    if os.environ.get("RAMEAU_TRACE"):
        print("trace: starting app", file=sys.stderr, flush=True)
    from rameau.app import main as app_main

    rc = app_main()
    if os.environ.get("RAMEAU_TRACE"):
        print(f"trace: app returned {rc}", file=sys.stderr, flush=True)
    return rc


if __name__ == "__main__":
    if os.environ.get("RAMEAU_TRACE"):
        print(f"trace: __main__ argv={sys.argv}", file=sys.stderr, flush=True)
    sys.exit(main())
