"""
Autonomous LangGraph Dispatch Agent Test Runner.

Executes and logs the end-to-end autonomous dispatch agent workflow:
  1. Fleet Predictive Maintenance (ML Inference)
  2. Wind Park Health Triage
  3. Park-Scoped Crew Isolation & Capacity Check
  4. Crew Contention Detection & Wind Power Output Prioritization
  5. Crew Matching & Task Assignment
  6. Multi-Channel Alerting (Automated TTS Voice Call vs Email Work Order)

Usage:
  python scripts/test_agent.py
  python scripts/test_agent.py --park 1
  python scripts/test_agent.py --simulate-contention
  python scripts/test_agent.py --all-parks
"""

import argparse
import logging
import os
from pathlib import Path
import sys
from typing import Any

# Ensure repository root is on sys.path when script is invoked directly
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from smarthack.clients.crew_client import get_default_crew_client  # noqa: E402
from smarthack.clients.email_client import get_default_email_client  # noqa: E402
from smarthack.clients.voice_client import get_default_voice_client  # noqa: E402
from smarthack.services.agent.graph import run_park_dispatch_agent  # noqa: E402
from smarthack.services.dispatch_service import get_default_dispatch_service  # noqa: E402


def configure_runner_logging(verbose: bool = False) -> None:
    """
    Set up clean, structured terminal logging for the test execution.

    :param verbose: If True, enables DEBUG logs. Defaults to INFO.
    """
    log_level = logging.DEBUG if verbose else logging.INFO
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=log_level, format=log_format, datefmt="%H:%M:%S")
    # Suppress external noise
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def run_contention_simulation() -> int:
    """
    Run an interactive contention scenario where failing turbines exceed available crews.

    Forces execution of the 7-day Wind Power Output Model to test energy loss prioritization.

    :returns exit_code: Process exit code 0 on success.
    """
    logger = logging.getLogger("agent.test")
    logger.info(">>> STARTING CREW CONTENTION SIMULATION (3 Failing vs 2 Crews) <<<")

    os.environ["AGENT_DATA_SOURCE"] = "simulated"
    crew_client = get_default_crew_client()
    crew_client.reset_crews()

    # Scenario: 3 failing turbines in wind_farm_a (which has only 2 available crews)
    triage_scenario = [
        {
            "turbine_id": 101,
            "park_id": "wind_farm_a",
            "health_status": "CRITICAL",
            "fault_probability": 0.95,
            "days_to_failure": 1.0,
            "suspected_failure": "Generator Bearing Thermal Runaway",
            "recommended_action": "Emergency shutdown and inspect bearing DE.",
            "needs_repair": True,
        },
        {
            "turbine_id": 102,
            "park_id": "wind_farm_a",
            "health_status": "WARNING",
            "fault_probability": 0.75,
            "days_to_failure": 3.5,
            "suspected_failure": "Gearbox Oil Overheating",
            "recommended_action": "Inspect oil pump pressure and fluid filters.",
            "needs_repair": True,
        },
        {
            "turbine_id": 103,
            "park_id": "wind_farm_a",
            "health_status": "WARNING",
            "fault_probability": 0.70,
            "days_to_failure": 4.0,
            "suspected_failure": "Generator Stator Winding Vibration",
            "recommended_action": "Schedule thermography and vibration analysis.",
            "needs_repair": True,
        },
    ]

    result = run_park_dispatch_agent(park_id="wind_farm_a", triage_items=triage_scenario)
    _print_results(result, title="SIMULATION RESULTS: POWER MODEL PRIORITIZATION")
    return 0


def run_single_park(park_id: str) -> int:
    """
    Execute the LangGraph dispatch workflow for a specific wind park.

    :param park_id: Wind park identifier (e.g. '1', 'wind_farm_a').

    :returns exit_code: Process exit code 0 on success.
    """
    logger = logging.getLogger("agent.test")
    logger.info(">>> EXECUTING AUTONOMOUS AGENT FOR PARK: %s <<<", park_id)

    result = run_park_dispatch_agent(park_id=park_id)
    _print_results(result, title=f"WORKFLOW RESULTS FOR PARK {park_id}")
    return 0


