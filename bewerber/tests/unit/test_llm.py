from pydantic import BaseModel
from bewerber.shared.llm import LLMClient


class DummyOut(BaseModel):
    answer: str
    score: int


def test_structured_call_uses_responses_parse(mocker):
    fake_client = mocker.Mock()
    fake_resp = mocker.Mock()
    fake_resp.output_parsed = DummyOut(answer="hello", score=7)
    fake_client.responses.parse.return_value = fake_resp

    client = LLMClient(client=fake_client, model="gpt-test")
    result = client.structured(
        system="be helpful",
        user="hi",
        schema=DummyOut,
    )
    assert result.answer == "hello"
    assert result.score == 7
    fake_client.responses.parse.assert_called_once()
    call_kwargs = fake_client.responses.parse.call_args.kwargs
    assert call_kwargs["model"] == "gpt-test"
    assert call_kwargs["text_format"] == DummyOut


def test_text_call(mocker):
    fake_client = mocker.Mock()
    fake_resp = mocker.Mock()
    fake_resp.output_text = "plain answer"
    fake_client.responses.create.return_value = fake_resp

    client = LLMClient(client=fake_client, model="gpt-test")
    result = client.text(system="s", user="u")
    assert result == "plain answer"


def test_default_model_from_env(monkeypatch, mocker):
    monkeypatch.setenv("BEWERBER_LLM_MODEL", "gpt-from-env")
    fake_openai = mocker.patch("bewerber.shared.llm.OpenAI")
    client = LLMClient()
    assert client.model == "gpt-from-env"
    fake_openai.assert_called_once()
