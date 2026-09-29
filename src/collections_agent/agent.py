"""LiveKit Agents entrypoint (Phase 3: tools + full conversation flow).

Pipeline (LiveKit Inference, PRD §4 / Option A):
  STT  -> Deepgram   (inference.STT)
  LLM  -> OpenAI      (inference.LLM)
  TTS  -> Cartesia    (inference.TTS)
  VAD  -> Silero      (local, free)
  Turn -> LiveKit turn detector (inference.TurnDetector, adaptive interruptions)

The six PRD §6 tools are @function_tool methods on CollectionsAgent. They keep
per-call state (customer id, verified flag, call id) on the agent, delegate the
real work to the pure functions in tools.py, and record every call to the
transcript (PRD §9). end_call writes the final calls row and hangs up.

Run it:
  uv run python src/collections_agent/agent.py console   # talk in terminal
  uv run python src/collections_agent/agent.py dev       # connect to Cloud + Agent Console
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from datetime import date, datetime
from pathlib import Path

# Allow `python src/collections_agent/agent.py <cmd>` (script invocation) to
# import the package, in addition to `python -m collections_agent.agent`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402
from livekit import api  # noqa: E402
from livekit.agents import (  # noqa: E402
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    RunContext,
    TurnHandlingOptions,
    cli,
    function_tool,
    get_job_context,
    inference,
)
from livekit.plugins import silero  # noqa: E402

from collections_agent import tools  # noqa: E402
from collections_agent.config import get_settings  # noqa: E402
from collections_agent.db import get_connection  # noqa: E402
from collections_agent.models import CallState  # noqa: E402
from collections_agent.prompts import build_agent_instructions  # noqa: E402
from collections_agent.transcript import TranscriptRecorder  # noqa: E402

logger = logging.getLogger("collections-agent")

# Load LIVEKIT_URL / API key / secret and model settings from .env.
load_dotenv(".env")

settings = get_settings()


class CollectionsAgent(Agent):
    """Collections agent with the full PRD §5 flow and §6 tools."""

    def __init__(
        self,
        *,
        state: CallState,
        recorder: TranscriptRecorder,
        db_path: str,
    ) -> None:
        super().__init__(
            llm=inference.LLM(model=settings.llm_model),
            instructions=build_agent_instructions(settings.company_name),
        )
        self.state = state
        self.recorder = recorder
        self.db_path = db_path

    # -- helpers ------------------------------------------------------------

    def _run(self, fn, /, **kwargs) -> dict:
        """Open a short-lived connection, run a tools.py function, close it."""
        conn = get_connection(self.db_path)
        try:
            return fn(conn, **kwargs)
        finally:
            conn.close()

    # -- tools (PRD §6) -----------------------------------------------------

    @function_tool()
    async def get_customer_context(self, context: RunContext) -> dict:
        """Load the customer on this call and their open invoices.

        Call this first, before greeting, to get the contact's name. Do not
        speak any amounts or invoice numbers from the result until identity is
        verified.
        """
        result = self._run(
            tools.get_customer_context,
            customer_id=self.state.customer_id,
            today=date.today(),
        )
        self.recorder.add_tool_call("get_customer_context", {}, result)
        return result

    @function_tool()
    async def verify_identity(self, context: RunContext, confirmed: bool) -> dict:
        """Record whether the caller confirmed they are the named contact.

        Call this immediately after the caller answers the identity question.

        Args:
            confirmed: True if the caller confirmed they are the contact.
        """
        self.state.verified = bool(confirmed)
        result = {"verified": self.state.verified}
        self.recorder.add_tool_call(
            "verify_identity", {"confirmed": bool(confirmed)}, result
        )
        return result

    @function_tool()
    async def log_promise_to_pay(
        self,
        context: RunContext,
        invoice_id: str,
        promised_date: str,
        amount: int | None = None,
    ) -> dict:
        """Record a promise to pay. Only call after reading the amount and date
        back to the caller and getting a clear yes.

        Args:
            invoice_id: The invoice, for example INV-4217.
            promised_date: The promised payment date as an ISO date,
                YYYY-MM-DD.
            amount: Amount in whole rupees. Omit for the full balance.
        """
        if not self.state.verified:
            return {"error": "Identity is not verified yet. Verify the contact first."}
        result = self._run(
            tools.log_promise_to_pay,
            call_id=self.state.call_id,
            invoice_id=invoice_id,
            promised_date_iso=promised_date,
            amount=amount,
            today=date.today(),
        )
        self.recorder.add_tool_call(
            "log_promise_to_pay",
            {"invoice_id": invoice_id, "promised_date": promised_date, "amount": amount},
            result,
        )
        return result

    @function_tool()
    async def flag_dispute(
        self,
        context: RunContext,
        invoice_id: str,
        dispute_type: str,
        details: str,
    ) -> dict:
        """Record a dispute or an already-paid claim and put the invoice under
        review.

        Args:
            invoice_id: The invoice, for example INV-4217.
            dispute_type: ALREADY_PAID or DISPUTE.
            details: For ALREADY_PAID, the payment date and reference. For
                DISPUTE, the reason the caller gives.
        """
        if not self.state.verified:
            return {"error": "Identity is not verified yet. Verify the contact first."}
        result = self._run(
            tools.flag_dispute,
            call_id=self.state.call_id,
            invoice_id=invoice_id,
            dispute_type=dispute_type,
            details=details,
        )
        self.recorder.add_tool_call(
            "flag_dispute",
            {"invoice_id": invoice_id, "dispute_type": dispute_type, "details": details},
            result,
        )
        return result

    @function_tool()
    async def escalate_to_human(
        self,
        context: RunContext,
        reason: str,
        preferred_callback_time: str | None = None,
    ) -> dict:
        """Escalate the call to a human agent and record a callback.

        Args:
            reason: Why the call is being escalated.
            preferred_callback_time: Optional free text, e.g. "tomorrow morning".
        """
        result = self._run(
            tools.escalate_to_human,
            call_id=self.state.call_id,
            customer_id=self.state.customer_id,
            reason=reason,
            preferred_callback_time=preferred_callback_time,
        )
        self.recorder.add_tool_call(
            "escalate_to_human",
            {"reason": reason, "preferred_callback_time": preferred_callback_time},
            result,
        )
        return result

    @function_tool()
    async def end_call(self, context: RunContext, outcome: str, summary: str) -> dict:
        """End the call. Call exactly once, at the very end, after summarising
        what happens next.

        Args:
            outcome: One of PROMISE_TO_PAY, ALREADY_PAID, DISPUTE, ESCALATED,
                WRONG_CONTACT, NO_RESOLUTION.
            summary: A one or two sentence summary of the call.
        """
        if self.state.outcome_logged:
            return {"error": "The call outcome has already been logged."}

        transcript_path = f"{settings.logs_dir}/{self.state.call_id}.transcript.json"
        result = self._run(
            tools.finalize_call,
            call_id=self.state.call_id,
            customer_id=self.state.customer_id,
            started_at=self.state.started_at,
            ended_at=datetime.now().isoformat(timespec="seconds"),
            outcome=outcome,
            summary=summary,
            transcript_path=transcript_path,
        )
        if "error" in result:
            return result

        self.state.outcome_logged = True
        self.recorder.add_tool_call(
            "end_call", {"outcome": outcome, "summary": summary}, result
        )
        self.recorder.dump(transcript_path)

        # Let the closing line finish, then hang up the room.
        asyncio.create_task(_hang_up(context))
        return result


async def _hang_up(context: RunContext) -> None:
    """Wait for the final speech to play, then delete the room to end the call."""
    try:
        await context.wait_for_playout()
    except Exception:  # noqa: BLE001 - best-effort in console mode
        pass
    try:
        job_ctx = get_job_context()
        await job_ctx.api.room.delete_room(
            api.DeleteRoomRequest(room=job_ctx.room.name)
        )
    except Exception as exc:  # noqa: BLE001 - no real room in console mode
        logger.info("Could not delete room (expected in console mode): %s", exc)


server = AgentServer()


@server.rtc_session(agent_name=settings.agent_name)
async def entrypoint(ctx: JobContext) -> None:
    ctx.log_context_fields = {"room": ctx.room.name}

    call_id = f"call-{uuid.uuid4().hex[:12]}"
    state = CallState(
        customer_id=settings.customer_id,
        call_id=call_id,
        started_at=datetime.now().isoformat(timespec="seconds"),
    )
    recorder = TranscriptRecorder(call_id=call_id, customer_id=state.customer_id)
    agent = CollectionsAgent(state=state, recorder=recorder, db_path=settings.db_path)

    # Cartesia TTS: pass the voice id only if one is configured.
    tts_kwargs = {"model": settings.tts_model, "language": "en"}
    if settings.tts_voice:
        tts_kwargs["voice"] = settings.tts_voice

    session = AgentSession(
        stt=inference.STT(model=settings.stt_model, language="en"),
        tts=inference.TTS(**tts_kwargs),
        vad=silero.VAD.load(),
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
            interruption={"mode": "adaptive"},
            preemptive_generation={"enabled": True},
        ),
    )

    # Record every finalized conversation turn for the transcript (§9).
    @session.on("conversation_item_added")
    def _on_item(event) -> None:  # noqa: ANN001 - event type is internal
        item = event.item
        text = getattr(item, "text_content", None)
        if not text:
            return
        role = getattr(item, "role", None)
        speaker = "customer" if role == "user" else "agent"
        recorder.add_message(
            speaker, text, interrupted=bool(getattr(item, "interrupted", False))
        )

    # If the call ends without end_call (e.g. caller hangs up), log NO_RESOLUTION
    # so every call has exactly one outcome (§5.1).
    async def _on_shutdown() -> None:
        if state.outcome_logged:
            return
        transcript_path = f"{settings.logs_dir}/{call_id}.transcript.json"
        conn = get_connection(settings.db_path)
        try:
            tools.finalize_call(
                conn,
                call_id=call_id,
                customer_id=state.customer_id,
                started_at=state.started_at,
                ended_at=datetime.now().isoformat(timespec="seconds"),
                outcome="NO_RESOLUTION",
                summary="Call ended without a resolution.",
                transcript_path=transcript_path,
            )
        finally:
            conn.close()
        state.outcome_logged = True
        recorder.dump(transcript_path)

    ctx.add_shutdown_callback(_on_shutdown)

    await session.start(agent=agent, room=ctx.room)
    await ctx.connect()

    # The agent speaks first: load context, then greet + disclosure + identity.
    await session.generate_reply(
        instructions=(
            "Start the call. First call get_customer_context to load the "
            "contact, then greet the caller, disclose that you are an automated "
            f"assistant calling on behalf of {settings.company_name}, and ask in "
            "one short question whether you are speaking with the contact by "
            "name. Do not state any amounts or invoice numbers yet."
        )
    )


if __name__ == "__main__":
    cli.run_app(server)