def run_full_fleet_sweep() -> int:
    """
    Execute a full fleet sweep across all registered wind parks.

    :returns exit_code: Process exit code 0 on success.
    """
    logger = logging.getLogger("agent.test")
    logger.info(">>> EXECUTING FULL FLEET SWEEP ACROSS ALL PARKS <<<")

    if os.environ.get("AGENT_DATA_SOURCE") == "supabase":
        import asyncio
        from datetime import datetime, timezone
        import httpx
        from smarthack.clients import supabase
        from smarthack.schemas.dispatch import (
            AlertChannel,
            DispatchDecision,
            FleetSweepReport,
            ParkSweepResult,
        )

        async def _get_park_ids() -> list[str]:
            async with httpx.AsyncClient(timeout=10.0) as http:
                parks = await supabase.fetch_parks(http)
                return [str(p["id"]) for p in parks]

        try:
            park_ids = asyncio.run(_get_park_ids())
        except Exception:
            park_ids = ["1", "2", "3", "4", "5"]

        park_results: dict[str, ParkSweepResult] = {}
        total_scanned = 0
        total_faults = 0
        critical_alerts = 0
        warning_alerts = 0

        for pid in park_ids:
            logger.info("Sweeping park %s via LangGraph agent...", pid)
            res = run_park_dispatch_agent(park_id=pid)
            decisions = [
                DispatchDecision.model_validate(d) for d in res.get("alert_decisions", [])
            ]
            failing = res.get("failing_turbines", [])
            crews = res.get("available_crews", [])
            scanned = len(res.get("triage_items", []))
            total_scanned += scanned
            total_faults += len(failing)
            for d in decisions:
                if d.alert_channel == AlertChannel.VOICE_CALL:
                    critical_alerts += 1
                elif d.alert_channel == AlertChannel.EMAIL:
                    warning_alerts += 1

            park_results[pid] = ParkSweepResult(
                park_id=pid,
                turbines_scanned=scanned,
                turbines_needing_repair=len(failing),
                crews_available=len(crews),
                conflict_detected=bool(res.get("has_conflict", False)),
                power_model_invoked=bool(res.get("power_model_invoked", False)),
                decisions=decisions,
            )

        report = FleetSweepReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_turbines_scanned=total_scanned,
            total_faults_detected=total_faults,
            critical_alerts_count=critical_alerts,
            warning_alerts_count=warning_alerts,
            park_results=park_results,
        )
    else:
        dispatch_svc = get_default_dispatch_service()
        report = dispatch_svc.run_daily_fleet_sweep()

    print("\n" + "=" * 70)
    print(" FLEET SWEEP REPORT SUMMARY")
    print("=" * 70)
    print(f"Timestamp:                 {report.timestamp}")
    print(f"Total Turbines Scanned:    {report.total_turbines_scanned}")
    print(f"Total Faults Detected:     {report.total_faults_detected}")
    print(f"Critical Alerts (Voice):   {report.critical_alerts_count}")
    print(f"Warning Alerts (Email):    {report.warning_alerts_count}")
    print("=" * 70)

    for pid, presult in report.park_results.items():
        print(f"\n[Park {pid}]")
        print(
            f"  • Scanned: {presult.turbines_scanned} | Failing: {presult.turbines_needing_repair} "
            f"| Crews: {presult.crews_available}"
        )
        print(
            f"  • Contention: {presult.conflict_detected} | Power Model Invoked: {presult.power_model_invoked}"
        )
        for d in presult.decisions:
            print(
                f"    - Turbine {d.turbine_id}: {d.health_status} -> {d.alert_channel.value} "
                f"(Crew: {d.assigned_crew_name})"
            )

    _print_dispatched_messages()
    return 0


