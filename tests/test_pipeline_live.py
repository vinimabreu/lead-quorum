"""Live end-to-end test: enrichment (real Gemini) then deterministic scoring.

Skips cleanly when there is no API key, and skips (does not fail) on free-tier 429 so the
suite stays green when quota is exhausted. The assertion is structural, not exact: the LLM
output varies, but the score must always reconcile to its reason.
"""

import asyncio
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

pytestmark = pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"), reason="no GOOGLE_API_KEY in .env"
)

from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from agents.pipeline import build_lead_pipeline  # noqa: E402

APP, USER = "lead_qualifier_live", "u1"


def run_pipeline(raw_notes: str) -> dict:
    async def _run():
        session_service = InMemorySessionService()
        session = await session_service.create_session(app_name=APP, user_id=USER)
        runner = Runner(
            app_name=APP, agent=build_lead_pipeline(), session_service=session_service
        )
        async for _event in runner.run_async(
            user_id=USER,
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=raw_notes)]),
        ):
            pass
        final = await session_service.get_session(
            app_name=APP, user_id=USER, session_id=session.id
        )
        return final.state

    return asyncio.run(_run())


def test_enrichment_to_scoring_end_to_end():
    notes = (
        "Acme Corp, industrial supplier. About 30 employees. They renewed their contract "
        "last year. Main contact is the VP of Operations. Spends around $6,000 per month."
    )
    try:
        state = run_pipeline(notes)
    except Exception as exc:  # noqa: BLE001
        if "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc):
            pytest.skip(f"free-tier quota hit: {exc}")
        raise

    assert state.get("enriched_lead") is not None, "enrichment did not write to state"
    assert state.get("rederived_lead") is not None, "rederive did not write to state"
    result = state.get("score_result")
    assert result is not None, "scoring did not write to state"
    # The whole point: whatever the LLM extracted, the reason reconciles to the score.
    assert sum(part["points"] for part in result["parts"]) == result["raw"]

    verdict = state.get("verdict")
    assert verdict is not None, "corroboration did not write a verdict"
    assert verdict["status"] in {"CONFIRMED", "REVIEW", "EXCLUDED"}
    if verdict["status"] == "EXCLUDED":
        # abstention: no number, and the reason names the flipped rule
        assert verdict["score"] is None
        assert "abstaining" in verdict["reason"]
    else:
        assert verdict["score"] == result["score"]
