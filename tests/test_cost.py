from app.services.llm.base import Usage


def test_zero_usage_is_free():
    assert Usage().cost(0.07, 0.28) == 0.0


def test_cost_uses_separate_in_out_prices():
    # 1M input @ $0.07 + 1M output @ $0.28 = $0.35
    usage = Usage(prompt_tokens=1_000_000, completion_tokens=1_000_000)
    assert round(usage.cost(0.07, 0.28), 6) == 0.35


def test_small_request_is_cheap():
    usage = Usage(prompt_tokens=600, completion_tokens=120)
    cost = usage.cost(0.07, 0.28)
    assert 0 < cost < 0.001