def _print_results(result: dict[str, Any], title: str) -> None:
    """
    Format and print readable execution diagnostics to standard output.

    :param result: LangGraph final state dictionary.
    :param title: Header title banner.
    """
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)
    print(f"Park Identifier:           {result.get('park_id')}")
    print(f"Turbines Needing Repair:   {len(result.get('failing_turbines', []))}")
    print(f"Available Park Technicians:{len(result.get('available_crews', []))}")
    print(f"Crew Shortage Contention:  {result.get('has_conflict')}")
    print(f"Power Prioritization Run:  {result.get('power_model_invoked')}")
    if result.get("power_evaluations"):
        print(f"Projected 7-Day MWh Losses:{result.get('power_evaluations')}")
    print(f"Total Dispatch Decisions:  {len(result.get('alert_decisions', []))}")
    print("-" * 70)

    decisions = result.get("alert_decisions", [])
    if not decisions:
        print("No turbines require dispatch at this time.")
    else:
        for d in decisions:
            rank = d.get("priority_rank", 0)
            tid = d.get("turbine_id")
            status = d.get("health_status")
            channel = d.get("alert_channel")
            ch_val = channel.value if hasattr(channel, "value") else str(channel)
            crew_name = d.get("assigned_crew_name") or "UNASSIGNED (DEFERRED)"
            print(f"\n[Rank #{rank}] Turbine {tid} | Status: {status} | Alert Channel: {ch_val}")
            print(f"  • Assigned Technician : {crew_name} (ID: {d.get('assigned_crew_id')})")
            print(f"  • Decision Reason     : {d.get('decision_reason')}")
            if d.get("notification_sent"):
                print("  • Notification Sent   : YES")

    print("\n" + "-" * 70)
    _print_dispatched_messages()
    print("=" * 70 + "\n")


def _print_dispatched_messages() -> None:
    """
    Print transcripts of dispatched voice calls and emails from client history.
    """
    voice_client = get_default_voice_client()
    calls = voice_client.get_call_history()
    if calls:
        print(f"\n📞 RECENT VOICE CALL DISPATCHES (Total: {len(calls)}):")
        for call in calls[-3:]:
            print(
                f"  • [{call.get('call_id')}] To: {call.get('crew_name')} ({call.get('phone_number')})"
            )
            print(f"    Turbine: {call.get('turbine_id')} in Park {call.get('park_id')}")
            print(f"    TTS Transcript: \"{call.get('synthesized_speech')}\"")

    email_client = get_default_email_client()
    emails = email_client.get_email_history()
    if emails:
        print(f"\n📧 RECENT EMAIL WORK ORDER DISPATCHES (Total: {len(emails)}):")
        for mail in emails[-3:]:
            print(f"  • [{mail.get('ticket_id')}] To: {mail.get('recipient_email')}")
            print(f"    Subject: {mail.get('subject')}")
            print(f"    Body: {mail.get('body')}")


def main() -> int:
    """
    Parse command line options and run the agent diagnostic test.

    :returns code: Exit code.
    """
    parser = argparse.ArgumentParser(
        description="Test runner for LangGraph predictive dispatch agent."
    )
    parser.add_argument(
        "--park",
        default="1",
        help="Wind park ID to evaluate (e.g. '1', '2', 'wind_farm_a'). Defaults to '1'.",
    )
    parser.add_argument(
        "--simulate-contention",
        action="store_true",
        help="Simulate a resource contention scenario (3 failing turbines vs 2 crews) to test power model prioritization.",
    )
    parser.add_argument(
        "--all-parks",
        action="store_true",
        help="Execute a fleet-wide health sweep across all registered wind parks.",
    )
    parser.add_argument(
        "--source",
        choices=["supabase", "simulated"],
        default=None,
        help="Override AGENT_DATA_SOURCE ('supabase' or 'simulated').",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging.",
    )

    args = parser.parse_args()
    configure_runner_logging(verbose=args.verbose)

    if args.source:
        os.environ["AGENT_DATA_SOURCE"] = args.source
    elif not os.environ.get("AGENT_DATA_SOURCE"):
        os.environ["AGENT_DATA_SOURCE"] = "supabase"

    if args.simulate_contention:
        return run_contention_simulation()
    elif args.all_parks:
        return run_full_fleet_sweep()
    else:
        return run_single_park(park_id=args.park)


if __name__ == "__main__":
    sys.exit(main())
