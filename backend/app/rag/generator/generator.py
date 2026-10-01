import openai
from supabase import AsyncClient
import json
from uuid import UUID
from typing import Any, AsyncGenerator, Optional
import logging

from app.core.config import env_config
from app.rag.generator.tools import Tools

MAX_ITER = 5

logger = logging.getLogger(__name__)


class Generator:
    def __init__(self) -> None:
        self.google_base_url = (
            "https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        self.groq_base_url = "https://api.groq.com/openai/v1"
        self.models = [
            "google/gemini-3.5-flash-lite",
            "groq/openai/gpt-oss-120b",
            "groq/openai/gpt-oss-20b",
            "groq/qwen/qwen3.8-27b",
        ]

    def list_models(self):
        return self.models

    def generate_chat_content(
        self, user_message: str, system_prompt: str | None = None
    ):
        pass

    def get_chat_client(self, provider: str):
        client = openai.AsyncOpenAI(
            base_url=self.google_base_url if provider == "groq" else self.groq_base_url,
            api_key=(
                env_config.GEMINI_API_KEY
                if provider == "groq"
                else env_config.GROQ_API_KEY
            ),
        )

        return client

    async def LLM(self, model: str, messages: list):
        if model not in self.models:
            return {"type": "error", "content": f"Model '{model}' is not supported."}

        try:
            provider, provided_model = model.split("/", 1)
            client = self.get_chat_client(provider=provider)

            response = await client.chat.completions.create(
                model=provided_model, messages=messages
            )

            return {"type": "success", "content": response.choices[0].message}

        except openai.RateLimitError as e:
            logger.exception(f"[LLM]: {e}")
            return {
                "type": "error",
                "content": "Rate limit exceeded. Please try again in a moment.",
            }

        except openai.APIError as e:
            logger.exception(f"[LLM]: {e}")
            return {
                "type": "error",
                "content": "Upstream AI service error occurred.",
            }

        except Exception as e:
            logger.exception(f"[LLM]: {e}")
            return {
                "type": "error",
                "content": "An unexpected streaming error occurred.",
            }

    async def LLM_generator(
        self,
        model: str,
        bucket_client: AsyncClient,
        repo_id: UUID,
        messages: Optional[list] = None,
        max_iter: int = MAX_ITER,
    ) -> AsyncGenerator[dict[str, Any], None]:
        if model not in self.models:
            yield {"type": "error", "content": f"Model '{model}' is not supported."}
            return

        if not messages:
            messages = []

        tools = Tools(bucket_client)
        provider, provided_model = model.split("/", 1)
        client = self.get_chat_client(provider=provider)
        tool_schema = tools.get_tool_defination()

        for iteration in range(max_iter):
            content_chunks = []
            tool_calls_accumulator = {}
            try:
                response_stream = await client.chat.completions.create(
                    model=provided_model,
                    messages=messages,
                    tools=tool_schema,
                    tool_choice="auto",
                    stream=True,
                )

                async for chunk in response_stream:
                    if not chunk.choices:
                        continue

                    delta = chunk.choices[0].delta

                    if delta.content:
                        content_chunks.append(delta.content)
                        yield {"type": "token", "content": delta.content}

                    if delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index

                            if idx not in tool_calls_accumulator:
                                tool_calls_accumulator[idx] = {
                                    "id": "",
                                    "name": "",
                                    "arguments": "",
                                }

                            if tc_delta.id:
                                tool_calls_accumulator[idx]["id"] += tc_delta.id
                            if tc_delta.function and tc_delta.function.name:
                                tool_calls_accumulator[idx][
                                    "name"
                                ] += tc_delta.function.name
                            if tc_delta.function and tc_delta.function.arguments:
                                tool_calls_accumulator[idx][
                                    "arguments"
                                ] += tc_delta.function.arguments

            except openai.RateLimitError as e:
                logger.exception("[LLM-GENERATOR]: %s", e)
                yield {
                    "type": "error",
                    "content": "Rate limit exceeded. Please try again in a moment.",
                }
                return

            except openai.APIError as e:
                logger.exception(f"[LLM-GENERATOR]: {e}")
                yield {
                    "type": "error",
                    "content": "Upstream AI service error occurred.",
                }
                return

            except Exception as e:
                logger.exception(f"[LLM-GENERATOR]: {e}")
                yield {
                    "type": "error",
                    "content": "An unexpected streaming error occurred.",
                }
                return

            assistant_message = {
                "role": "assistant",
                "content": "".join(content_chunks) if content_chunks else None,
            }

            if tool_calls_accumulator:
                assistant_message["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments"],
                        },
                    }
                    for tc in tool_calls_accumulator.values()
                ]

            messages.append(assistant_message)

            if not tool_calls_accumulator:
                print("\n\n[Agent Finished]")
                yield {"type": "end", "content": "--[END-RESPONSE-COMPLETE]--"}
                return

            for tc in assistant_message["tool_calls"]:
                function_name = tc["function"]["name"]
                try:
                    function_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    function_args = {}

                yield {"type": "tool_call", "name": function_name}

                try:
                    tool_result = await tools.use_tool(
                        repo_id=repo_id,
                        tool_name=function_name,
                        function_arguments=str(function_args),
                    )
                except Exception as e:
                    logger.exception(
                        "[LLM-GENERATOR] LLM TOOL CALL FAILED, FUNCTION NAME : %s, ERROR: %s",
                        function_name,
                        e,
                    )
                    tool_result = {
                        "status": "error",
                        "message": f"TOOL EXECUTION FAILED, ERROR {str(e)}",
                        "data": None,
                    }

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(tool_result),
                    }
                )

        yield {
            "type": "error",
            "content": f"Agent reached the maximum iteration limit ({max_iter}) without reaching a conclusion.",
        }
