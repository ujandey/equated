import re
import unicodedata

_SUPERSCRIPT_TRANSLATION = str.maketrans({
    "\u00B2": "^2",
    "\u00B3": "^3",
    "\u2070": "^0",
    "\u00B9": "^1",
    "\u2074": "^4",
    "\u2075": "^5",
    "\u2076": "^6",
    "\u2077": "^7",
    "\u2078": "^8",
    "\u2079": "^9",
})

class QueryNormalizer:
    """Handles text sanitation and normalization for incoming queries."""

    @staticmethod
    def normalize_input(query: str) -> str:
        text = (query or "").replace("\u00B2", "^2").replace("\u00B3", "^3")
        text = text.translate(_SUPERSCRIPT_TRANSLATION)
        text = unicodedata.normalize("NFKC", text)
        text = text.replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")
        text = text.replace("\u00D7", "*").replace("\u00B7", "*").replace("\u00F7", "/")
        text = re.sub(r"\s+", " ", text).strip()
        return text

query_normalizer = QueryNormalizer()
