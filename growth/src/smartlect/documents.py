"""Bounded in-memory text import. Filenames select a format, never a filesystem path."""
from io import BytesIO
from pathlib import PurePath

from pypdf import PdfReader, apply_configuration
from pypdf.errors import LimitReachedError

from smartlect.state import StateError

MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 300000
MAX_PDF_PAGES = 40
MAX_PDF_STREAM_BYTES = 2 * 1024 * 1024
MAX_PAGE_CONTENT_BYTES = 8 * 1024 * 1024


def _text(body):
    if len(body) > MAX_TEXT_CHARS:
        raise StateError("document_text_too_large", 413)
    if not body.strip():
        raise StateError("document_has_no_text", 422)
    if any(ord(character) < 32 and character not in "\t\r\n" for character in body):
        raise StateError("document_invalid_text", 422)
    return body.replace("\r\n", "\n").replace("\r", "\n")


def parse_document(filename, data):
    if (not isinstance(filename, str) or not filename or len(filename) > 256
            or any(character in filename for character in "/\\:\0")):
        raise StateError("invalid_document_filename", 422)
    if not isinstance(data, bytes):
        raise StateError("invalid_document_bytes", 422)
    if not data or len(data) > MAX_INPUT_BYTES:
        raise StateError("document_input_too_large" if data else "document_empty", 413 if data else 422)
    extension = PurePath(filename).suffix.lower()
    if extension not in {".md", ".txt", ".pdf"}:
        raise StateError("unsupported_document_format", 415)
    if extension != ".pdf":
        try:
            body = data.decode("utf-8-sig")
        except UnicodeError:
            raise StateError("document_requires_utf8", 422) from None
        return {"body": _text(body), "media_type": "text/markdown" if extension == ".md" else "text/plain"}
    if not data.startswith(b"%PDF-"):
        raise StateError("invalid_pdf", 422)
    try:
        # Context-local pypdf limits leave other parsing calls and global settings alone.
        with apply_configuration(maximum_declared_stream_length=MAX_PDF_STREAM_BYTES,
                array_based_stream_maximum_output_length=MAX_PDF_STREAM_BYTES,
                zlib_maximum_output_length=MAX_PDF_STREAM_BYTES,
                lzw_maximum_output_length=MAX_PDF_STREAM_BYTES,
                run_length_maximum_output_length=MAX_PDF_STREAM_BYTES,
                jbig2_maximum_output_length=MAX_PDF_STREAM_BYTES,
                image_maximum_buffer_size=MAX_PDF_STREAM_BYTES,
                page_tree_maximum_entries=200, page_tree_maximum_depth=20,
                xform_maximum_invocations_per_extraction=32, jbig2dec_binary=None):
            reader = PdfReader(BytesIO(data), strict=True, root_object_recovery_limit=0)
            if reader.is_encrypted:
                raise StateError("encrypted_pdf_not_supported", 422)
            if len(reader.pages) > MAX_PDF_PAGES:
                raise StateError("pdf_page_limit", 413)
            parts, content_bytes, text_chars = [], 0, 0

            def visit(text, *_):
                nonlocal text_chars
                text_chars += len(text)
                if text_chars > MAX_TEXT_CHARS:
                    raise StateError("document_text_too_large", 413)

            for page in reader.pages:
                contents = page.get_contents()
                if contents is not None:
                    content_bytes += len(contents.get_data())
                    if content_bytes > MAX_PAGE_CONTENT_BYTES:
                        raise StateError("pdf_content_limit", 413)
                parts.append(page.extract_text(visitor_text=visit, extraction_mode="plain"))
            body = "\n\n".join(parts)
            return {"body": _text(body), "media_type": "application/pdf"}
    except StateError:
        raise
    except LimitReachedError:
        raise StateError("pdf_resource_limit", 413) from None
    except Exception:
        # Parser exceptions may contain bytes from the uploaded document.
        raise StateError("invalid_pdf", 422) from None
