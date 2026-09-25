"""Command-line entry point for ``python -m pmjev``."""

from __future__ import annotations

import argparse
import asyncio
import logging

import httpx

from pmjev.alerts import TelegramAlerts
from pmjev.config import Settings
from pmjev.main import run_collector, run_doctor
from pmjev.market.gamma import GammaClient
from pmjev.report import render_report
from pmjev.resolver import Resolver
from pmjev.store import Store

logger = logging.getLogger(__name__)


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(prog="python -m pmjev")
    subcommands = cli.add_subparsers(dest="command", required=True)
    run = subcommands.add_parser("run", help="run the paper data collector")
    run.add_argument("--no-jev", action="store_true", help="collect Phase 0 baselines only")
    subcommands.add_parser("resolve", help="resolve pending windows from Gamma")
    subcommands.add_parser("report", help="print metrics for resolved predictions")
    subcommands.add_parser("doctor", help="verify all Phase 0 public APIs and assets")
    return cli


async def resolve(settings: Settings) -> None:
    store = Store(settings.db_url)
    store.initialize()
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_s) as client:
            alerts = TelegramAlerts(
                store=store,
                client=client,
                bot_token=settings.telegram_bot_token,
                chat_id=settings.telegram_chat_id,
                message_thread_id=settings.telegram_message_thread_id,
                mode=settings.mode,
            )
            alerts_task = asyncio.create_task(alerts.run())
            try:
                resolved, checked = await Resolver(
                    store, GammaClient(client, settings.gamma_url)
                ).resolve_pending_details()
                for resolution in resolved:
                    alerts.window_settled(slug=resolution.slug, outcome=resolution.outcome)
            finally:
                await alerts.close()
                await asyncio.gather(alerts_task, return_exceptions=True)
        print(f"Resolved {len(resolved)}/{checked} pending windows.")
    finally:
        store.close()


def main() -> None:
    cli = parser()
    args = cli.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings()
    try:
        if args.command == "run":
            asyncio.run(run_collector(settings, no_jev=bool(args.no_jev)))
        elif args.command == "resolve":
            asyncio.run(resolve(settings))
        elif args.command == "report":
            store = Store(settings.db_url)
            store.initialize()
            try:
                print(render_report(store))
            finally:
                store.close()
        elif args.command == "doctor":
            asyncio.run(run_doctor(settings))
    except KeyboardInterrupt:
        logger.info("collector stopped by user")
    except ValueError as exc:
        cli.error(str(exc))


if __name__ == "__main__":
    main()
