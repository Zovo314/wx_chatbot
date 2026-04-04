from openai import AsyncOpenAI

from app.models import AIConfig


def get_client(config: AIConfig) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
    )


async def chat_completion(
    config: AIConfig,
    messages: list[dict],
) -> str:
    client = get_client(config)
    resp = await client.chat.completions.create(
        model=config.model,
        messages=messages,
    )
    return resp.choices[0].message.content or ""
