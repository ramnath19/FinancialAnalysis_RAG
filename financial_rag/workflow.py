"""Bounded generation/verification graph; scope and retrieval occur before entry."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .logging_config import event


class State(TypedDict, total=False):
    question: str
    evidence: str
    sources: list
    answer: str
    verification: dict
    attempts: int
    trace: list


def guarded_generate(question, evidence, sources, generator, checker):
    def generate(state):
        retry = state["attempts"] > 0
        event("generation.started", attempt=state["attempts"] + 1, sources=len(state["sources"]))
        instruction = (
            " Use only numbers exactly as printed in cited passages. Avoid conversions and calculations."
            if retry
            else ""
        )
        return {
            "answer": generator(
                state["question"] + instruction, state["evidence"], state["sources"]
            ),
            "attempts": state["attempts"] + 1,
            "trace": state["trace"]
            + [{"step": "Generate", "detail": "Regeneration" if retry else "Nebius synthesis"}],
        }

    def verify(state):
        check = checker(state["answer"], state["sources"])
        event(
            "generation.verified",
            attempt=state["attempts"],
            passed=check["passed"],
            checked_numbers=check.get("checked_numbers", 0),
            issues=len(check.get("issues", [])),
        )
        return {
            "verification": check,
            "trace": state["trace"]
            + [
                {
                    "step": "Verify",
                    "detail": "Literal numeric support passed"
                    if check["passed"]
                    else "Unsupported cited number",
                }
            ],
        }

    def refuse(state):
        return {"answer": "I don't have enough evidence to answer this question."}

    def route(state):
        if state["verification"]["passed"]:
            return END
        return "generate" if state["attempts"] < 2 else "refuse"

    graph = StateGraph(State)
    graph.add_node("generate", generate)
    graph.add_node("verify", verify)
    graph.add_node("refuse", refuse)
    graph.add_edge(START, "generate")
    graph.add_edge("generate", "verify")
    graph.add_conditional_edges("verify", route, ["generate", "refuse", END])
    graph.add_edge("refuse", END)
    return graph.compile().invoke(
        {"question": question, "evidence": evidence, "sources": sources, "attempts": 0, "trace": []}
    )
