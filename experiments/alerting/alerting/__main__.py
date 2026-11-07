"""
# Command line

Manual checks for each step of the alerting module, run from `experiments/alerting/`:

    uv run python -m alerting email examples/03_email_si_apel_ridicata.json
    uv run python -m alerting tts examples/03_email_si_apel_ridicata.json

`email` sends the alert email to everyone in `oncall.json`, through the gates in
`alerting.mailer`. The summary printed at the end masks every contact.

`tts` renders the spoken message with each local voice into `out/tts/`, plus a copy at
phone-line quality, and prints the text, its word count and each file's length.

`call-check` reads the account of the provider in `CALL_PROVIDER` (nothing is created):
for Twilio, trial or not, verified numbers, Romania in Geo Permissions; for Infobip, whether
the credentials work and which Romanian voices exist. `call` phones the first person in
`oncall.json` once, through the gates in `alerting.caller`, and waits for the outcome.

    uv run python -m alerting call-check
    uv run python -m alerting call examples/03_email_si_apel_ridicata.json

`escalate` runs the whole escalation (see `alerting.escalation`). With `--simulate` each call
ends with the next scripted outcome instead: nobody is phoned, the per-alert cap is counted
in a throwaway file and the retry delay is reported, not waited:

    uv run python -m alerting escalate examples/04_email_si_apel_critica_vineri_seara.json \
        --simulate no-answer,busy,completed:human

`dispatch` runs `alerting.dispatch.dispatch(alert, decision)`: email, then the call with
escalation when the decision asks for it, once per alert. With `--simulate` the calls are
scripted, the email goes to Mailpit only, and the state is a throwaway file:

    uv run python -m alerting dispatch examples/04_email_si_apel_critica_vineri_seara.json
    uv run python -m alerting dispatch examples/04_email_si_apel_critica_vineri_seara.json \
        --simulate no-answer,completed:human

The following can be imported from this module:
- `main`
"""

import argparse
from dataclasses import asdict
import json
import logging
from pathlib import Path
import tempfile

from alerting.caller import check_account, place_call, wait_for_call
from alerting.config import PACKAGE_ROOT, environment
from alerting.dispatch import dispatch
from alerting.escalation import escalate
from alerting.mailer import send_alert_email
from alerting.models import Case, load_case
from alerting.oncall import OnCallPerson, load_oncall
from alerting.simulation import SimulatedProvider, parse_outcomes
from alerting.spoken import call_text, word_count
from alerting.state import StateStore
from alerting.tts_preview import (
    duration_seconds,
    synthesize_piper,
    synthesize_say,
    to_phone_quality,
)

__all__ = ["main"]


def _email(case: Case) -> int:
    rotation = load_oncall()
    results = send_alert_email(case.alert, case.decision, [p.email for p in rotation.people])
    print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
    return 0 if all(result.status in {"sent", "dry_run"} for result in results) else 1


def _tts(case: Case, out_dir: Path) -> int:
    text = call_text(case.alert, case.decision)
    print(f"Text ({word_count(text)} words):\n{text}\n")
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = case.alert.alert_id
    engines = {
        "ioana": lambda path: synthesize_say(text, path),
        "piper-mihai": lambda path: synthesize_piper(text, path),
    }
    for name, synthesize in engines.items():
        clear = synthesize(out_dir / f"{stem}_{name}.wav")
        phone = to_phone_quality(clear, out_dir / f"{stem}_{name}_telefon.wav")
        print(f"{name:12} {duration_seconds(clear):5.1f} s  {clear}\n{'':12}{'':8}  {phone}")
    return 0


def _call(case: Case) -> int:
    rotation = load_oncall()
    text = call_text(case.alert, case.decision)
    placed = place_call(case.alert.alert_id, rotation.people[0].phone, text)
    result = wait_for_call(case.alert.alert_id, placed)
    print(json.dumps(asdict(result) | {"answered": result.answered}, ensure_ascii=False, indent=2))
    return 0 if result.status != "rejected" else 1


