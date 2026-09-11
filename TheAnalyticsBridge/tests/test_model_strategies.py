import os
import unittest
from unittest.mock import Mock, patch

from integrations.model_strategies import create_chat_model
from integrations.llm_scorer import DangerScoreResponse


class ModelStrategyTests(unittest.TestCase):
    def test_gemini_preserves_existing_settings(self):
        with (
            patch("integrations.model_strategies.ChatGoogleGenerativeAI") as gemini,
            patch("integrations.model_strategies.ChatOllama") as local,
        ):
            model = create_chat_model({"LLM_MODEL_TYPE": "gemini", "LLM_MODEL": "test-model"})
        self.assertIs(model, gemini.return_value)
        gemini.assert_called_once_with(model="test-model", temperature=0, timeout=None)
        local.assert_not_called()

    def test_local_needs_no_gemini_configuration(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("integrations.model_strategies.ChatGoogleGenerativeAI") as gemini,
            patch("integrations.model_strategies.ChatOllama") as local,
        ):
            model = create_chat_model({"LLM_MODEL_TYPE": " LOCAL ", "LLM_MODEL": "local-test-model"})
        self.assertIs(model, local.return_value)
        local.assert_called_once_with(
            model="local-test-model", temperature=0,
            format=DangerScoreResponse.model_json_schema(),
        )
        schema = local.call_args.kwargs["format"]
        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["required"], ["danger_score"])
        self.assertEqual(schema["properties"]["danger_score"]["minimum"], 1)
        self.assertEqual(schema["properties"]["danger_score"]["maximum"], 100)
        gemini.assert_not_called()

    def test_unknown_type_is_rejected_before_client_creation(self):
        with (
            patch("integrations.model_strategies.ChatGoogleGenerativeAI") as gemini,
            patch("integrations.model_strategies.ChatOllama") as local,
        ):
            for model_type in ("", "other"):
                with self.subTest(model_type=model_type), self.assertRaises(ValueError):
                    create_chat_model({"LLM_MODEL_TYPE": model_type})
        gemini.assert_not_called()
        local.assert_not_called()

    def test_model_type_is_required(self):
        with self.assertRaises(KeyError):
            create_chat_model({})

    def test_strategy_can_be_replaced_without_inheritance(self):
        strategy = Mock()
        configuration = {"LLM_MODEL_TYPE": "local"}
        with patch.dict("integrations.model_strategies.MODEL_STRATEGIES", {"local": strategy}):
            self.assertIs(create_chat_model(configuration), strategy.create_model.return_value)
        strategy.create_model.assert_called_once_with(configuration)


if __name__ == "__main__":
    unittest.main()