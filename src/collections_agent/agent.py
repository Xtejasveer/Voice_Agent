"""LiveKit Agents entrypoint (Phase 2: greeting-only voice loop).

Pipeline (LiveKit Inference, PRD §4 / Option A):
  STT  -> Deepgram   (inference.STT, e.g. "deepgram/flux-general")
  LLM  -> OpenAI      (inference.LLM,  e.g. "openai/gpt-4o-mini")
  TTS  -> Cartesia    (inference.TTS,  e.g. "cartesia/sonic-3")
  VAD  -> Silero      (local, free)
  Turn -> LiveKit turn detector (inference.TurnDetector, adaptive interruptions)

Run it:
  uv run python src/collections_agent/agent.py download-files   # one-time
  uv run python src/collections_agent/agent.py console          # talk in terminal
  uv run python src/collections_agent/agent.py dev              # connect to Cloud + Agent Console
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Allow `python src/collections_agent/agent.py <cmd>` (script invocation) to
# import the package, in addition to `python -m collections_agent.agent`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402
from livekit.agents import (  # noqa: E402
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    TurnHandlingOptions,
    cli,
    inference,
)
from livekit.plugins import silero  # noqa: E402

from collections_agent.config import get_settings  # noqa: E402
from collections_agent.prompts import build_greeting_instructions  # noqa: E402

logger = logging.getLogger("collections-agent")

# Load LIVEKIT_URL / API key / secret and model settings from .env.
load_dotenv(".env")

settings = get_settings()


class CollectionsAgent(Agent):
    """Greeting-only agent for Phase 2 (no tools yet)."""

    def __init__(self) -> None:
        super().__init__(
            llm=inference.LLM(model=settings.llm_model),
            instructions=build_greeting_instructions(settings.company_name),
        )


server = AgentServer()


@server.rtc_session(agent_name=settings.agent_name)
async def entrypoint(ctx: JobContext) -> None:
    ctx.log_context_fields = {"room": ctx.room.name}

    # Cartesia TTS: pass the voice id only if one is configured.
    tts_kwargs = {"model": settings.tts_model, "language": "en"}
    if settings.tts_voice:
        tts_kwargs["voice"] = settings.tts_voice

    session = AgentSession(
        stt=inference.STT(model=settings.stt_model, language="en"),
        tts=inference.TTS(**tts_kwargs),
        # Local Silero VAD (free); LiveKit turn detector for end-of-turn +
        # adaptive interruptions (backchannels like "mhm" don't cut the agent off).
        vad=silero.VAD.load(),
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
            interruption={"mode": "adaptive"},
            preemptive_generation={"enabled": True},
        ),
    )

    await session.start(agent=CollectionsAgent(), room=ctx.room)
    await ctx.connect()

    # The agent speaks first: greet + disclosure.
    await session.generate_reply(
        instructions=(
            "Greet the customer, disclose that you are an automated assistant "
            f"calling on behalf of {settings.company_name}, and ask in one short "
            "question whether you are speaking with the right person."
        )
    )


if __name__ == "__main__":
    cli.run_app(server)
