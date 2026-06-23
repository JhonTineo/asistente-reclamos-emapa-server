import fitz
import re


def extract_text_multicolumn(pdf_path):

    doc = fitz.open(pdf_path)

    pages = []

    for page in doc:

        blocks = page.get_text("blocks")

        blocks = sorted(
            blocks,
            key=lambda b: (b[1], b[0])
        )

        page_text = "\n".join(
            block[4]
            for block in blocks
        )

        pages.append(page_text)

    return "\n".join(pages)


def split_articles(text):

    pattern = re.compile(
        r"(ART[IÍ]CULO\s+\d+.*?)"
        r"(?=ART[IÍ]CULO\s+\d+|$)",
        re.IGNORECASE | re.DOTALL
    )

    articles = []

    for match in pattern.finditer(text):

        article_text = match.group(1)

        title_match = re.search(
            r"ART[IÍ]CULO\s+(\d+)",
            article_text,
            re.IGNORECASE
        )

        article_number = (
            title_match.group(1)
            if title_match
            else None
        )

        articles.append(
            {
                "article": article_number,
                "text": article_text
            }
        )

    return articles