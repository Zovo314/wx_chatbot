"""人格生成服务 v2：双 Pipeline + 多 Agent 并行 + 双模式（RICH/LEAN）。

改动要点（相对 persona_gen.py v1）：
1. 按 persona_type 路由到两套 Pipeline：
   - private      → 5 Agent：A 表达 DNA / B 情感模式 / C 关系记忆 / D 决策反模式 / E 内在张力
   - public/fictional → 5 Agent：A 表达 DNA / D 决策反模式 / E 内在张力 / F 思维框架 / G 身份时间线
2. 每个 Agent 独立 prompt 模板，输出严格 JSON（含 evidence_level）
3. 语料充足度判断（RICH >= 2000 字 / LEAN < 2000 字）
4. Synthesizer 由 LLM 合成最终 system_prompt 文本
5. 质量自检 + 合成元数据（写入 meta_json.dimensions / quality_warnings）

调用方式：
    result = await generate_persona_v2(config, payload)
    result = {
        "memory": str,          # 供 DB persona.memory 字段（合成中间产物）
        "persona": str,         # 供 DB persona.persona 字段（合成中间产物）
        "system_prompt": str,   # 供 DB persona.system_prompt 字段
        "dimensions": dict,     # 供 meta_json.dimensions
        "quality_warnings": list,
    }
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models import AIConfig
from app.services.ai_client import chat_completion

# -------- 路径常量 --------
PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"
AGENTS_DIR = PROMPTS_DIR / "agents"

# -------- 常量 --------
RICH_THRESHOLD = 2000  # 字符数阈值
ASK_THRESHOLD = 300    # 信息量严重不足

PRIVATE_AGENTS = [
    ("expression_dna",     "private/A_expression_dna.md"),
    ("emotion_pattern",    "private/B_emotion_pattern.md"),
    ("relationship_memory","private/C_relationship_memory.md"),
    ("decision_anti",      "private/D_decision_anti.md"),
    ("inner_tension",      "private/E_inner_tension.md"),
]

NON_PRIVATE_AGENTS = [
    ("expression_dna",     "non_private/A_expression_dna.md"),
    ("decision_anti",      "non_private/D_decision_anti.md"),
    ("inner_tension",      "non_private/E_inner_tension.md"),
    ("mental_framework",   "non_private/F_mental_framework.md"),
    ("identity_timeline",  "non_private/G_identity_timeline.md"),
]

SYNTH_PRIVATE     = "synthesizer_private.md"
SYNTH_NON_PRIVATE = "synthesizer_non_private.md"


# -------- 数据结构 --------
@dataclass
class PersonaPayload:
    """统一入参结构。"""
    name: str
    persona_type: str                    # "private" / "public" / "fictional"
    basic_info: str = ""
    personality: str = ""
    # private 专属
    relationship_context: str = ""
    # non_private 专属
    domain: str = ""
    works: str = ""
    # 通用
    raw_material: str = ""

    @property
    def is_private(self) -> bool:
        return self.persona_type == "private"

    @property
    def mode(self) -> str:
        """RICH / LEAN / ASK。"""
        if len(self.raw_material.strip()) >= RICH_THRESHOLD:
            return "RICH"
        info_sum = len((self.basic_info + self.personality +
                        self.relationship_context + self.domain +
                        self.works + self.raw_material).strip())
        if info_sum < ASK_THRESHOLD:
            return "ASK"
        return "LEAN"


@dataclass
class AgentResult:
    name: str
    ok: bool
    data: dict = field(default_factory=dict)
    error: str = ""


# -------- 工具函数 --------
def _read_template(relpath: str) -> str:
    p = AGENTS_DIR / relpath if "/" in relpath else PROMPTS_DIR / relpath
    if not p.exists():
        # synthesizer 在 prompts 根
        p = PROMPTS_DIR / relpath
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _fill_template(template: str, payload: PersonaPayload) -> str:
    mapping = {
        "{name}": payload.name,
        "{basic_info}": payload.basic_info or "（未提供）",
        "{personality}": payload.personality or "（未提供）",
        "{relationship_context}": payload.relationship_context or "（未提供）",
        "{domain}": payload.domain or "（未提供）",
        "{works}": payload.works or "（未提供）",
        "{raw_material}": payload.raw_material or "（无语料，LEAN 模式）",
    }
    for k, v in mapping.items():
        template = template.replace(k, v)
    return template


def _parse_json_safely(text: str) -> dict | None:
    """LLM 可能返回带 ``` 包裹的 JSON，尝试剥离。"""
    if not text:
        return None
    text = text.strip()
    # 去掉 ``` 包裹
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试抓取第一个 { ... }
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def _strip_speculated(data: Any) -> Any:
    """递归丢弃 evidence_level == 'speculated' 的条目。"""
    if isinstance(data, dict):
        if data.get("evidence_level") == "speculated":
            return None
        return {k: _strip_speculated(v) for k, v in data.items()
                if _strip_speculated(v) is not None or not isinstance(v, (dict, list))}
    if isinstance(data, list):
        cleaned = [_strip_speculated(x) for x in data]
        return [x for x in cleaned if x is not None]
    return data


