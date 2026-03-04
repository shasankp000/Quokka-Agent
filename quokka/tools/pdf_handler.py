"""
PDF handling tool for text extraction
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, ClassVar

from ..core.types import ToolResult
from ..core.logger import get_logger
from .base import BaseTool

logger = get_logger(__name__)


class PDFHandlerTool(BaseTool):
    """
    Extract text from PDF files

    Uses pdfplumber for reliable text extraction
    """

    name: ClassVar[str] = "pdf_handler"
    description: ClassVar[str] = (
        "Extract text content from PDF files. "
        "Supports both local files and in-memory PDF data. "
        "Returns extracted text organized by page."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the PDF file (optional if data provided)",
            },
            "pages": {
                "type": "string",
                "description": "Pages to extract (e.g., '1-5', '1,3,5', default: all)",
            },
            "include_metadata": {
                "type": "boolean",
                "description": "Include PDF metadata in output",
                "default": True,
            },
        },
        "required": [],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Extract text from a PDF

        Args:
            path: Path to PDF file
            pages: Page range to extract
            include_metadata: Include metadata in output

        Returns:
            ToolResult with extracted text
        """
        path_str = kwargs.get("path")
        pages_spec = kwargs.get("pages")
        include_metadata = kwargs.get("include_metadata", True)

        if not path_str:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error="No PDF path provided",
            )

        try:
            import pdfplumber
        except ImportError:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error="pdfplumber not installed. Run: pip install pdfplumber",
            )

        try:
            path = Path(path_str).expanduser().resolve()

            if not path.exists():
                return ToolResult(
                    call_id="",
                    tool_name=self.name,
                    success=False,
                    error=f"PDF file not found: {path}",
                )

            output_parts = []

            with pdfplumber.open(path) as pdf:
                # Metadata
                if include_metadata and pdf.metadata:
                    output_parts.append("📄 PDF Metadata:")
                    for key, value in pdf.metadata.items():
                        if value:
                            output_parts.append(f"  {key}: {value}")
                    output_parts.append(f"\nTotal pages: {len(pdf.pages)}\n")

                # Parse page specification
                page_indices = self._parse_pages(pages_spec, len(pdf.pages))

                # Extract text from each page
                output_parts.append("📝 Extracted Text:\n")

                for i in page_indices:
                    page = pdf.pages[i]
                    text = page.extract_text() or ""

                    output_parts.append(f"--- Page {i + 1} ---")
                    output_parts.append(text)
                    output_parts.append("")

                    # Also extract tables if present
                    tables = page.extract_tables()
                    if tables:
                        output_parts.append(f"Tables on page {i + 1}:")
                        for j, table in enumerate(tables):
                            output_parts.append(f"\nTable {j + 1}:")
                            for row in table:
                                output_parts.append(" | ".join(str(cell or "") for cell in row))
                        output_parts.append("")

            output = "\n".join(output_parts)

            # Truncate if too long
            if len(output) > 50000:
                output = output[:50000] + "\n\n... [content truncated]"

            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=True,
                output=output,
            )

        except Exception as e:
            logger.exception(f"PDF extraction failed: {e}")
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error=f"Failed to extract PDF: {str(e)}",
            )

    def _parse_pages(self, pages_spec: str | None, total_pages: int) -> list[int]:
        """
        Parse page specification into list of 0-indexed page numbers

        Examples:
            "1-5" -> [0, 1, 2, 3, 4]
            "1,3,5" -> [0, 2, 4]
            "1-3,5,7-9" -> [0, 1, 2, 4, 6, 7, 8]
            None -> all pages
        """
        if not pages_spec:
            return list(range(total_pages))

        result = []

        for part in pages_spec.split(","):
            part = part.strip()

            if "-" in part:
                # Range
                start, end = part.split("-", 1)
                start = int(start.strip()) - 1  # Convert to 0-indexed
                end = int(end.strip())  # Keep as 1-indexed for range

                for i in range(max(0, start), min(total_pages, end)):
                    if i not in result:
                        result.append(i)
            else:
                # Single page
                page = int(part) - 1  # Convert to 0-indexed
                if 0 <= page < total_pages and page not in result:
                    result.append(page)

        return sorted(result)

    async def extract_from_bytes(self, data: bytes, **kwargs: Any) -> ToolResult:
        """
        Extract text from PDF bytes

        Args:
            data: PDF file bytes
            **kwargs: Additional options

        Returns:
            ToolResult with extracted text
        """
        try:
            import pdfplumber
        except ImportError:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error="pdfplumber not installed",
            )

        try:
            with pdfplumber.open(BytesIO(data)) as pdf:
                output_parts = []

                if kwargs.get("include_metadata", True) and pdf.metadata:
                    output_parts.append("📄 PDF Metadata:")
                    for key, value in pdf.metadata.items():
                        if value:
                            output_parts.append(f"  {key}: {value}")
                    output_parts.append("")

                for i, page in enumerate(pdf.pages):
                    text = page.extract_text() or ""
                    output_parts.append(f"--- Page {i + 1} ---")
                    output_parts.append(text)

                return ToolResult(
                    call_id="",
                    tool_name=self.name,
                    success=True,
                    output="\n".join(output_parts),
                )

        except Exception as e:
            return ToolResult(
                call_id="",
                tool_name=self.name,
                success=False,
                error=str(e),
            )
