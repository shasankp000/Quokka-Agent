"""
Web fetch tool for HTTP requests
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from ..core.types import ToolResult
from ..core.logger import get_logger
from .base import BaseTool

logger = get_logger(__name__)


class WebFetchTool(BaseTool):
    """
    Make HTTP requests to fetch web content

    Supports GET, POST, and other HTTP methods
    """

    name: ClassVar[str] = "web_fetch"
    description: ClassVar[str] = (
        "Make HTTP requests to fetch or interact with web resources. "
        "Supports GET, POST, PUT, DELETE methods. "
        "Returns response body, headers, and status code."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch",
            },
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"],
                "description": "HTTP method",
                "default": "GET",
            },
            "headers": {
                "type": "object",
                "description": "HTTP headers to send",
            },
            "body": {
                "type": "string",
                "description": "Request body (for POST/PUT/PATCH)",
            },
            "json_data": {
                "type": "object",
                "description": "JSON body (for POST/PUT/PATCH)",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds",
                "default": 30,
            },
            "follow_redirects": {
                "type": "boolean",
                "description": "Follow HTTP redirects",
                "default": True,
            },
        },
        "required": ["url"],
    }

    timeout: int = 30

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute an HTTP request

        Args:
            url: The URL to request
            method: HTTP method
            headers: Request headers
            body: Request body
            json_data: JSON body
            timeout: Request timeout
            follow_redirects: Whether to follow redirects

        Returns:
            ToolResult with response data
        """
        url = kwargs.get("url")
        method = kwargs.get("method", "GET").upper()
        headers = kwargs.get("headers", {})
        body = kwargs.get("body")
        json_data = kwargs.get("json_data")
        timeout = min(kwargs.get("timeout", 30), 120)  # Max 2 minutes
        follow_redirects = kwargs.get("follow_redirects", True)

        if not url:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error="No URL provided",
            )

        # Validate URL
        if not url.startswith(("http://", "https://")):
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error="URL must start with http:// or https://",
            )

        logger.info(f"Making {method} request to {url}")

        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=follow_redirects) as client:
                request_kwargs: dict[str, Any] = {}

                if headers:
                    request_kwargs["headers"] = headers

                if json_data:
                    request_kwargs["json"] = json_data
                elif body:
                    request_kwargs["content"] = body

                response = await client.request(method, url, **request_kwargs)

                # Build output
                output_parts = [
                    f"🌐 HTTP {method} {url}",
                    f"Status: {response.status_code} {response.reason_phrase}",
                    "",
                    "📋 Response Headers:",
                ]

                for key, value in list(response.headers.items())[:10]:
                    output_parts.append(f"  {key}: {value}")

                if len(response.headers) > 10:
                    output_parts.append(f"  ... and {len(response.headers) - 10} more headers")

                output_parts.append("")

                # Response body
                content_type = response.headers.get("content-type", "")

                if "application/json" in content_type:
                    try:
                        json_output = response.json()
                        import json
                        output_parts.append("📦 Response Body (JSON):")
                        output_parts.append(json.dumps(json_output, indent=2)[:10000])
                    except Exception:
                        output_parts.append("📦 Response Body:")
                        output_parts.append(response.text[:10000])
                elif "text/" in content_type or "html" in content_type:
                    output_parts.append("📄 Response Body:")
                    output_parts.append(response.text[:10000])
                else:
                    output_parts.append(f"📦 Response Body ({content_type}):")
                    output_parts.append(f"  Size: {len(response.content)} bytes")
                    output_parts.append(f"  First 100 bytes (hex): {response.content[:100].hex()}")

                output = "\n".join(output_parts)

                return ToolResult(
                    call_id="",
                    tool_name=self.name,
                    success=response.is_success,
                    output=output,
                    error=None if response.is_success else f"HTTP {response.status_code}: {response.reason_phrase}",
                )

        except httpx.TimeoutException:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error=f"Request timed out after {timeout} seconds",
            )
        except httpx.ConnectError as e:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error=f"Connection failed: {str(e)}",
            )
        except Exception as e:
            logger.exception(f"Web fetch failed: {e}")
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error=f"Request failed: {str(e)}",
            )
