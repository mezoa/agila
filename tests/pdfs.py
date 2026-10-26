"""Tiny PDFs built inside the tests (block m), so no real manual or binary file is committed.

`text_pdf` writes the bytes by hand (no private pypdf call, research U58): one page per string,
one line of Helvetica per text line; an empty string is a page with no text (scanned-like).
`locked_pdf` adds an RC4 password with public pypdf calls only (RC4 needs no extra package, V107).
"""

import io

from pypdf import PdfWriter


def _escape(line: str) -> str:
    return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _stream(text: str) -> bytes:
    if not text:
        return b""
    ops = ["BT /F1 11 Tf 72 720 Td 14 TL"]
    ops += [f"({_escape(line)}) Tj T*" for line in text.split("\n")]
    ops.append("ET")
    return "\n".join(ops).encode("latin-1")


def text_pdf(pages: list[str]) -> bytes:
    """A valid PDF with one page per string (ASCII or Latin-1 text)."""
    count = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(count))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, text in enumerate(pages):
        content = _stream(text)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
            f" /Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>".encode()
        )
        objects.append(
            f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    out += f"startxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def locked_pdf(data: bytes, user_password: str = "pw") -> bytes:
    """`data` with RC4 encryption; an empty `user_password` opens without a password."""
    writer = PdfWriter(clone_from=io.BytesIO(data))
    writer.encrypt(user_password=user_password, owner_password="owner", algorithm="RC4-128")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
