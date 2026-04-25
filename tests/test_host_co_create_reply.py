from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ainovel_py.bootstrap.config import Config, ProviderConfig
from ainovel_py.host.host import Host


class HostCoCreateReplyTest(unittest.TestCase):
    def _host(self) -> Host:
        host = Host.__new__(Host)
        host.cfg = Config(
            output_dir="output/test_host",
            provider="openrouter",
            model="qwen3.5-flash",
            providers={"openrouter": ProviderConfig(api_key="test-key", base_url="https://example.com/v1")},
            style="default",
            context_window=128000,
        )
        return host

    def test_co_create_reply_parses_fenced_json(self) -> None:
        host = self._host()
        with patch("ainovel_py.assets.load_bundle", return_value=SimpleNamespace(prompts={})), patch(
            "ainovel_py.agents.llm_client.OpenAICompatClient.complete_stream",
            return_value='```json\n{"message":"ok","prompt":"p","ready":true}\n```',
        ):
            result = host.co_create_reply([{"role": "user", "content": "测试"}])

        self.assertEqual(result["message"], "ok")
        self.assertEqual(result["prompt"], "p")
        self.assertTrue(result["ready"])

    def test_co_create_reply_parses_json_with_surrounding_text(self) -> None:
        host = self._host()
        with patch("ainovel_py.assets.load_bundle", return_value=SimpleNamespace(prompts={})), patch(
            "ainovel_py.agents.llm_client.OpenAICompatClient.complete_stream",
            return_value='result: {"message":"ok","prompt":"p","ready":true}',
        ):
            result = host.co_create_reply([{"role": "user", "content": "测试"}])

        self.assertEqual(result["message"], "ok")
        self.assertEqual(result["prompt"], "p")
        self.assertTrue(result["ready"])

    def test_co_create_reply_falls_back_to_plain_text_message(self) -> None:
        host = self._host()
        with patch("ainovel_py.assets.load_bundle", return_value=SimpleNamespace(prompts={})), patch(
            "ainovel_py.agents.llm_client.OpenAICompatClient.complete_stream",
            return_value='请先补充故事设定，我再继续写第一章。',
        ):
            result = host.co_create_reply([{"role": "user", "content": "测试"}])

        self.assertEqual(result["message"], '请先补充故事设定，我再继续写第一章。')
        self.assertEqual(result["prompt"], "")
        self.assertFalse(result["ready"])

    def test_co_create_reply_uses_non_stream_when_stream_is_empty(self) -> None:
        host = self._host()
        with patch("ainovel_py.assets.load_bundle", return_value=SimpleNamespace(prompts={})), patch(
            "ainovel_py.agents.llm_client.OpenAICompatClient.complete_stream",
            return_value='',
        ), patch(
            "ainovel_py.agents.llm_client.OpenAICompatClient.complete",
            return_value='{"message":"ok","prompt":"p","ready":true}',
        ):
            result = host.co_create_reply([{"role": "user", "content": "测试"}])

        self.assertEqual(result["message"], 'ok')
        self.assertEqual(result["prompt"], "p")
        self.assertTrue(result["ready"])


if __name__ == "__main__":
    unittest.main()
