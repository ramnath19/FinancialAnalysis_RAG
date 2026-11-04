"""SEC latest-10K ingestion into a separate persistent local corpus."""

import hashlib
import json
import os
import re
import threading
import time
import uuid
from urllib.request import Request, urlopen

from lxml import html

from .figures import from_company_facts
from .logging_config import LOGGER, REQUEST_ID, event
from .registry import ROOT, Registry, atomic_json, atomic_write
from .section_chunk import section_chunks

JOBS = {}
LOCK = threading.RLock()
PACE = threading.Lock()
LAST = 0


def jobs_snapshot():
    with LOCK:
        return [dict(job) for job in JOBS.values()]


def update_job(identity, **fields):
    with LOCK:
        JOBS[identity].update(fields)
        job = dict(JOBS[identity])
    event(
        "ingestion.stage",
        job_id=identity,
        ticker=job.get("ticker"),
        stage=job.get("stage"),
        progress=job.get("progress"),
        status=job.get("status"),
    )


def fetch(url):
    global LAST
    agent = os.getenv("SEC_USER_AGENT", "").strip()
    if not agent or "@" not in agent:
        raise ValueError(
            'Add SEC_USER_AGENT="Your name email@example.com" to the local .env first.'
        )
    with PACE:
        time.sleep(max(0, 0.25 - (time.monotonic() - LAST)))
        LAST = time.monotonic()
        with urlopen(
            Request(url, headers={"User-Agent": agent, "Accept-Encoding": "identity"}), timeout=40
        ) as response:
            return response.read()


def clean_html(raw):
    tree = html.fromstring(raw)
    for node in tree.xpath('//script|//style|//*[local-name()="hidden"]'):
        node.drop_tree()
    for node in tree.xpath("//p|//tr|//h1|//h2|//h3|//div|//li"):
        node.tail = "\n" + (node.tail or "")
    for node in tree.xpath("//td|//th"):
        node.tail = " | " + (node.tail or "")
    lines = [t.strip() for t in tree.text_content().splitlines() if t.strip()]
    text = "\n".join(lines)
    if not text:
        raise ValueError("The downloaded filing has no extractable text.")
    return text


def run(identity, ticker):
    token = REQUEST_ID.set(identity)
    registry = Registry()
    try:
        update_job(identity, stage="Resolve ticker", progress=10)
        mapping = json.loads(fetch("https://www.sec.gov/files/company_tickers.json"))
        company = next((c for c in mapping.values() if c["ticker"].upper() == ticker), None)
        if company is None:
            raise ValueError("Ticker was not found in the SEC company directory.")
        cik = str(company["cik_str"])
        update_job(identity, stage="Find latest 10-K", progress=25)
        submission = json.loads(fetch(f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json"))
        recent = submission["filings"]["recent"]
        index = next((i for i, f in enumerate(recent["form"]) if f == "10-K"), None)
        if index is None:
            raise ValueError("No 10-K found in recent SEC submissions.")
        accession = recent["accessionNumber"][index]
        existing = registry.sessions().get(ticker)
        if existing and existing.get("accession") == accession:
            update_job(identity, stage="Already current", progress=100, status="complete")
            return
        source = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{recent['primaryDocument'][index]}"
        raw = fetch(source)
        update_job(identity, stage="Clean filing", progress=45)
        text = clean_html(raw)
        docid = ticker.lower() + "-" + accession
        period = recent["reportDate"][index]
        block = {
            "document_id": docid,
            "company": company["title"],
            "ticker": ticker,
            "report_fiscal_year": int(period[:4]),
            "document_type": "10-K",
            "source_url": source,
            "block_id": hashlib.sha256(raw).hexdigest()[:24],
            "kind": "text",
            "text": text,
            "location": {"section": "SEC annual filing"},
            "source_sha256": hashlib.sha256(raw).hexdigest(),
        }
        chunks = section_chunks([block])
        update_job(identity, stage="Build local chunks and figures", progress=70)
        facts = json.loads(
            fetch(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik.zfill(10)}.json")
        )
        folder = ROOT / "data/session" / ticker
        folder.mkdir(parents=True, exist_ok=True)
        atomic_write(folder / "filing.html", raw)
        atomic_write(folder / "section.jsonl", "".join(json.dumps(c) + "\n" for c in chunks))
        # Fixed local chunks preserve the source independently of semantic boundaries.
        fixed = []
        for start in range(0, len(text), 1800):
            c = {
                **block,
                "chunk_id": docid + "-" + str(start),
                "strategy": "fixed",
                "text": text[start : start + 2000],
            }
            fixed.append(c)
        atomic_write(folder / "fixed.jsonl", "".join(json.dumps(c) + "\n" for c in fixed))
        atomic_json(folder / "figures.json", from_company_facts(facts, ticker, company["title"]))
        document = {
            "document_id": docid,
            "ticker": ticker,
            "company": company["title"],
            "fiscal_year": int(period[:4]),
            "source_url": source,
            "document_type": "10-K",
        }
        registry.register({"ticker": ticker, "accession": accession, "documents": [document]})
        update_job(
            identity, stage="Ready: local lexical retrieval", progress=100, status="complete"
        )
    except Exception as error:
        LOGGER.exception(
            "ingestion.failed", extra={"fields": {"job_id": identity, "ticker": ticker}}
        )
        update_job(
            identity,
            status="failed",
            stage="Stopped",
            error=str(error)
            if isinstance(error, ValueError)
            else "SEC download failed. Check network access and SEC_USER_AGENT; retry later.",
        )

    finally:
        REQUEST_ID.reset(token)


def start(ticker):
    if not isinstance(ticker, str):
        raise ValueError("Enter a ticker symbol.")
    ticker = ticker.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", ticker):
        raise ValueError("Enter a valid ticker symbol.")
    with LOCK:
        if any(j["status"] == "running" for j in JOBS.values()):
            raise ValueError("An ingestion is already running. Please wait.")
        if ticker not in Registry().sessions() and len(Registry().sessions()) >= 40:
            raise ValueError("The local session limit is 40 companies.")
        # Keep recent completed jobs bounded for long-running local sessions.
        finished = [key for key, value in JOBS.items() if value["status"] != "running"]
        for key in finished[:-49]:
            JOBS.pop(key, None)
        identity = uuid.uuid4().hex
        JOBS[identity] = {
            "id": identity,
            "ticker": ticker,
            "status": "running",
            "stage": "Queued",
            "progress": 0,
        }
        threading.Thread(target=run, args=(identity, ticker), daemon=True).start()
        return dict(JOBS[identity])
