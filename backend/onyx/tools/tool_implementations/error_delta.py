from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from onyx.chat.emitter import Emitter
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    CalendarSearchToolDelta,
    CrmCreateToolDelta,
    CrmGetToolDelta,
    CrmListToolDelta,
    CrmLogInteractionToolDelta,
    CrmSearchToolDelta,
    CrmUpdateToolDelta,
    Packet,
)
from onyx.tools.models import ToolCallException, ToolExecutionException
from onyx.utils.logger import setup_logger

logger = setup_logger()

ERROR_PAYLOAD_KEY = "error"
UNEXPECTED_TOOL_ERROR_MESSAGE = "The tool failed unexpectedly. Please try again."

PayloadToolDelta = (
    CalendarSearchToolDelta
    | CrmCreateToolDelta
    | CrmGetToolDelta
    | CrmListToolDelta
    | CrmLogInteractionToolDelta
    | CrmSearchToolDelta
    | CrmUpdateToolDelta
)


def _emit_error(
    emitter: Emitter,
    placement: Placement,
    delta_type: type[PayloadToolDelta],
    message: str,
) -> None:
    emitter.emit(
        Packet(
            placement=placement, obj=delta_type(payload={ERROR_PAYLOAD_KEY: message})
        )
    )


@contextmanager
def stream_tool_call_error(
    emitter: Emitter,
    placement: Placement,
    delta_type: type[PayloadToolDelta],
) -> Iterator[None]:
    """Emit a failed call's error as the tool's result delta, then raise it.

    The runner only sends the error to the model, so without this delta the
    UI shows a tool with no result until a reload replays the stored error.
    An unexpected exception becomes a ToolCallException with a generic message,
    so the UI and the stored response never show the raw exception text.
    ToolExecutionException passes through: the runner handles it itself.
    The runner still emits the SectionEnd."""
    try:
        yield
    except ToolCallException as e:
        _emit_error(emitter, placement, delta_type, e.llm_facing_message)
        raise
    except ToolExecutionException:
        raise
    except Exception as e:
        logger.exception(
            "Unexpected error in the tool that streams %s", delta_type.__name__
        )
        _emit_error(emitter, placement, delta_type, UNEXPECTED_TOOL_ERROR_MESSAGE)
        raise ToolCallException(
            message=f"Unexpected {type(e).__name__}: {e}",
            llm_facing_message=UNEXPECTED_TOOL_ERROR_MESSAGE,
        ) from e
