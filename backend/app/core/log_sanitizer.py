"""
House style: always use these helpers when logging URLs or tokens.
Never log raw credentials, API keys, or connection strings.
"""
from urllib.parse import urlparse


def mask_url(url: str) -> str:
    """Returns scheme://****@host:port/path — never logs password"""
    p = urlparse(url)
    return f"{p.scheme}://****@{p.hostname}:{p.port}{p.path}" if p.password else url


def mask_token(token: str, visible: int = 8) -> str:
    """Returns ...last8chars"""
    if not token or len(token) <= visible:
        return "****"
    return f"...{token[-visible:]}"
