import argparse
import asyncio
import json
from app.db import init_db
from app.services.digest import send_daily_digest
from app.services.ingest import run_all_connectors


async def _run_ingest() -> None:
    await init_db()
    summaries = await run_all_connectors()
    for s in summaries:
        s.pop("_id", None)
    print(json.dumps(summaries, default=str, indent=2))


async def _send_digest() -> None:
    await init_db()
    res = await send_daily_digest()
    print(json.dumps(res, default=str, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Personal Job Radar CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run-ingest", help="Run all configured job connectors and score new jobs")
    sub.add_parser("send-digest", help="Build and send the daily high-signal job digest")
    args = parser.parse_args()

    if args.command == "run-ingest":
        asyncio.run(_run_ingest())
    elif args.command == "send-digest":
        asyncio.run(_send_digest())


if __name__ == "__main__":
    main()
