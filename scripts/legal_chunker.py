import re


def split_numerals(article_number, article_text):

    numeral_pattern = re.compile(
        rf"({article_number}\.\d+.*?)"
        rf"(?={article_number}\.\d+|$)",
        re.DOTALL
    )

    numerals = []

    matches = list(
        numeral_pattern.finditer(article_text)
    )

    if len(matches) == 0:

        return [
            {
                "article": article_number,
                "numeral": None,
                "text": article_text
            }
        ]

    for match in matches:

        chunk = match.group(1).strip()

        numeral_match = re.match(
            rf"({article_number}\.\d+)",
            chunk
        )

        numeral = (
            numeral_match.group(1)
            if numeral_match
            else None
        )

        numerals.append(
            {
                "article": article_number,
                "numeral": numeral,
                "text": chunk
            }
        )

    return numerals