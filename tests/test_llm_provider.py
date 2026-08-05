import unittest

from ai_content_pipeline.config import Settings
from ai_content_pipeline.generation.llm import (
    DeepSeekLLMClient,
    MockLLM,
    QwenLLMClient,
    create_llm,
)


class LLMProviderTests(unittest.TestCase):
    def test_deepseek_selected_by_default_with_key(self):
        settings = Settings(llm_provider="deepseek", deepseek_api_key="sk-test")
        self.assertIsInstance(create_llm(settings), DeepSeekLLMClient)

    def test_qwen_selected_when_provider_qwen(self):
        settings = Settings(llm_provider="qwen", qwen_api_key="sk-test")
        self.assertIsInstance(create_llm(settings), QwenLLMClient)

    def test_fallback_to_qwen_when_only_qwen_key(self):
        settings = Settings(llm_provider="deepseek", qwen_api_key="sk-test")
        self.assertIsInstance(create_llm(settings), QwenLLMClient)

    def test_mock_when_no_key(self):
        settings = Settings(llm_provider="deepseek")
        self.assertIsInstance(create_llm(settings), MockLLM)

    def test_deepseek_client_http_shape(self):
        settings = Settings(deepseek_api_key="sk-test", deepseek_model="deepseek-chat")
        client = DeepSeekLLMClient(settings)
        self.assertEqual(client.base_url, "https://api.deepseek.com")
        self.assertEqual(client.model, "deepseek-chat")
        self.assertEqual(client.provider, "deepseek")


if __name__ == "__main__":
    unittest.main()

