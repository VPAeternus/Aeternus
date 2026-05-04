from langchain_core.messages import AIMessage

from tradingagents.graph.conditional_logic import ConditionalLogic


def _state_with_messages(messages):
    return {"messages": messages}


def test_should_continue_market_routes_to_tools_under_iteration_cap():
    logic = ConditionalLogic(max_tool_iterations_per_analyst=3)
    state = _state_with_messages(
        [
            AIMessage(
                content="call tool",
                tool_calls=[{"name": "get_stock_data", "args": {}, "id": "1"}],
            )
        ]
    )
    assert logic.should_continue_market(state) == "tools_market"


def test_should_continue_market_clears_when_iteration_cap_hit():
    logic = ConditionalLogic(max_tool_iterations_per_analyst=2)
    state = _state_with_messages(
        [
            AIMessage(
                content="call tool 1",
                tool_calls=[{"name": "get_stock_data", "args": {}, "id": "1"}],
            ),
            AIMessage(
                content="call tool 2",
                tool_calls=[{"name": "get_indicators", "args": {}, "id": "2"}],
            ),
        ]
    )
    assert logic.should_continue_market(state) == "Msg Clear Market"


def test_should_continue_news_clears_when_last_message_has_no_tool_calls():
    logic = ConditionalLogic(max_tool_iterations_per_analyst=4)
    state = _state_with_messages([AIMessage(content="final report", tool_calls=[])])
    assert logic.should_continue_news(state) == "Msg Clear News"

