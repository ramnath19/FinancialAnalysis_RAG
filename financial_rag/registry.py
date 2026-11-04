"""Persistent corpus registry; bundled benchmark and runtime additions stay separate."""

import json
import os
import re
import tempfile
import threading
from pathlib import Path

REGISTRY_LOCK = threading.RLock()
ROOT = Path(__file__).resolve().parents[1]
ALIASES = {
    "AAPL": ["Apple", "Apple Inc."],
    "MSFT": ["Microsoft", "Microsoft Corporation"],
    "GOOGL": ["Google", "Alphabet", "Alphabet Inc."],
    "JPM": ["JPMorgan", "JPMorgan Chase", "JP Morgan", "JPMC"],
    "TSLA": ["Tesla"],
    "NVDA": ["Nvidia"],
    "AMZN": ["Amazon"],
    "NFLX": ["Netflix"],
    "META": ["Meta Platforms", "Facebook"],
}


def atomic_write(path, data):
    """Publish a complete file with a unique temporary name in the same directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix="." + path.name, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(data if isinstance(data, bytes) else data.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def atomic_json(path, data):
    atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


class Registry:
    def __init__(self, root=ROOT):
        self.root = Path(root)

    def documents(self, selector="active"):
        bundled = json.loads((self.root / "data/manifest.json").read_text())
        sessions = self.sessions()
        docs = [dict(d, origin="bundled") for d in bundled]
        if selector != "bundled":
            for company in sessions.values():
                docs.extend(dict(d, origin="session") for d in company["documents"])
        if selector not in ("active", "bundled"):
            docs = [d for d in docs if d.get("ticker", "").upper() == selector.upper()]
        return docs

    def sessions(self):
        p = self.root / "data/session/registry.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def register(self, company):
        with REGISTRY_LOCK:
            sessions = self.sessions()
            sessions[company["ticker"]] = company
            atomic_json(self.root / "data/session/registry.json", sessions)

    def companies(self, selector="active"):
        result = {}
        for doc in self.documents(selector):
            ticker = doc["ticker"]
            item = result.setdefault(
                ticker,
                {
                    "ticker": ticker,
                    "name": doc["company"],
                    "aliases": ALIASES.get(ticker, []),
                    "documents": [],
                    "origin": doc["origin"],
                },
            )
            item["documents"].append(doc)
        return list(result.values())

    def detect(self, text):
        known = {x["ticker"]: x for x in self.companies()}
        result = []
        aliases = {**ALIASES, **{t: [c["name"]] + c.get("aliases", []) for t, c in known.items()}}
        for ticker, names in aliases.items():
            if any(
                re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text, re.I)
                for name in names + [ticker]
            ):
                result.append(ticker)
        return list(dict.fromkeys(result))

    def strategies(self, ticker, selector="active"):
        """Return strategies with an indexed source for this company and corpus."""
        documents = [d for d in self.documents(selector) if d["ticker"] == ticker]
        available = []
        for strategy in ("fixed", "semantic", "section"):
            for document in documents:
                folder = (
                    self.root / "data/chunks/reference"
                    if document["origin"] == "bundled"
                    else self.root / "data/session" / ticker
                )
                path = folder / f"{strategy}.jsonl"
                if path.exists() and path.stat().st_size:
                    available.append(strategy)
                    break
        return available

    def company(self, ticker):
        return next((c for c in self.companies() if c["ticker"] == ticker), None)
