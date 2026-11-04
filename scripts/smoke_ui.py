"""Check local UI contracts. Add --live for one billable Pinecone/Nebius answer."""

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8501")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    checks = []

    def request(path, body=None, expected=200, origin=None, raw=None):
        data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        if origin:
            headers["Origin"] = origin
        req = Request(args.base_url + path, data=data, headers=headers)
        try:
            response = urlopen(req, timeout=180)
        except HTTPError as error:
            response = error
        with response:
            assert response.status == expected, (path, response.status)
            request_id = response.headers.get("X-Request-ID")
            assert request_id and len(request_id) == 32
            payload = response.read()
            if "application/json" in response.headers.get("Content-Type", ""):
                result = json.loads(payload)
                assert result["request_id"] == request_id
                return result
            return payload

    page = request("/")
    assert b'id="ask-form"' in page and b'id="chat-view"' in page
    request("/app.js")
    request("/style.css")
    checks.append("page and static assets")
    status = request("/api/status")
    assert status["documents"] >= 13 and "services" in status
    request("/api/ask", {}, expected=400)
    request("/api/ask", {"question": "Apple revenue?", "context": {"year": 2025}}, expected=400)
    request("/api/ask", raw=b"{broken", expected=400)
    request("/api/ask", {}, expected=403, origin="https://unrelated.example")
    checks.append("validation, malformed JSON, cross-origin rejection and request IDs")
    for question, expected in [
        ("What was net income?", "clarify"),
        ("Predict Apple stock price tomorrow", "refused"),
    ]:
        result = request("/api/ask", {"question": question, "offline": True, "rerank": False})
        assert result["answer_status"] == expected
    result = request(
        "/api/ask",
        {
            "question": "Compare Apple and Microsoft revenue in 2025",
            "strategy": "section",
            "offline": True,
            "rerank": False,
        },
    )
    assert result["answer_status"] == "excerpts"
    assert {source["metadata"]["ticker"] for source in result["sources"]} == {"AAPL", "MSFT"}
    followup = request(
        "/api/ask",
        {
            "question": "And last year?",
            "strategy": "section",
            "offline": True,
            "rerank": False,
            "context": result["context"],
        },
    )
    assert followup["context"]["year"] == "2024"
    checks.append("scope, comparison and follow-up memory")
    for strategy in ["fixed", "semantic", "section"]:
        assert request("/api/chunks?strategy=" + strategy)["count"] > 0
    request("/api/chunks?strategy=invalid", expected=400)
    request("/api/jobs")
    assert len(request("/api/evaluation")["local_retrieval"]["rows"]) == 6
    request("/api/market?ticker=invalid%2Fpath", expected=400)
    checks.append("chunk lab, jobs, evaluation and market validation")
    if args.live:
        result = request(
            "/api/ask",
            {
                "question": "What was JPMorgan Chase net income in 2024?",
                "strategy": "fixed",
                "rerank": True,
            },
        )
        assert result["sources"] and result["answer_status"] in ("answered", "abstained")
        checks.append("live provider response with evidence")
    output = {
        "passed": checks,
        "live_provider_check": args.live,
        "visual_browser_check": "unavailable",
    }
    Path("reports/ui-refactor-smoke.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
