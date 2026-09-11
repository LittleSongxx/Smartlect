"""Real text PDF fixtures made with the same small installed PDF dependency."""
from io import BytesIO
import unittest

from pypdf import PdfWriter, get_configuration
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from smartlect.documents import MAX_INPUT_BYTES, MAX_TEXT_CHARS, parse_document
from smartlect.state import StateError


def text_pdf(text="Smartlect simulated payment only.", *, pages=1, password=None):
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=300, height=300)
        if text:
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
            stream = DecodedStreamObject()
            stream.set_data(b"BT /F1 12 Tf 10 200 Td (" + text.encode("ascii") + b") Tj ET")
            page[NameObject("/Contents")] = writer._add_object(stream)
    if password:
        writer.encrypt(password)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class DocumentTests(unittest.TestCase):
    def test_utf8_markdown_and_txt_preserve_content_without_opening_paths(self):
        self.assertEqual(parse_document("policy.MD", b"\xef\xbb\xbf# Smartlect\r\nPolicy"),
                         {"body": "# Smartlect\nPolicy", "media_type": "text/markdown"})
        self.assertEqual(parse_document("policy.txt", "中文政策".encode())["body"], "中文政策")
        for name in ("../policy.txt", "https://example.com/policy.txt", "C:\\policy.txt"):
            with self.assertRaisesRegex(StateError, "invalid_document_filename"):
                parse_document(name, b"text")

    def test_actual_pdf_text_layer_is_extracted_and_limits_are_context_local(self):
        before = get_configuration()
        result = parse_document("policy.pdf", text_pdf(pages=2))
        self.assertEqual(result["media_type"], "application/pdf")
        self.assertEqual(result["body"].count("Smartlect simulated payment only."), 2)
        self.assertEqual(get_configuration(), before)

    def test_blank_encrypted_malformed_and_too_many_pages_fail_without_content(self):
        for payload, code in ((text_pdf(text=""), "document_has_no_text"),
                              (text_pdf(password="fixture-password"), "encrypted_pdf_not_supported"),
                              (text_pdf(pages=41), "pdf_page_limit"),
                              (b"%PDF-1.7\nPRIVATE_TEXT_DO_NOT_ECHO", "invalid_pdf")):
            with self.assertRaises(StateError) as failure:
                parse_document("policy.pdf", payload)
            self.assertEqual(str(failure.exception), code)
            self.assertNotIn("PRIVATE_TEXT_DO_NOT_ECHO", str(failure.exception))

    def test_input_encoding_and_extracted_text_limits(self):
        for name, data, code in (("policy.txt", b"x" * (MAX_INPUT_BYTES + 1), "document_input_too_large"),
                                ("policy.txt", b"\xff", "document_requires_utf8"),
                                ("policy.txt", b"binary\0text", "document_invalid_text"),
                                ("policy.docx", b"zip", "unsupported_document_format"),
                                ("policy.txt", b"x" * (MAX_TEXT_CHARS + 1), "document_text_too_large"),
                                ("policy.pdf", text_pdf("x" * (MAX_TEXT_CHARS + 1)), "document_text_too_large")):
            with self.assertRaisesRegex(StateError, code):
                parse_document(name, data)


if __name__ == "__main__":
    unittest.main()