# -------- 单 Agent 调用 --------
async def _run_agent(
    config: AIConfig,
    agent_name: str,
    template_path: str,
    payload: PersonaPayload,
) -> AgentResult:
    template = _read_template(template_path)
    if not template:
        return AgentResult(agent_name, False, error=f"模板不存在: {template_path}")

    prompt = _fill_template(template, payload)
    try:
        text = await chat_completion(config, [
            {"role": "system", "content": "You are a precise analyzer. Output strict JSON only."},
            {"role": "user",   "content": prompt},
        ])
        data = _parse_json_safely(text)
        if data is None:
            return AgentResult(agent_name, False, error="JSON 解析失败", data={"raw": text[:500]})
        data = _strip_speculated(data)
        return AgentResult(agent_name, True, data=data)
    except Exception as e:  # noqa: BLE001
        return AgentResult(agent_name, False, error=str(e))


# -------- Pipeline --------
async def _run_pipeline(
    config: AIConfig,
    payload: PersonaPayload,
) -> dict[str, AgentResult]:
    agents = PRIVATE_AGENTS if payload.is_private else NON_PRIVATE_AGENTS
    tasks = [_run_agent(config, name, path, payload) for name, path in agents]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    return {r.name: r for r in results}


# -------- Synthesizer --------
async def _synthesize(
    config: AIConfig,
    payload: PersonaPayload,
    agents: dict[str, AgentResult],
) -> str:
    template_name = SYNTH_PRIVATE if payload.is_private else SYNTH_NON_PRIVATE
    template = _read_template(template_name)

    agent_dump = {
        name: (r.data if r.ok else {"error": r.error})
        for name, r in agents.items()
    }

    meta = {
        "name": payload.name,
        "persona_type": payload.persona_type,
        "basic_info": payload.basic_info,
        "personality": payload.personality,
        "relationship_context": payload.relationship_context,
        "domain": payload.domain,
        "works": payload.works,
        "has_raw_material": bool(payload.raw_material.strip()),
        "mode": payload.mode,
        "current_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    user_msg = f"""以下是 5 个 Agent 的 JSON 输出和元信息，请按模板输出最终 markdown 文本：

## 元信息
{json.dumps(meta, ensure_ascii=False, indent=2)}

## Agent 输出
{json.dumps(agent_dump, ensure_ascii=False, indent=2)}

## 合成模板与规则
{template}
"""
    text = await chat_completion(config, [
        {"role": "system", "content": "You are a persona synthesizer. Output clean markdown only."},
        {"role": "user",   "content": user_msg},
    ])
    return text.strip()


# -------- 质量自检 --------
def _quality_check(
    payload: PersonaPayload,
    agents: dict[str, AgentResult],
    system_prompt: str,
) -> list[str]:
    warnings: list[str] = []

    # 通用检查
    if len(system_prompt) < 1500:
        warnings.append("system_prompt 过短，可能信息不足")
    if len(system_prompt) > 8000:
        warnings.append("system_prompt 过长，可能浪费 context")

    # 失败的 Agent
    for name, r in agents.items():
        if not r.ok:
            warnings.append(f"{name} 生成失败：{r.error}")

    # 类型专属检查
    def _feat_count(key: str, subkey: str) -> int:
        r = agents.get(key)
        if not r or not r.ok:
            return 0
        val = r.data.get(subkey, [])
        return len(val) if isinstance(val, list) else 0

    if payload.is_private:
        if _feat_count("expression_dna", "features") < 3:
            warnings.append("表达 DNA 特征 < 3 条")
        if _feat_count("decision_anti", "anti_patterns") < 2:
            warnings.append("反模式 < 2 条，人设可能崩")
        if _feat_count("inner_tension", "tensions") < 1:
            warnings.append("缺少内在张力")
    else:  # non_private
        if _feat_count("mental_framework", "models") < 2:
            warnings.append("思维框架 < 2 个，可能沦为浅层模仿")
        if _feat_count("expression_dna", "features") < 3:
            warnings.append("表达 DNA 特征 < 3 条")
        if _feat_count("identity_timeline", "timeline") < 2:
            warnings.append("时间线节点 < 2 个")

    # ASK 模式警告
    if payload.mode == "ASK":
        warnings.append("信息量严重不足，建议补全后重生成")

    return warnings


# -------- 主入口 --------
async def generate_persona_v2(
    config: AIConfig,
    payload: PersonaPayload,
) -> dict[str, Any]:
    """完整的 v2 生成流程。

    返回 dict：
        memory / persona / system_prompt / dimensions / quality_warnings / mode
    """
    # Phase 1: 并行 Agent
    agents = await _run_pipeline(config, payload)

    # Phase 2: 合成 system_prompt
    system_prompt = await _synthesize(config, payload, agents)

    # Phase 3: 质量自检
    warnings = _quality_check(payload, agents, system_prompt)

    # Phase 4: 提取兼容字段（保持 DB schema 不变）
    # memory 字段 = private 的关系记忆 + 情感模式 JSON
    #             = non_private 的身份时间线 + 思维框架 JSON
    # persona 字段 = 其余 Agent 的 JSON
    if payload.is_private:
        memory_payload = {
            "relationship_memory": agents["relationship_memory"].data if agents["relationship_memory"].ok else {},
            "emotion_pattern":     agents["emotion_pattern"].data     if agents["emotion_pattern"].ok     else {},
        }
        persona_payload = {
            "expression_dna": agents["expression_dna"].data if agents["expression_dna"].ok else {},
            "decision_anti":  agents["decision_anti"].data  if agents["decision_anti"].ok  else {},
            "inner_tension":  agents["inner_tension"].data  if agents["inner_tension"].ok  else {},
        }
    else:
        memory_payload = {
            "identity_timeline": agents["identity_timeline"].data if agents["identity_timeline"].ok else {},
            "mental_framework":  agents["mental_framework"].data  if agents["mental_framework"].ok  else {},
        }
        persona_payload = {
            "expression_dna": agents["expression_dna"].data if agents["expression_dna"].ok else {},
            "decision_anti":  agents["decision_anti"].data  if agents["decision_anti"].ok  else {},
            "inner_tension":  agents["inner_tension"].data  if agents["inner_tension"].ok  else {},
        }

    dimensions = {name: r.data for name, r in agents.items() if r.ok}

    return {
        "memory": json.dumps(memory_payload, ensure_ascii=False, indent=2),
        "persona": json.dumps(persona_payload, ensure_ascii=False, indent=2),
        "system_prompt": system_prompt,
        "dimensions": dimensions,
        "quality_warnings": warnings,
        "mode": payload.mode,
        "persona_type": payload.persona_type,
    }


# -------- 增量更新 --------
async def regenerate_dimension(
    config: AIConfig,
    payload: PersonaPayload,
    dimension: str,
) -> AgentResult:
    """只重跑单个维度。

    dimension 合法值：见 PRIVATE_AGENTS / NON_PRIVATE_AGENTS 的 name 部分。
    """
    agents = PRIVATE_AGENTS if payload.is_private else NON_PRIVATE_AGENTS
    path = next((p for n, p in agents if n == dimension), None)
    if not path:
        return AgentResult(dimension, False, error=f"非法维度：{dimension}")
    return await _run_agent(config, dimension, path, payload)
