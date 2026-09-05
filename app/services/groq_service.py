from typing import Any, List, Optional, Iterator
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
import logging
import time
from app.services.vector_store import VectorStoreService
from app.utils.time_info import get_time_information
from app.utils.retry import with_retry
from app.utils.text_clean import strip_reasoning
from config import (
    GROQ_API_KEYS,
    GROQ_MODEL,
    SCALABLE_SYSTEM_PROMPT,
    GENERAL_CHAT_ADDENDUM,
)

logger = logging.getLogger("SCALABLE")
GROQ_REQUEST_TIMEOUT = 60

ALL_APIS_FAILED_MESSAGE = (
    "I'm unable to process your request at the moment. All API services are "
    "temporarily unavailable. Please try again in a few minutes."
)

class AllGroqApisFailedError(Exception):
    pass

def escape_curly_braces(text: str) -> str:
    if not text:
        return text
    return text.replace("{", "{{").replace("}", "}}")

_REPEAT_WINDOW = 100
_REPEAT_THRESHOLD = 3
_REPEAT_CHECK_INTERVAL = 200

def _detect_repetition_loop(text: str) -> bool:

    if len(text) < _REPEAT_WINDOW * _REPEAT_THRESHOLD:
        return False

    phrase = text[-_REPEAT_WINDOW:]
    return text.count(phrase) >= _REPEAT_THRESHOLD

def _truncate_at_repetition(text: str) -> str:

    if len(text) < _REPEAT_WINDOW * _REPEAT_THRESHOLD:
        return text

    phrase = text[-_REPEAT_WINDOW:]
    if text.count(phrase) < _REPEAT_THRESHOLD:
        return text

    first = text.find(phrase)
    second = text.find(phrase, first + 1)

    if second > first:
        return text[:second].rstrip()
    return text

def _normalize_response_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        if isinstance(content.get("content"), str):
            return content["content"]
        if isinstance(content.get("text"), str):
            return content["text"]
        return ""
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if isinstance(item.get("content"), str):
                    parts.append(item["content"])
                elif isinstance(item.get("text"), str):
                    parts.append(item["text"])
        return "".join(parts)
    return str(content)

def _is_rate_limit_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "429" in str(exc) or "rate limit" in msg or "tokens per day" in msg

def _log_timing(label: str, elapsed: float, extra: str = ""):
    msg = f"[TIMING] {label}: {elapsed:.3f}s"

    if extra:
        msg += f" ({extra})"
    logger.info(msg)

def _mask_api_key(key: str) -> str:

    if not key or len(key) <= 12:
        return "***masked***"
    return f"{key[:8]}...{key[-4:]}"

