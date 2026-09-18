"""LangGraph wiring only: nodes stay run-scoped via the ContextVar session."""
from typing import TypedDict

from langgraph.graph import StateGraph, START, END


class RunState(TypedDict):
    messages: list[dict]
    response: dict
    result: dict
    repair: int


def route_shopping_model(state):
    calls = state['response'].get('tool_calls') or []
    names = [call['function']['name'] for call in calls]
    if any(name in {'request_handoff', 'finish_answer'} for name in names):
        return 'answer'
    if calls:
        return 'tools'
    return 'answer'


def build_shopping_graph():
    """Compiled once by graph_runtime. Nodes read the current ShoppingSession ContextVar."""
    from smartlect.graph_runtime import shopping_session

    async def model_node(state):
        return await shopping_session.get().model_node(state)

    async def tool_node(state):
        return await shopping_session.get().tool_node(state)

    async def answer_node(state):
        return await shopping_session.get().answer_node(state)

    graph = StateGraph(RunState)
    graph.add_node('model', model_node)
    graph.add_node('tools', tool_node)
    graph.add_node('answer', answer_node)
    graph.add_edge(START, 'model')
    graph.add_conditional_edges('model', route_shopping_model)
    graph.add_conditional_edges('tools', lambda state: END if state.get('result') else 'model')
    graph.add_conditional_edges('answer', lambda state: END if state.get('result') else 'model')
    return graph
