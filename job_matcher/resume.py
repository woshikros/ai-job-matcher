from __future__ import annotations

from pathlib import Path


class ResumeReadError(ValueError):
    pass


def extract_resume_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".txt":
        text = path.read_text(encoding="utf-8", errors="ignore")
    elif suffix == ".pdf":
        from pypdf import PdfReader

        text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    elif suffix == ".docx":
        from docx import Document

        document = Document(str(path))
        text = "\n".join(p.text for p in document.paragraphs)
    else:
        raise ResumeReadError("仅支持 PDF、DOCX 或 TXT 简历")
    text = " ".join(text.split())
    if len(text) < 40:
        raise ResumeReadError("未能从简历中读取足够内容，请确认文件不是扫描图片")
    return text