class GroqService:

    def __init__(self, vector_store_service: VectorStoreService):

        if not GROQ_API_KEYS:
            raise ValueError(
                "No Groq API keys configured. Set GROQ_API_KEY (and optionally GROQ_API_KEY_2, GROQ_API_KEY_3, ...) in .env"
            )

        self.llms = [
            ChatGroq(
                api_key=key,
                model=GROQ_MODEL,
                temperature=0.5,
                max_tokens=1024,
                timeout=GROQ_REQUEST_TIMEOUT,
                model_kwargs={"frequency_penalty": 0.3},
            )
            for key in GROQ_API_KEYS
        ]

        self.vector_store_service = vector_store_service
        logger.info(f"Initialized GroqService with {len(GROQ_API_KEYS)} API key(s) (primary-first fallback)")

    def _invoke_llm(
        self,
        prompt: ChatPromptTemplate,
        messages: list,
        question: str,
        key_start_index: int = 0,
    ) -> str:

        n = len(self.llms)
        last_exc = None
        keys_tried = []

        for j in range(n):
            i = (key_start_index + j) % n
            keys_tried.append(i)
            masked_key = _mask_api_key(GROQ_API_KEYS[i])
            logger.info(f"Trying API key #{i + 1}/{n}: {masked_key}")

            def _invoke_with_key():
                chain = prompt | self.llms[i]
                return chain.invoke({"history": messages, "question": question})

            try:
                response = with_retry(
                    _invoke_with_key,
                    max_retries=2,
                    initial_delay=0.5,
                )

                if i > 0:
                    logger.info(f"Fallback successful: API key #{i + 1}/{n} succeeded: {masked_key}")

                text = strip_reasoning(_normalize_response_text(response.content))

                if _detect_repetition_loop(text):
                    logger.warning("[INVOKE] Repetition loop detected - truncating response (%d chars)", len(text))
                    text = _truncate_at_repetition(text)
                return text

            except Exception as e:
                last_exc = e

                if _is_rate_limit_error(e):
                    logger.warning(f"API key #{i + 1}/{n} rate limited: {masked_key}")
                else:
                    logger.warning(f"API key #{i + 1}/{n} failed: {masked_key} - {str(e)[:100]}")

                if i < n - 1:
                    logger.info(f"Falling back to next API key...")
                    continue

                break

        masked_all = ", ".join([_mask_api_key(GROQ_API_KEYS[j]) for j in keys_tried])
        logger.error(f"All {n} API key(s) failed. Tried: {masked_all}")
        raise AllGroqApisFailedError(ALL_APIS_FAILED_MESSAGE) from last_exc

    def _stream_llm(
        self,
        prompt: ChatPromptTemplate,
        messages: list,
        question: str,
        key_start_index: int = 0,
    ) -> Iterator[str]:

        n = len(self.llms)
        last_exc = None

        for j in range(n):
            i = (key_start_index + j) % n
            masked_key = _mask_api_key(GROQ_API_KEYS[i])
            logger.info(f"Streaming with API key #{i + 1}/{n}: {masked_key}")

            try:
                chain = prompt | self.llms[i]
                chunk_count = 0
                first_chunk_time = None
                stream_start = time.perf_counter()
                accumulated = ""
                last_check_len = 0
                repetition_stopped = False
                in_think_block = False
                pending = ""  # holds partial tag text that might be the start of <think> or </think>

                for chunk in chain.stream({"history": messages, "question": question}):
                    content = ""

                    if hasattr(chunk, "content"):
                        content = chunk.content or ""

                    elif isinstance(chunk, dict) and "content" in chunk:
                        content = chunk.get("content", "") or ""

                    if isinstance(content, str) and content:

                        if first_chunk_time is None:
                            first_chunk_time = time.perf_counter() - stream_start
                            _log_timing("first_chunk", first_chunk_time)

                        chunk_count += 1
                        accumulated += content

                        if len(accumulated) - last_check_len >= _REPEAT_CHECK_INTERVAL:
                            last_check_len = len(accumulated)

                            if _detect_repetition_loop(accumulated):
                                logger.warning("[STREAM] Repetition loop detected after %d chars - stopping", len(accumulated))
                                repetition_stopped = True
                                break

                        # Filter out <think>...</think> reasoning blocks live, so
                        # they never reach the UI even mid-stream. `pending` holds
                        # back a short tail of text in case it's the start of a tag
                        # that's been split across chunk boundaries.
                        pending += content
                        emit = ""

                        while pending:
                            if not in_think_block:
                                tag_pos = pending.find("<think>")

                                if tag_pos != -1:
                                    emit += pending[:tag_pos]
                                    pending = pending[tag_pos + len("<think>"):]
                                    in_think_block = True
                                    continue

                                # Keep back a small tail that could be a partial "<think>"
                                safe_len = max(0, len(pending) - len("<think>"))
                                emit += pending[:safe_len]
                                pending = pending[safe_len:]
                                break
                            else:
                                tag_pos = pending.find("</think>")

                                if tag_pos != -1:
                                    pending = pending[tag_pos + len("</think>"):]
                                    in_think_block = False
                                    continue

                                # Still inside the reasoning block - discard it all,
                                # just keep a small tail for partial-tag detection.
                                safe_len = max(0, len(pending) - len("</think>"))
                                pending = pending[safe_len:]
                                break

                        if emit:
                            yield emit

                # Flush anything left in `pending` once the stream ends, unless it
                # was mid-reasoning-block (unclosed <think> - discard, nothing usable).
                if pending and not in_think_block:
                    yield pending

                total_stream = time.perf_counter() - stream_start
                _log_timing("groq_stream_total", total_stream, f"chunks: {chunk_count}{', TRUNCATED-REPETITION' if repetition_stopped else ''}")

                if i > 0 and chunk_count > 0:
                    logger.info(f"Fallback successful: API key #{i + 1}/{n} streamed: {masked_key}")
                return

            except Exception as e:

                last_exc = e
                if _is_rate_limit_error(e):
                    logger.warning(f"API key #{i + 1}/{n} rate limited: {masked_key}")

                else:
                    logger.warning(f"API key #{i + 1}/{n} failed: {masked_key} - {str(e)[:100]}")

                if i < n - 1:
                    logger.info("Falling back to next API key for stream...")
                    continue
                break

        logger.error(f"All {n} API key(s) failed during stream.")
        raise AllGroqApisFailedError(ALL_APIS_FAILED_MESSAGE) from last_exc

    def _build_prompt_and_messages(
        self,
        question: str,
        chat_history: Optional[List[tuple]] = None,
        extra_system_parts: Optional[List[str]] = None,
        mode_addendum: str = "",
        include_personal_context: bool = False,
    ) -> tuple:

        context = ""
        context_sources = []
        t0 = time.perf_counter()

        # Personal context (owner's learning data + indexed chat history) is
        # only retrieved for the owner account. Guests and other users get a
        # clean prompt — their name/identity never leaks into their replies.
        if include_personal_context:
            try:
                retriever = self.vector_store_service.get_retriever(k=5)

                context_docs = retriever.invoke(question)

                if context_docs:
                    context = "\n".join([doc.page_content for doc in context_docs])

                    context_sources = [doc.metadata.get("source", "unknown") for doc in context_docs]
                    logger.info("[CONTEXT] Retrieved %d chunks from sources: %s", len(context_docs), context_sources)

                else:
                    logger.info("[CONTEXT] No relevant chunks found for query")

            except Exception as retrieval_err:
                logger.warning("Vector store retrieval failed, using empty context: %s", retrieval_err)

            finally:
                _log_timing("vector_db", time.perf_counter() - t0)

        time_info = get_time_information()
        system_message = SCALABLE_SYSTEM_PROMPT

        system_message += f"\n\nCurrent time and date: {time_info}"

        if context:
            system_message += f"\n\nRelevant context from your learning data and past conversations:\n{escape_curly_braces(context)}"

        if extra_system_parts:
            system_message += "\n\n" + "\n\n".join(extra_system_parts)

        if mode_addendum:
            system_message += f"\n\n{mode_addendum}"

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_message),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{question}"),
        ])

        messages = []

        if chat_history:
            for human_msg, ai_msg in chat_history:
                messages.append(HumanMessage(content=human_msg))
                messages.append(AIMessage(content=ai_msg))

        logger.info("[PROMPT] System message length: %d chars | History pairs: %d | Question: %.100s",
                    len(system_message), len(chat_history) if chat_history else 0, question)

        return prompt, messages

    def get_response(
        self,
        question: str,
        chat_history: Optional[List[tuple]] = None,
        key_start_index: int = 0,
        extra_system_parts: Optional[List[str]] = None,
        include_personal_context: bool = False,
    ) -> str:

        try:
            prompt, messages = self._build_prompt_and_messages(
                question, chat_history, extra_system_parts=extra_system_parts, mode_addendum=GENERAL_CHAT_ADDENDUM,
                include_personal_context=include_personal_context,
            )
            t0 = time.perf_counter()
            result = self._invoke_llm(prompt, messages, question, key_start_index=key_start_index)
            _log_timing("groq_api", time.perf_counter() - t0)
            logger.info("[RESPONSE] General chat | Length: %d chars | Preview: %.120s", len(result), result)
            return result

        except AllGroqApisFailedError:
            raise

        except Exception as e:
            raise Exception(f"Error getting response from Groq: {str(e)}") from e

    def stream_response(
        self,
        question: str,
        chat_history: Optional[List[tuple]] = None,
        key_start_index: int = 0,
        extra_system_parts: Optional[List[str]] = None,
        include_personal_context: bool = False,
    ) -> Iterator[dict[str, dict[str, str]] | str]:

        try:
            prompt, messages = self._build_prompt_and_messages(
                question, chat_history, extra_system_parts=extra_system_parts, mode_addendum=GENERAL_CHAT_ADDENDUM,
                include_personal_context=include_personal_context,
            )
            if include_personal_context:
                yield {"_activity": {"event": "context_retrieved", "message": "Retrieved relevant context from knowledge base"}}
            yield from self._stream_llm(prompt, messages, question, key_start_index=key_start_index)

        except AllGroqApisFailedError:
            raise

        except Exception as e:
            raise Exception(f"Error streaming response from Groq: {str(e)}") from e
