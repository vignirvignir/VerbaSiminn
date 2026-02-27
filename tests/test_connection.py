"""Smoke test: authenticate and search calls against the live Verba API."""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from verba_client import VerbaClient

def main():
    base_url = os.environ["VERBA_BASE_URL"]
    api_key = os.environ["VERBA_API_KEY"]
    username = os.environ["VERBA_USERNAME"]
    password = os.environ["VERBA_PASSWORD"]

    print(f"Connecting to {base_url} ...")

    with VerbaClient(base_url, api_key, username, password) as client:
        print(f"Token acquired: {client.token[:12]}...")
        print(f"Token valid: {client.is_token_valid}")

        # Search calls from the last 7 days
        end = datetime.now()
        start = end - timedelta(days=7)
        print(f"\nSearching calls from {start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} ...")

        result = client.search_calls(start, end, pagelen=5)
        print(f"Total calls found: {result.total_count}")

        for i, call in enumerate(result.calls):
            print(f"\n  [{i+1}] {call.ccdr_id}")
            print(f"      From: {call.source_caller_id} ({call.source_name})")
            print(f"      To:   {call.destination_caller_id} ({call.destination_name})")
            print(f"      Time: {call.start_time} -> {call.end_time}")
            print(f"      Duration: {call.duration}")

    print("\nDone.")


if __name__ == "__main__":
    main()
