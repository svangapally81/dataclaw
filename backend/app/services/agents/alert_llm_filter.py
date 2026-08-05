from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI, OpenAIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Agent, Alert
from app.services.settings_store import resolve_openai


async def should_alert(session: AsyncSession, agent: Agent, signal_payload: dict[str, Any]) -> tuple[bool, str]:
    if not agent.uses_llm_filter:
        return True, "LLM filter disabled."
    api_key, model, base_url, _embedding_model = await resolve_openai(session)
    if not api_key:
        return True, "No LLM provider configured; kept alert."

    recent_alerts = list(
        (
            await session.scalars(
                select(Alert)
                .where(Alert.workspace_id == agent.workspace_id, Alert.resolved.is_(False))
                .order_by(Alert.created_at.desc())
                .limit(10)
            )
        ).all()
    )
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    try:
        completion = await client.chat.completions.create(
            model=model or "gpt-4.1-mini",
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": agent.system_prompt
                    or "Decide whether a monitoring signal should create a new alert. Return JSON.",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "signal": signal_payload,
                            "recent_alerts": [
                                {"title": alert.title, "detail": alert.detail, "severity": alert.severity}
                                for alert in recent_alerts
                            ],
                            "response_schema": {"keep": "boolean", "rationale": "string"},
                        },
                        default=str,
                    ),
                },
            ],
        )
    except OpenAIError as exc:
        return True, f"LLM filter failed ({exc.__class__.__name__}); kept alert."

    content = completion.choices[0].message.content or "{}"
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return True, "LLM filter returned non-JSON; kept alert."
    return bool(parsed.get("keep", True)), str(parsed.get("rationale") or "No rationale returned.")
