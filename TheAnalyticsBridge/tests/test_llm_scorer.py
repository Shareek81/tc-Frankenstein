import asyncio
import json
import unittest
from datetime import datetime, time
from unittest.mock import AsyncMock, patch

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage

from integrations import LlmScorer
from models import AttackLog, ILog, LegacyLog


def assessment_json(score=60, **overrides):
    return json.dumps({
        "danger_score": score,
        "insight": ["The log records an authentication event.", "The event alone does not confirm compromise."],
        "respondsuggested": ["Review related authentication logs.", "Verify the account's recent activity."],
        **overrides,
    })


class LlmScorerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = AttackLog(time(14, 30), "Brute Force", 8, "103.25.12.45")

    async def test_chain_parses_valid_scores_including_boundaries(self):
        for response, expected in ((assessment_json(1), 1), (assessment_json(100), 100), (' ' + assessment_json(80) + '\n', 80), ('```json\n' + assessment_json(60) + '\n```', 60)):
            with self.subTest(response=response):
                scorer = LlmScorer(FakeListChatModel(responses=[response]))
                result = await scorer.score(self.log)
                self.assertEqual(result.danger_score, expected)
                self.assertEqual(result.insight, tuple(json.loads(assessment_json())["insight"]))
                self.assertEqual(result.respondsuggested, tuple(json.loads(assessment_json())["respondsuggested"]))
                self.assertEqual(scorer.name, "llm")

    async def test_chain_rejects_non_integer_or_out_of_range_output(self):
        for response in ("80", "Score: 80", "", "true", "null", '"80"', "[80]", '{"score": 80}', '{"danger_score": 0}', '{"danger_score": 101}', '{"danger_score": -1}', '{"danger_score": 80.0}', '{"danger_score": "80"}', '{"danger_score": true}', '{"danger_score": null}', '{"danger_score": 80, "reason": "extra"}'):
            with self.subTest(response=response):
                scorer = LlmScorer(FakeListChatModel(responses=[response]))
                with self.assertRaises(OutputParserException):
                    await scorer.score(self.log)

    async def test_assessment_requires_exactly_two_nonblank_strings_per_array(self):
        for field in ("insight", "respondsuggested"):
            for points in (None, "text", [], ["one"], ["one", "two", "three"], ["", "two"], ["  ", "two"], [1, "two"], ["x" * 401, "two"]):
                with self.subTest(field=field, points=points):
                    scorer = LlmScorer(FakeListChatModel(responses=[assessment_json(**{field: points})]))
                    with self.assertRaises(OutputParserException):
                        await scorer.score(self.log)

    async def test_score_validation_is_preserved_with_insights_present(self):
        for score in (0, 101, -1, 80.0, "80", True, None):
            with self.subTest(score=score):
                scorer = LlmScorer(FakeListChatModel(responses=[assessment_json(score)]))
                with self.assertRaises(OutputParserException):
                    await scorer.score(self.log)

    async def test_both_log_schemas_are_serialized_into_human_message(self):
        for log in (self.log, LegacyLog(datetime(2026, 9, 12), "45.33.22.11", "SSH Connection", "Failed")):
            with self.subTest(log_type=type(log).__name__):
                model = FakeListChatModel(responses=[assessment_json()])
                with patch.object(FakeListChatModel, "ainvoke", new=AsyncMock(return_value=AIMessage(content=assessment_json()))) as invoke:
                    scorer = LlmScorer(model)
                    self.assertEqual((await scorer.score(log)).danger_score, 60)
                messages = invoke.call_args.args[0].to_messages()
                self.assertEqual(messages[0].type, "system")
                self.assertIn("untrusted data", messages[0].content)
                payload = json.loads(messages[1].content.split("\n", 1)[1])
                self.assertEqual(payload["log_type"], type(log).__name__)
                self.assertEqual(payload["log"].get("severity", payload["log"].get("status")), 8 if isinstance(log, AttackLog) else "Failed")

    async def test_non_dataclass_log_uses_serialization_contract(self):
        class CustomLog(ILog):
            def to_payload(self) -> dict[str, object]:
                return {"event": "custom activity", "status": "failed"}

            @classmethod
            def from_json(cls, payload):
                return cls()

        log = CustomLog()
        with patch.object(FakeListChatModel, "ainvoke", new=AsyncMock(return_value=AIMessage(content=assessment_json()))) as invoke:
            scorer = LlmScorer(FakeListChatModel(responses=[assessment_json()]))
            self.assertEqual((await scorer.score(log)).danger_score, 60)
        message = invoke.call_args.args[0].to_messages()[1].content
        payload = json.loads(message.split("\n", 1)[1])
        self.assertEqual(payload, {"log_type": "CustomLog", "log": log.to_payload()})

    async def test_pending_request_has_no_scorer_deadline_and_can_be_cancelled(self):
        scorer = LlmScorer(FakeListChatModel(responses=["80"]))
        started = asyncio.Event()

        async def wait_forever(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()

        with patch.object(FakeListChatModel, "ainvoke", new=wait_forever):
            with patch("asyncio.wait_for", side_effect=AssertionError("Unexpected scorer deadline")):
                task = asyncio.create_task(scorer.score(self.log))
                try:
                    async with asyncio.timeout(2):
                        await started.wait()
                    self.assertFalse(task.done())
                finally:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task

    async def test_provider_errors_propagate_without_fallback(self):
        scorer = LlmScorer(FakeListChatModel(responses=["80"]))
        with patch.object(FakeListChatModel, "ainvoke", new=AsyncMock(side_effect=RuntimeError("provider failed"))):
            with self.assertRaises(RuntimeError):
                await scorer.score(self.log)

    async def test_cancellation_propagates(self):
        scorer = LlmScorer(FakeListChatModel(responses=["80"]))
        with patch.object(FakeListChatModel, "ainvoke", new=AsyncMock(side_effect=asyncio.CancelledError())):
            with self.assertRaises(asyncio.CancelledError):
                await scorer.score(self.log)

if __name__ == "__main__":
    unittest.main()