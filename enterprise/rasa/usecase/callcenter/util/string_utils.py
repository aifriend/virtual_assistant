import unicodedata
from bs4 import BeautifulSoup


def sanitize_html_entities(text):
    """Converts to unicode html text format

    Args:
        text: HTML formatted text

    Returns:
        unicode text
    """

    return str(BeautifulSoup(text, "html.parser"))


def sanitize_spanish_string(text):
    """Removes accents and question marks from spanish language

    Args:
        text: String with original spancish text

    Returns:
        String without spanish accents
    """

    # type (str) -> (str)
    text = remove_accent_marks(text)
    return text.replace("¿", "").replace("?", "")


def remove_accent_marks(text):
    """Removes accents from spanish language

    Args:
        text: String with original spancish text

    Returns:
        String without spanish accents
    """

    s = ''.join((c for c in unicodedata.normalize('NFD', str(text)) if unicodedata.category(c) != 'Mn'))
    return s.decode()
