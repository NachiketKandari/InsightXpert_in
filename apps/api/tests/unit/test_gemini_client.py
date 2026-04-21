from unittest.mock import MagicMock, patch

from insightxpert_api.llm.gemini import GeminiLLM


@patch("insightxpert_api.llm.gemini.genai.Client")
def test_generate_returns_text(mock_client_cls):
    instance = mock_client_cls.return_value
    instance.models.generate_content.return_value = MagicMock(text="SELECT 1")
    llm = GeminiLLM(api_key="k", model="gemini-2.5-flash")
    assert llm.generate("hi") == "SELECT 1"
    instance.models.generate_content.assert_called_once()


@patch("insightxpert_api.llm.gemini.genai.Client")
def test_generate_handles_empty_text(mock_client_cls):
    instance = mock_client_cls.return_value
    instance.models.generate_content.return_value = MagicMock(text=None)
    llm = GeminiLLM(api_key="k", model="m")
    assert llm.generate("hi") == ""


@patch("insightxpert_api.llm.gemini.genai.Client")
def test_embed_returns_list_of_floats(mock_client_cls):
    instance = mock_client_cls.return_value
    instance.models.embed_content.return_value = MagicMock(
        embeddings=[MagicMock(values=[0.1, 0.2, 0.3])]
    )
    llm = GeminiLLM(api_key="k")
    assert llm.embed("hello") == [0.1, 0.2, 0.3]
