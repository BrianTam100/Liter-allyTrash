"""Post an identified disposal from the Pi to Literally Trash. No extra packages.

Call post_bin_event from your bin detection code after identifying the depositor.
Reuse event_id on retries so an item is never scored twice.
"""
import argparse
import json
import os
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def post_bin_event(base_url, api_key, user_id, item_name, category, count=1, event_id=None):
    if not api_key:
        raise ValueError("Set COLLECTION_API_KEY on the Pi and the website to the same secret.")
    event_id = str(uuid.UUID(event_id)) if event_id else str(uuid.uuid4())
    payload = {"user_id": user_id, "item_name": item_name, "category": category,
               "count": count, "request_id": event_id}
    request = Request(base_url.rstrip("/") + "/api/bin-events", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key}, method="POST")
    try:
        with urlopen(request, timeout=10) as response:
            return {"event_id": event_id, **json.load(response)}
    except (HTTPError, URLError, TimeoutError) as exc:
        # The server may have saved the event before the connection failed.
        raise RuntimeError(f"Bin event could not be confirmed. Retry with event_id={event_id}.") from exc


def main():
    parser = argparse.ArgumentParser(description="Send a bin event to Literally Trash")
    parser.add_argument("--url", default=os.getenv("LITERALLY_TRASH_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--item", required=True)
    parser.add_argument("--category", choices=["trash", "recycling"], required=True)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--event-id", help="Reuse the original UUID when retrying an event")
    args = parser.parse_args()
    try:
        result = post_bin_event(args.url, os.getenv("COLLECTION_API_KEY", ""), args.user_id,
            args.item, args.category, args.count, args.event_id)
    except (ValueError, RuntimeError) as exc:
        parser.exit(1, str(exc) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
