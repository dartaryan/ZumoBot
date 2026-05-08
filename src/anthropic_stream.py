"""Anthropic streaming wrapper with auto-continuation on max_tokens.

Wraps `client.messages.stream(...)` so callers don't have to deal with the
silent-truncation failure mode: when the model hits `stop_reason: max_tokens`
mid-output, the stream still ends with HTTP 200 OK and the partial text comes
back as if it were complete. This module detects that case and continues
generation via the assistant-prefill pattern (sending the partial text back
as an assistant turn so the model picks up exactly where it left off).
"""

from dataclasses import dataclass
import logging

from anthropic import Anthropic

logger = logging.getLogger(__name__)

MAX_CONTINUATION_ITERATIONS = 3


@dataclass
class StreamResult:
    """Outcome of a stream_with_continuation call.

    `truncated=True` means the final stop_reason was still `max_tokens` even
    after `max_iterations` continuation passes — content is incomplete and the
    caller must surface this to the user.
    """
    text: str
    stop_reason: str
    iterations: int
    truncated: bool
    total_input_tokens: int
    total_output_tokens: int


def stream_with_continuation(
    client: Anthropic,
    model: str,
    max_tokens: int,
    system: str,
    user_message: str,
    max_iterations: int = MAX_CONTINUATION_ITERATIONS,
) -> StreamResult:
    """Stream a Claude response, auto-continuing on max_tokens.

    On each iteration: open a stream, drain text deltas, read the final
    Message for stop_reason and usage. If stop_reason is `max_tokens` and we
    still have iterations left, prefill the next call's assistant turn with
    everything so far and continue. Concatenate exactly — no whitespace
    stripping, which would corrupt boundary tokens.
    """
    text_parts: list[str] = []
    total_input = 0
    total_output = 0
    iterations = 0
    final_stop_reason = ""

    messages: list[dict] = [{"role": "user", "content": user_message}]

    while iterations < max_iterations:
        iterations += 1
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        ) as stream:
            chunk = "".join(stream.text_stream)
            final_message = stream.get_final_message()

        text_parts.append(chunk)
        total_input += final_message.usage.input_tokens
        total_output += final_message.usage.output_tokens
        final_stop_reason = final_message.stop_reason or ""

        logger.info(
            "anthropic stream iter=%d stop_reason=%s out_tokens=%d cum_chars=%d",
            iterations, final_stop_reason,
            final_message.usage.output_tokens, sum(len(p) for p in text_parts),
        )

        if final_stop_reason != "max_tokens":
            break

        if iterations >= max_iterations:
            logger.warning(
                "anthropic stream exhausted %d iterations still at max_tokens; truncated",
                max_iterations,
            )
            break

        full_so_far = "".join(text_parts)
        logger.warning(
            "anthropic stream hit max_tokens on iter=%d; continuing (chars=%d, cum_out_tokens=%d)",
            iterations, len(full_so_far), total_output,
        )
        messages = [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": full_so_far},
        ]

    return StreamResult(
        text="".join(text_parts),
        stop_reason=final_stop_reason,
        iterations=iterations,
        truncated=(final_stop_reason == "max_tokens"),
        total_input_tokens=total_input,
        total_output_tokens=total_output,
    )
