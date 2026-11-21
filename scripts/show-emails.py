#!/usr/bin/env python3
"""Print the emails the app has "sent" to LocalStack's SES emulation.

Local development only: LocalStack stores every message instead of delivering it.

    scripts/show-emails.py                    # all messages, oldest first
    scripts/show-emails.py -t user@x.com      # only mail addressed to that recipient
    scripts/show-emails.py -n 3               # only the 3 most recent
    scripts/show-emails.py --clear            # delete all stored messages
    scripts/show-emails.py --endpoint URL     # default: $AWS_ENDPOINT_URL or http://localhost:4566
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def _request(url: str, method: str = "GET") -> bytes:
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("-t", "--to", help="only show mail sent to this address")
    parser.add_argument("-n", "--last", type=int, help="only show the N most recent messages")
    parser.add_argument("--clear", action="store_true", help="delete all stored messages and exit")
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566"),
        help="LocalStack endpoint",
    )
    args = parser.parse_args()

    url = args.endpoint.rstrip("/") + "/_aws/ses"
    try:
        if args.clear:
            _request(url, "DELETE")
            print("Cleared all stored messages.")
            return 0
        query = {"email": args.to} if args.to else {}
        if query:
            url += "?" + urllib.parse.urlencode(query)
        messages = json.loads(_request(url)).get("messages", [])
    except (urllib.error.URLError, OSError) as exc:
        print(f"Could not reach LocalStack at {args.endpoint}: {exc}", file=sys.stderr)
        print("Is `docker-compose up` running?", file=sys.stderr)
        return 1

    messages.sort(key=lambda m: m.get("Timestamp", ""))
    if args.last:
        messages = messages[-args.last :]
    if not messages:
        print("No messages.")
        return 0

    for msg in messages:
        body = msg.get("Body", {})
        recipients = ", ".join(msg.get("Destination", {}).get("ToAddresses", []))
        print("=" * 72)
        print(f"Time:    {msg.get('Timestamp', '?')}")
        print(f"From:    {msg.get('Source', '?')}")
        print(f"To:      {recipients}")
        print(f"Subject: {msg.get('Subject', '?')}")
        print("-" * 72)
        print(body.get("text_part") or body.get("html_part") or "(empty body)")
        print()
    print(f"{len(messages)} message(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