def _escalate(case: Case, script: str | None, people: list[OnCallPerson]) -> int:
    text = call_text(case.alert, case.decision)
    if script is None:
        outcome = escalate(case.alert.alert_id, text, people)
    else:
        # Fake calls only: sending is safe, the cap file is thrown away, delays are not waited.
        with tempfile.TemporaryDirectory() as scratch:
            outcome = escalate(
                case.alert.alert_id,
                text,
                people,
                env=environment() | {"DRY_RUN": "false"},
                provider=SimulatedProvider(parse_outcomes(script)),
                store=StateStore(Path(scratch) / "alerts.json"),
                sleep=lambda seconds: logging.info("(simulated) waiting %.0f s", seconds),
            )
    summary = {
        "stopped": outcome.stopped,
        "answered_by_person": outcome.answered_by_person,
        "attempts": [
            {"person": a.person, "try": a.try_number} | asdict(a.result) for a in outcome.attempts
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _dispatch(case: Case, script: str | None) -> int:
    if script is None:
        summary = dispatch(case.alert, case.decision)
    else:
        # Scripted calls, email to the local Mailpit only, throwaway state.
        with tempfile.TemporaryDirectory() as scratch:
            summary = dispatch(
                case.alert,
                case.decision,
                env=environment() | {"DRY_RUN": "false", "EMAIL_BACKEND": "mailpit"},
                provider=SimulatedProvider(parse_outcomes(script)),
                store=StateStore(Path(scratch) / "alerts.json"),
                sleep=lambda seconds: logging.info("(simulated) waiting %.0f s", seconds),
            )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    """
    Parse arguments and run one command.

    :param argv: Arguments without the program name. Defaults to None, meaning `sys.argv`.

    :returns: The process exit code.
    """
    parser = argparse.ArgumentParser(prog="python -m alerting")
    commands = parser.add_subparsers(dest="command", required=True)
    email = commands.add_parser("email", help="email one example case to on-call")
    email.add_argument("case", help="JSON file with an alert and a decision")
    tts = commands.add_parser("tts", help="render the spoken message with each local voice")
    tts.add_argument("case", help="JSON file with an alert and a decision")
    tts.add_argument("--out", type=Path, default=PACKAGE_ROOT / "out" / "tts")
    commands.add_parser("call-check", help="read the call provider setup, change nothing")
    call = commands.add_parser("call", help="phone the first on-call person once")
    call.add_argument("case", help="JSON file with an alert and a decision")
    escalation = commands.add_parser("escalate", help="phone on-call in order until one answers")
    escalation.add_argument("case", help="JSON file with an alert and a decision")
    escalation.add_argument(
        "--simulate",
        metavar="OUTCOMES",
        help="comma-separated call outcomes, e.g. no-answer,busy,completed:human; nobody is phoned",
    )
    escalation.add_argument(
        "--people",
        type=int,
        default=None,
        help="with --simulate: pretend the rotation has this many people (copies of the first)",
    )
    send = commands.add_parser("dispatch", help="email, then call with escalation, once per alert")
    send.add_argument("case", help="JSON file with an alert and a decision")
    send.add_argument(
        "--simulate",
        metavar="OUTCOMES",
        help="scripted call outcomes; email goes to Mailpit only; nobody is phoned",
    )
    arguments = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if arguments.command == "call-check":
        print(json.dumps(check_account(), ensure_ascii=False, indent=2))
        return 0
    case = load_case(arguments.case)
    if arguments.command == "email":
        return _email(case)
    if arguments.command == "call":
        return _call(case)
    if arguments.command == "dispatch":
        return _dispatch(case, arguments.simulate)
    if arguments.command == "escalate":
        people = list(load_oncall().people)
        if arguments.simulate and arguments.people:
            people = [
                people[0].model_copy(update={"id": f"garda-{n}"})
                for n in range(1, arguments.people + 1)
            ]
        return _escalate(case, arguments.simulate, people)
    return _tts(case, arguments.out)


if __name__ == "__main__":
    raise SystemExit(main())
