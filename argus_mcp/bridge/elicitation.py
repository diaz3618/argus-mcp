"""MCP Elicitation protocol — bridge forwarding and handling.

The elicitation protocol allows backend tools to request interactive
input from the user.  The bridge captures ``elicitation/create``
messages from backends and forwards them to the frontend (TUI or
client), then routes the user's response back.

Flow::

    Backend → elicitation/create → Bridge → TUI Modal → User Input
    User Input → Bridge → elicitation/response → Backend

"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

from argus_mcp.constants import SHORT_ID_LENGTH

logger = logging.getLogger(__name__)

# Callback type:  (request) -> Optional[Dict] response from user
ElicitationCallback = Callable[
    ["ElicitationRequest"],
    Coroutine[Any, Any, Optional[Dict[str, Any]]],
]


class ElicitationStatus(Enum):
    """Status of an elicitation request."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    TIMEOUT = "timeout"


@dataclass
class ElicitationField:
    """A single field in an elicitation form.

    Mirrors JSON Schema property definition with UI hints.
    """

    name: str
    field_type: str = "string"  # string, boolean, integer, number, enum
    description: str = ""
    required: bool = False
    default: Any = None
    enum_values: List[str] = field(default_factory=list)

    @classmethod
    def from_schema(
        cls, name: str, prop: Dict[str, Any], required_list: List[str]
    ) -> ElicitationField:
        """Parse from a JSON Schema property definition."""
        return cls(
            name=name,
            field_type=prop.get("type", "string"),
            description=prop.get("description", ""),
            required=name in required_list,
            default=prop.get("default"),
            enum_values=prop.get("enum", []),
        )


@dataclass
class ElicitationRequest:
    """An elicitation request from a backend tool.

    Contains the form schema and metadata for user interaction.
    """

    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:SHORT_ID_LENGTH])
    tool_name: str = ""
    message: str = ""
    schema: Dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 120.0
    backend_name: str = ""

    @property
    def fields(self) -> List[ElicitationField]:
        """Parse schema properties into typed fields."""
        properties = self.schema.get("properties", {})
        required = self.schema.get("required", [])
        return [
            ElicitationField.from_schema(name, prop, required) for name, prop in properties.items()
        ]

    @classmethod
    def from_message(cls, data: Dict[str, Any]) -> ElicitationRequest:
        """Parse from an MCP elicitation/create message."""
        return cls(
            request_id=data.get("requestId", uuid.uuid4().hex[:SHORT_ID_LENGTH]),
            tool_name=data.get("toolName", ""),
            message=data.get("message", ""),
            schema=data.get("schema", {}),
            timeout_seconds=data.get("timeout", 120.0),
        )


@dataclass
class ElicitationResponse:
    """User's response to an elicitation request."""

    request_id: str
    status: ElicitationStatus
    data: Dict[str, Any] = field(default_factory=dict)

    def to_message(self) -> Dict[str, Any]:
        """Convert to MCP elicitation/response message."""
        return {
            "requestId": self.request_id,
            "status": self.status.value,
            "data": self.data,
        }


class ElicitationBridge:
    """Manages elicitation request/response flow.

    The bridge registers a callback (typically the TUI) that handles
    user interaction.  When a backend sends an elicitation request,
    the bridge invokes the callback and returns the response.
    """

    def __init__(self, default_timeout: float = 120.0) -> None:
        self._callback: Optional[ElicitationCallback] = None
        self._default_timeout = default_timeout
        self._pending: Dict[str, ElicitationRequest] = {}

    def register_handler(self, callback: ElicitationCallback) -> None:
        """Register the UI callback for handling elicitation forms."""
        self._callback = callback

    async def handle_request(self, request: ElicitationRequest) -> ElicitationResponse:
        """Process an elicitation request.

        Forwards to the registered handler and waits for a response
        with timeout.
        """
        if not self._callback:
            logger.warning(
                "No elicitation handler registered — auto-denying request %s",
                request.request_id,
            )
            return ElicitationResponse(
                request_id=request.request_id,
                status=ElicitationStatus.DENIED,
            )

        self._pending[request.request_id] = request
        timeout = request.timeout_seconds or self._default_timeout

        try:
            result = await asyncio.wait_for(
                self._callback(request),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Elicitation request %s timed out after %.0fs",
                request.request_id,
                timeout,
            )
            return ElicitationResponse(
                request_id=request.request_id,
                status=ElicitationStatus.TIMEOUT,
            )
        finally:
            self._pending.pop(request.request_id, None)

        if result is None:
            return ElicitationResponse(
                request_id=request.request_id,
                status=ElicitationStatus.DENIED,
            )

        return ElicitationResponse(
            request_id=request.request_id,
            status=ElicitationStatus.APPROVED,
            data=result,
        )

    @property
    def has_pending(self) -> bool:
        """Whether there are pending elicitation requests."""
        return bool(self._pending)
