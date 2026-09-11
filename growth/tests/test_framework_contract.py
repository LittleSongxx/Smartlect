"""F0 dependency contract only: no model, database or commerce service calls."""

from collections.abc import AsyncIterable
import json
from typing import TypedDict
import unittest

import httpx
from fastapi import FastAPI
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field
import uvicorn


class Payload(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    count: int = Field(ge=0, le=2)


class State(TypedDict):
    count: int


class FrameworkContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_validated_bounded_graph_and_native_sse(self):
        builder = StateGraph(State)
        builder.add_node("advance", lambda state: {"count": state["count"] + 1})
        builder.add_edge(START, "advance")
        builder.add_conditional_edges(
            "advance", lambda state: END if state["count"] >= 2 else "advance"
        )
        graph = builder.compile()
        self.assertEqual(graph.invoke({"count": 0}, {"recursion_limit": 3}), {"count": 2})
        with self.assertRaises(GraphRecursionError):
            graph.invoke({"count": 0}, {"recursion_limit": 1})

        app = FastAPI()

        @app.post("/events", response_class=EventSourceResponse)
        async def events(payload: Payload) -> AsyncIterable[ServerSentEvent]:
            result = await graph.ainvoke(payload.model_dump(), {"recursion_limit": 3})
            yield ServerSentEvent(data=result, event="completed", id="1")

        server_config = uvicorn.Config(app, loop="asyncio", http="h11", ws="none", log_config=None)
        server_config.load()
        self.assertTrue(callable(server_config.loaded_app))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),
                                     base_url="http://smartlect.test") as client:
            response = await client.post("/events", json={"count": 0})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
            data = next(line[6:] for line in response.text.splitlines() if line.startswith("data: "))
            self.assertEqual(json.loads(data), {"count": 2})
            self.assertIn("event: completed", response.text)
            self.assertIn("id: 1", response.text)
            for payload in ({"count": "0"}, {"count": False}, {"count": -1},
                            {"count": 0, "extra": "rejected"}):
                self.assertEqual((await client.post("/events", json=payload)).status_code, 422)


if __name__ == "__main__":
    unittest.main()
