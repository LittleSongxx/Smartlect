"""LangChain BaseChatModel 适配器：把 Smartlect Provider（openai SDK + 白名单校验）
暴露为框架原生模型接口，供 create_react_agent 等预构建组件直接消费。

消息在 LangChain 对象与 OpenAI dict 协议之间做无损往返；工具 schema 原样透传
（compatible-mode 端点接受 OpenAI 工具格式，LangChain 的 convert_to_openai_tool
产物也是该格式，直接下发即可）。
"""
from typing import Any

from langchain_core.callbacks import AsyncCallbackManager
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult


def to_openai_messages(messages: list[BaseMessage]) -> list[dict]:
    result = []
    for message in messages:
        if isinstance(message, SystemMessage):
            result.append({"role": "system", "content": message.content})
        elif isinstance(message, HumanMessage):
            result.append({"role": "user", "content": message.content})
        elif isinstance(message, AIMessage):
            entry = {"role": "assistant", "content": message.content}
            if message.tool_calls:
                entry["tool_calls"] = [
                    {"id": call["id"], "type": "function",
                     "function": {"name": call["name"], "arguments": call["args"]}}
                    if isinstance(call["args"], str) else
                    {"id": call["id"], "type": "function",
                     "function": {"name": call["name"],
                                  "arguments": __import__("json").dumps(call["args"], ensure_ascii=False)}}
                    for call in message.tool_calls]
            result.append(entry)
        elif isinstance(message, ToolMessage):
            result.append({"role": "tool", "tool_call_id": message.tool_call_id,
                           "content": message.content if isinstance(message.content, str)
                           else __import__("json").dumps(message.content, ensure_ascii=False)})
        else:
            raise ValueError(f"unsupported_message_type:{type(message).__name__}")
    return result


def from_openai_message(message: dict) -> AIMessage:
    """Provider 返回的 assistant dict → AIMessage（含 tool_calls 结构化）。"""
    content = message.get("content")
    if content is None and (message.get("tool_calls") or []):
        content = ""  # AIMessage 校验要求 content 为 str；纯工具调用轮以空串表达
    tool_calls = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        arguments = function.get("arguments") or "{}"
        if isinstance(arguments, str):
            try:
                import json
                arguments = json.loads(arguments)
            except Exception:
                arguments = {"_raw": arguments}
        tool_calls.append({"id": call.get("id") or "", "name": function.get("name") or "",
                           "args": arguments})
    return AIMessage(content=content, tool_calls=tool_calls,
                     additional_kwargs={"refusal": message.get("refusal")})


class ProviderChatModel(BaseChatModel):
    """Smartlect Provider 的 LangChain 适配层。

    预算（模型调用计数、trace、prompt_version 标注）仍由 Provider 内部承担——
    这与框架无冲突：BaseChatModel 的职责是协议适配，不是成本治理。
    """
    provider: Any
    tools_wire: list = []
    tool_choice_wire: Any = None
    max_tokens: int = 1024
    prompt_version: str = "shopping-react"
    skill_versions: dict = {}
    schema_version: str = "shopping-answer"

    @property
    def _llm_type(self) -> str:
        return "smartlect-provider"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ProviderChatModel":
        wire = list(tools)  # 已是 OpenAI function 格式；由调用方保证
        return self.__class__(provider=self.provider, tools_wire=wire,
                              tool_choice_wire=kwargs.get("tool_choice"),
                              max_tokens=self.max_tokens,
                              prompt_version=self.prompt_version,
                              skill_versions=self.skill_versions,
                              schema_version=self.schema_version)

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        raise NotImplementedError("sync_generate_not_used; assistant runtime is async-only")

    async def _agenerate(self, messages: list[BaseMessage], stop=None,
                         run_manager: AsyncCallbackManager | None = None, **kwargs) -> ChatResult:
        response = await self.provider.chat(
            to_openai_messages(messages),
            tools=self.tools_wire or None,
            tool_choice=self.tool_choice_wire,
            max_tokens=self.max_tokens,
            prompt_version=self.prompt_version,
            skill_versions=self.skill_versions,
            schema_version=self.schema_version)
        message = from_openai_message(response["message"])
        generation = ChatGeneration(message=message)
        generation.generation_info = {"usage": response.get("usage"),
                                      "metadata": response.get("metadata")}
        return ChatResult(generations=[generation])
