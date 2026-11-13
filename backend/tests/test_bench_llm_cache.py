from pydantic import BaseModel

from evals.bench.llm_cache import CachingChatModel


class FakeSchema(BaseModel):
    value: str


class FakeStructuredRunnable:
    def __init__(self, queue):
        self.queue = queue
        self.calls = 0

    def invoke(self, prompt):
        self.calls += 1
        return self.queue.pop(0)


class FakeInnerModel:
    def __init__(self, queue):
        self.runnable = FakeStructuredRunnable(queue)

    def with_structured_output(self, schema):
        return self.runnable


def test_cache_miss_calls_inner_model_and_caches(tmp_path):
    inner = FakeInnerModel([FakeSchema(value="first")])
    model = CachingChatModel(inner, tmp_path, case_id="case1", mode="full", model_name="gpt-x")

    result = model.with_structured_output(FakeSchema).invoke("some prompt")

    assert result.value == "first"
    assert inner.runnable.calls == 1
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_cache_hit_does_not_call_inner_model_again(tmp_path):
    inner = FakeInnerModel([FakeSchema(value="first"), FakeSchema(value="should-not-be-used")])
    model = CachingChatModel(inner, tmp_path, case_id="case1", mode="full", model_name="gpt-x")

    first = model.with_structured_output(FakeSchema).invoke("some prompt")
    second = model.with_structured_output(FakeSchema).invoke("some prompt")

    assert first.value == second.value == "first"
    assert inner.runnable.calls == 1  # second call was served from cache


def test_different_case_id_gets_a_different_cache_entry(tmp_path):
    inner = FakeInnerModel([FakeSchema(value="a"), FakeSchema(value="b")])
    model_1 = CachingChatModel(inner, tmp_path, case_id="case1", mode="full", model_name="gpt-x")
    model_2 = CachingChatModel(inner, tmp_path, case_id="case2", mode="full", model_name="gpt-x")

    result_1 = model_1.with_structured_output(FakeSchema).invoke("same prompt")
    result_2 = model_2.with_structured_output(FakeSchema).invoke("same prompt")

    assert result_1.value == "a"
    assert result_2.value == "b"
    assert inner.runnable.calls == 2


def test_different_prompt_gets_a_different_cache_entry(tmp_path):
    inner = FakeInnerModel([FakeSchema(value="a"), FakeSchema(value="b")])
    model = CachingChatModel(inner, tmp_path, case_id="case1", mode="full", model_name="gpt-x")

    result_1 = model.with_structured_output(FakeSchema).invoke("prompt one")
    result_2 = model.with_structured_output(FakeSchema).invoke("prompt two")

    assert result_1.value == "a"
    assert result_2.value == "b"
    assert inner.runnable.calls == 2


def test_different_mode_gets_a_different_cache_entry(tmp_path):
    inner = FakeInnerModel([FakeSchema(value="a"), FakeSchema(value="b")])
    model_full = CachingChatModel(inner, tmp_path, case_id="case1", mode="full", model_name="gpt-x")
    model_diff_only = CachingChatModel(inner, tmp_path, case_id="case1", mode="diff_only", model_name="gpt-x")

    result_1 = model_full.with_structured_output(FakeSchema).invoke("same prompt")
    result_2 = model_diff_only.with_structured_output(FakeSchema).invoke("same prompt")

    assert result_1.value == "a"
    assert result_2.value == "b"
    assert inner.runnable.calls == 2
