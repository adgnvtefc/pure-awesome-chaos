"""pure-awesome-chaos: a local model builds one weird little app every night."""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="chaos", description="Nightly autonomous app builder.")
    sub = parser.add_subparsers(dest="command", required=True)
    night = sub.add_parser("night", help="run one night now")
    night.add_argument("--hours", type=float, help="how long the night lasts (default: CHAOS_HOURS or 5.5)")
    sub.add_parser("dice", help="roll tonight's ingredients (just for fun)")
    sub.add_parser("selftest", help="check the model server and prove the sandbox holds")
    sub.add_parser("gallery", help="rebuild gallery/index.html")
    sub.add_parser("status", help="what's happening tonight / what happened last night")
    dash = sub.add_parser("dashboard", help="open the local control room in your browser")
    dash.add_argument("--port", type=int, default=8642)
    dash.add_argument("--no-open", action="store_true", help="don't open a browser tab")
    sched = sub.add_parser("schedule", help="turn the nightly run on/off (launchd)")
    sched.add_argument("switch", choices=["on", "off", "status"])
    wake = sub.add_parser("wake", help="turn the nightly wake-up on/off (pmset; asks for your password)")
    wake.add_argument("switch", choices=["on", "off", "status"])
    args = parser.parse_args()

    from chaos import config  # after argparse, so --help works without a .env

    if args.command == "night":
        from chaos.night import run_night

        night_dir = run_night(args.hours or config.HOURS)
        status = json.loads((night_dir / "night.json").read_text()).get("status")
        sys.exit(0 if status == "done" else 1)

    if args.command == "dice":
        from chaos import dice

        for k, v in dice.roll().items():
            if k != "seed":
                print(f"{k:>6}: {v}")

    if args.command == "selftest":
        from chaos import llm, sandbox

        try:
            models = llm.server_models()
            mark = "ok " if config.MODEL in models else "!! "
            print(f"[{mark}] model server: {config.BASE_URL} serves {models} (using {config.MODEL})")
        except Exception as e:  # noqa: BLE001
            print(f"[!! ] model server unreachable: {e}")
        with tempfile.TemporaryDirectory(dir=config.ROOT) as tmp:
            for desc, ok in sandbox.selftest(Path(tmp)):
                print(f"[{'ok ' if ok else 'FAIL'}] sandbox: {desc}")

    if args.command == "gallery":
        from chaos import gallery

        print(gallery.build())

    if args.command == "dashboard":
        from chaos import dashboard

        dashboard.serve(args.port, open_browser=not args.no_open)

    if args.command in ("schedule", "wake"):
        from chaos import schedule

        try:
            if args.command == "schedule" and args.switch != "status":
                schedule.install() if args.switch == "on" else schedule.uninstall()
            if args.command == "wake" and args.switch != "status":
                schedule.set_wake(args.switch == "on")
        except schedule.ScheduleError as e:
            sys.exit(f"Error: {e}")
        on = schedule.is_installed()
        print(f"nightly run: {'on' if on else 'off'}" + (f" (next: {schedule.next_run():%a %H:%M})" if on else ""))
        w = schedule.wake_status()
        print(f"wake-up:     {'on' if w['on'] else 'off'}" + (f" ({w['description']})" if w["on"] else ""))

    if args.command == "status":
        nights = sorted(config.NIGHTS.glob("*/night.json"))
        if not nights:
            print("No nights yet.")
            return
        latest = nights[-1].parent
        s = json.loads(nights[-1].read_text())
        tests = (s.get("tests") or {}).get("summary", "-")
        print(f"{latest.name}: {s.get('status')} | {s.get('name', '?')} | plan {s.get('plan_done', 0)}/{s.get('plan_total', 0)} | tests: {tests}")
        sys.stdout.flush()  # before tail writes to the same stdout
        log = latest / "night.log"
        if log.exists():
            subprocess.run(["tail", "-n", "15", str(log)])
