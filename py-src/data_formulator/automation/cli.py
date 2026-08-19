# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Command-line entry point for the resident Automation Worker process."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import sys
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

from data_formulator.automation.runtime import AutomationRuntime
from data_formulator.automation.worker import (
    AutomationWorkerDisabledError,
    AutomationWorkerError,
)
from data_formulator.recipes.openers import WorkspaceOpenError
from data_formulator.security.code_signing import CodeSigningConfigurationError
from data_formulator.security.log_sanitizer import SensitiveDataFilter


logger = logging.getLogger(__name__)


def _load_worker_environment() -> None:
    """Load the same package/repository env files as the Web entry point."""
    package_root = Path(__file__).resolve().parents[1]
    load_dotenv(package_root.parent.parent / ".env")
    load_dotenv(package_root / ".env")


def _positive_seconds(value: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _non_empty(value: str) -> str:
    parsed = value.strip()
    if not parsed:
        raise argparse.ArgumentTypeError("must not be empty")
    return parsed


def _default_worker_id() -> str:
    configured = os.getenv("AUTOMATION_WORKER_ID")
    if configured is not None:
        return configured
    return f"{socket.gethostname()}-{os.getpid()}"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="data_formulator_worker",
        description=(
            "Run the local Data Formulator Automation Scheduler and Worker."
        ),
    )
    parser.add_argument(
        "--worker-id",
        type=_non_empty,
        default=_default_worker_id(),
        help=(
            "Stable identifier used for fenced Run leases "
            "(default: AUTOMATION_WORKER_ID or hostname-pid)."
        ),
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=_positive_seconds,
        default=os.getenv("AUTOMATION_POLL_INTERVAL_SECONDS", "1"),
        help="Seconds between Scheduler/Worker cycles (default: 1).",
    )
    parser.add_argument(
        "--lease-seconds",
        type=_positive_seconds,
        default=os.getenv("AUTOMATION_LEASE_SECONDS", "30"),
        help="Fenced Run lease duration in seconds (default: 30).",
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=_positive_seconds,
        default=os.getenv("AUTOMATION_HEARTBEAT_SECONDS", "10"),
        help="Lease heartbeat interval in seconds (default: 10).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Execute one Scheduler/Worker cycle and exit.",
    )
    return parser.parse_args(argv)


def _configure_console_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(SensitiveDataFilter())
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[handler],
    )
    logging.getLogger("data_formulator").setLevel(level)


@contextmanager
def _stop_on_signals(stop_event: threading.Event) -> Iterator[None]:
    previous: dict[signal.Signals, object] = {}

    def request_stop(_signum, _frame) -> None:
        stop_event.set()

    try:
        for name in ("SIGINT", "SIGTERM"):
            candidate = getattr(signal, name, None)
            if candidate is None:
                continue
            previous[candidate] = signal.getsignal(candidate)
            signal.signal(candidate, request_stop)
        yield
    finally:
        for candidate, handler in previous.items():
            signal.signal(candidate, handler)


def _configuration_error(message: str) -> int:
    print(f"data_formulator_worker: {message}", file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    _load_worker_environment()
    args = parse_args(argv)
    if args.heartbeat_seconds >= args.lease_seconds:
        return _configuration_error(
            "Heartbeat interval must be shorter than the Run lease."
        )
    stop_event = threading.Event()
    try:
        runtime = AutomationRuntime.from_environment(
            worker_id=args.worker_id,
            poll_interval=timedelta(seconds=args.poll_interval_seconds),
            lease_duration=timedelta(seconds=args.lease_seconds),
            heartbeat_interval=timedelta(seconds=args.heartbeat_seconds),
            stop_event=stop_event,
        )
        _configure_console_logging()
        if args.once:
            runtime.run_cycle()
            return 0
        logger.info(
            "Automation Worker started for data home %s.",
            runtime.data_home,
        )
        with _stop_on_signals(stop_event):
            runtime.run_forever()
        logger.info("Automation Worker stopped.")
        return 0
    except AutomationWorkerDisabledError:
        return _configuration_error(
            "Automation is disabled; set AUTOMATION_ENABLED=true."
        )
    except CodeSigningConfigurationError:
        return _configuration_error(
            "Stable code signing is required; configure "
            "DF_CODE_SIGNING_SECRET or FLASK_SECRET_KEY."
        )
    except WorkspaceOpenError:
        return _configuration_error(
            "Only a durable local Workspace backend is supported."
        )
    except (AutomationWorkerError, TypeError, ValueError):
        return _configuration_error("Automation Worker configuration is invalid.")
    except KeyboardInterrupt:
        stop_event.set()
        return 0
    except Exception:
        print(
            "data_formulator_worker: Automation Worker stopped unexpectedly.",
            file=sys.stderr,
        )
        return 1
