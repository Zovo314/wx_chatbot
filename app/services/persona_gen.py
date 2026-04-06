"""人格生成服务：调用 AI 生成 memory + persona，拼装 system_prompt。

支持任意关系类型的人物复刻：朋友、家人、同事、前任、暧昧对象、偶像、虚构角色等。
"""

from pathlib import Path

from app.models import AIConfig
from app.services.ai_client import chat_completion

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


def _read_prompt(name: str) -> str:
    p = PROMPTS_DIR / name
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


RUNNING_RULES_TEMPLATE = """## 运行规则

1. 你是{name}，不是 AI 助手。用ta的方式说话，用ta的逻辑思考
2. 先由人物性格判断：ta会怎么回应这个话题？什么态度？
3. 再由关系记忆补充：结合你们的共同记忆，让回应更真实
4. 始终保持表达风格，包括口头禅、语气词、标点习惯
5. **只输出对话文本**，禁止任何旁白、括号描写、场景描述、动作描写（如"（叹气）""（沉默）""（消息提示音响起）"）。像真人发微信一样，只发文字消息
6. 硬规则优先级最高：
   - 不说ta在现实中绝不可能说的话
   - 不突然变得完美或无条件包容（除非ta本来就这样）
   - 保持ta的"棱角"——正是这些不完美让ta真实
   - 如果被问到"你爱不爱我"这类问题，用ta会用的方式回答，而不是用户想听的答案
"""


async def generate_memory(
    config: AIConfig,
    name: str,
    basic_info: str,
    personality: str,
    raw_material: str,
) -> str:
    memory_analyzer = _read_prompt("memory_analyzer.md")
    memory_builder = _read_prompt("memory_builder.md")

    system = f"""你是一个人物记忆分析专家。根据提供的原材料，生成 Person Memory 文档。目标人物可以是任何关系类型（朋友、家人、同事、前任、暧昧对象、偶像、虚构角色等）。

{memory_analyzer}

---

请按以下模板输出：

{memory_builder}"""

    user_msg = f"""## 基本信息
- 代号：{name}
- 基本情况：{basic_info}
- 性格画像：{personality}

## 原材料
{raw_material if raw_material else "（无额外原材料，仅凭以上信息生成）"}"""

    return await chat_completion(config, [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ])


async def generate_persona(
    config: AIConfig,
    name: str,
    basic_info: str,
    personality: str,
    raw_material: str,
) -> str:
    persona_analyzer = _read_prompt("persona_analyzer.md")
    persona_builder = _read_prompt("persona_builder.md")

    system = f"""你是一个性格行为分析专家。根据提供的原材料，生成 5 层 Persona 结构文档。

{persona_analyzer}

---

请按以下模板输出：

{persona_builder}"""

    user_msg = f"""## 基本信息
- 代号：{name}
- 基本情况：{basic_info}
- 性格画像：{personality}

## 原材料
{raw_material if raw_material else "（无额外原材料，仅凭以上信息生成）"}"""

    return await chat_completion(config, [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ])


def build_system_prompt(name: str, memory: str, persona: str) -> str:
    rules = RUNNING_RULES_TEMPLATE.replace("{name}", name)
    return f"""# {name}

{rules}

---

## 人物记忆

{memory}

---

## 人物性格

{persona}"""
