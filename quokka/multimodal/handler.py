"""
Multimodal Input Handler

Handles images (OCR), PDFs, and other non-text inputs
"""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Any

from ..core.config import get_config
from ..core.logger import get_logger
from ..core.types import Message, MessageType

logger = get_logger(__name__)


class MultimodalHandler:
    """
    Handles multimodal inputs

    Supports:
    - Image OCR with Tesseract
    - PDF text extraction
    - File type detection
    """

    def __init__(self) -> None:
        """Initialize the multimodal handler"""
        self.config = get_config()
        self._ocr_available = self._check_ocr()
        self._pdf_available = self._check_pdf()

    def _check_ocr(self) -> bool:
        """Check if OCR is available"""
        try:
            import pytesseract
            # Check if tesseract binary is available
            pytesseract.get_tesseract_version()
            return True
        except Exception as e:
            logger.warning(f"OCR not available: {e}")
            return False

    def _check_pdf(self) -> bool:
        """Check if PDF processing is available"""
        try:
            import pdfplumber
            return True
        except ImportError:
            logger.warning("PDF processing not available (install pdfplumber)")
            return False

    async def process_message(self, message: Message) -> Message:
        """
        Process a message for multimodal content

        Args:
            message: Message to process

        Returns:
            Processed message with extracted content
        """
        # Check for image data (for OCR)
        if message.metadata.get("image_for_ocr"):
            image_data = message.metadata.get("image_data")
            if image_data:
                ocr_result = await self.process_image_ocr(image_data)
                if ocr_result:
                    message.content = f"{message.content}\n\n[OCR Result]:\n{ocr_result}"

        # Check for document data
        if message.metadata.get("document_data"):
            doc_data = message.metadata.get("document_data")
            doc_mime = message.metadata.get("document_mime", "")

            if "pdf" in doc_mime:
                pdf_result = await self.process_pdf(doc_data)
                if pdf_result:
                    message.content = f"{message.content}\n\n[PDF Content]:\n{pdf_result}"

        return message

    async def process_image_ocr(self, image_data: bytes | str) -> str | None:
        """
        Perform OCR on an image

        Args:
            image_data: Image bytes or base64 string

        Returns:
            Extracted text or None
        """
        if not self._ocr_available:
            return "OCR not available (install tesseract and pytesseract)"

        try:
            import pytesseract
            from PIL import Image

            # Convert base64 to bytes if needed
            if isinstance(image_data, str):
                image_data = base64.b64decode(image_data)

            # Load image
            image = Image.open(BytesIO(image_data))

            # Perform OCR
            language = self.config.multimodal.ocr_language
            text = pytesseract.image_to_string(image, lang=language)

            if text.strip():
                logger.info(f"OCR extracted {len(text)} characters")
                return text.strip()

            return None

        except Exception as e:
            logger.exception(f"OCR failed: {e}")
            return f"OCR failed: {str(e)}"

    async def process_pdf(self, pdf_data: bytes | str) -> str | None:
        """
        Extract text from PDF

        Args:
            pdf_data: PDF bytes or base64 string

        Returns:
            Extracted text or None
        """
        if not self._pdf_available:
            return "PDF processing not available (install pdfplumber)"

        try:
            import pdfplumber

            # Convert base64 to bytes if needed
            if isinstance(pdf_data, str):
                pdf_data = base64.b64decode(pdf_data)

            # Open PDF
            pdf = pdfplumber.open(BytesIO(pdf_data))

            # Extract text from all pages
            text_parts = []

            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(f"--- Page {i + 1} ---\n{page_text}")

            pdf.close()

            if text_parts:
                result = "\n\n".join(text_parts)
                logger.info(f"PDF extraction: {len(result)} characters from {len(text_parts)} pages")
                return result

            return None

        except Exception as e:
            logger.exception(f"PDF extraction failed: {e}")
            return f"PDF extraction failed: {str(e)}"

    async def detect_content_type(self, data: bytes) -> str:
        """
        Detect the content type of binary data

        Args:
            data: Binary data

        Returns:
            MIME type string
        """
        # Try to detect using magic numbers
        if data[:4] == b'%PDF':
            return 'application/pdf'
        elif data[:8] == b'\x89PNG\r\n\x1a\n':
            return 'image/png'
        elif data[:2] == b'\xff\xd8':
            return 'image/jpeg'
        elif data[:4] == b'GIF8':
            return 'image/gif'
        elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return 'image/webp'

        # Try using python-magic if available
        try:
            import magic
            return magic.from_buffer(data, mime=True)
        except ImportError:
            pass

        return 'application/octet-stream'

    def is_processable(self, mime_type: str) -> bool:
        """Check if a MIME type can be processed"""
        processable = {
            'application/pdf',
            'image/png',
            'image/jpeg',
            'image/gif',
            'image/webp',
            'image/tiff',
            'image/bmp',
        }
        return mime_type in processable

    async def process_file(self, filepath: Path) -> str | None:
        """
        Process a file based on its type

        Args:
            filepath: Path to the file

        Returns:
            Extracted content or None
        """
        if not filepath.exists():
            return None

        # Read file content
        data = filepath.read_bytes()

        # Detect type
        mime_type = await self.detect_content_type(data)

        if mime_type == 'application/pdf':
            return await self.process_pdf(data)
        elif mime_type.startswith('image/'):
            return await self.process_image_ocr(data)

        return None

    async def process_base64(
        self,
        data: str,
        mime_type: str | None = None,
    ) -> str | None:
        """
        Process base64-encoded data

        Args:
            data: Base64 encoded data
            mime_type: Optional MIME type hint

        Returns:
            Extracted content or None
        """
        try:
            binary_data = base64.b64decode(data)

            if not mime_type:
                mime_type = await self.detect_content_type(binary_data)

            if mime_type == 'application/pdf':
                return await self.process_pdf(binary_data)
            elif mime_type.startswith('image/'):
                return await self.process_image_ocr(binary_data)

            return None

        except Exception as e:
            logger.error(f"Failed to process base64 data: {e}")
            return None
