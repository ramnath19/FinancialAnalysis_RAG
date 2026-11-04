"""List account model IDs without displaying credentials."""

import json
import os
from urllib.request import Request, urlopen


def main():
    key = os.environ.get("NEBIUS_API_KEY")
    if not key:
        raise SystemExit("Set NEBIUS_API_KEY locally first.")
    base = os.environ.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1").rstrip("/")
    if not base.startswith("https://"):
        raise SystemExit("Use an HTTPS endpoint.")
    request = Request(base + "/models", headers={"Authorization": "Bearer " + key})
    with urlopen(request, timeout=30) as response:
        data = json.load(response)
    for model in data.get("data", []):
        print(model["id"])


if __name__ == "__main__":
    main()
