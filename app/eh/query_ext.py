"""Search-query extension keywords -> E-Hentai advanced-search params.

OPDS clients can only pass a free-text ``query``; these semantic keywords let
them reach the advanced-search form fields that have no f_search syntax.
Keywords are stripped from the query text and translated into upstream URL
params by ``EHService.search_galleries``:

    rating:5            -> advsearch=1&f_srdd=5   (minimum rating, 1-5)
    expunged            -> advsearch=1&f_sh=on    (show expunged galleries)
    nohide:uploader     -> f_sfu=on               (disable uploader filter)
    nohide:language     -> f_sfl=on               (disable language filter)
    nohide:tags         -> f_sft=on               (disable tag filter)
    nohide:all          -> f_sfu+f_sfl+f_sft=on

Design notes:
- No dedicated namespace prefix: the query already speaks native EH keyword
  syntax (``language:chinese`` passes straight through), so these read as
  part of the same language.
- Matching is case-insensitive and quote-aware: tokens inside double quotes
  are exact phrases and never match (searching for the literal string
  "rating:5" stays intact).
- Invalid values are silently dropped (keyword removed, no param, no error):
  a typo must not silently change what the client searches for.
"""

from __future__ import annotations

import re

# Keyword (lowercase) -> upstream params it activates.
_KEYWORDS: dict[str, dict[str, str]] = {
    "expunged": {"f_sh": "on"},
    "nohide:uploader": {"f_sfu": "on"},
    "nohide:language": {"f_sfl": "on"},
    "nohide:tags": {"f_sft": "on"},
    "nohide:all": {"f_sfu": "on", "f_sfl": "on", "f_sft": "on"},
}

# Minimum-rating keyword: f_srdd accepts 1-5 (stars), site-native values only.
_RATING_RE = re.compile(r"rating:([1-5])")

# Curly / full-width double-quote variants (see tag_translation._DOUBLE_QUOTE_RE)
# and ``ns: "phrase"`` spacing — kept in sync with tag_translation.
_DOUBLE_QUOTE_RE = re.compile("[\u201c\u201d\u201e\u00ab\u00bb\uff02]")
_COLON_SPACE_QUOTE_RE = re.compile(r':\s+"')


def _normalize_query(query: str) -> str:
    query = _DOUBLE_QUOTE_RE.sub('"', query)
    query = _COLON_SPACE_QUOTE_RE.sub(':"', query)
    return query


# Whitespace tokenizer that keeps double-quoted phrases as single tokens.
_TOKEN_RE = re.compile(r'[^\s"]+:"[^"]*"|"[^"]*"|\S+')


def extract_adv_params(query: str) -> tuple[str, dict[str, str]]:
    """Split extension keywords out of a free-text search query.

    Returns ``(remaining_query, extra_params)``. When nothing matched the
    original query string is returned untouched (whitespace preserved);
    otherwise the remainder is re-joined on single spaces. Any hit injects
    ``advsearch=1`` (the upstream gate for all advanced fields).
    """
    if not query:
        return query, {}
    query = _normalize_query(query)
    params: dict[str, str] = {}
    rest: list[str] = []
    matched = False
    for tok in _TOKEN_RE.findall(query):
        if tok.startswith('"'):  # quoted phrase: never a keyword
            rest.append(tok)
            continue
        key = tok.lower()
        hit = _KEYWORDS.get(key)
        if hit is not None:
            params.update(hit)
            matched = True
            continue
        m = _RATING_RE.fullmatch(key)
        if m is not None:
            params["f_srdd"] = m.group(1)
            matched = True
            continue
        if key.startswith(("rating:", "nohide:")) or key == "expunged":
            # Keyword-shaped token that failed validation (e.g. `rating:9`,
            # `nohide:bogus`): drop it silently instead of searching for it
            # literally (a typo must not silently change what is searched).
            matched = True
            continue
        rest.append(tok)
    if not matched:
        return query, {}
    if params:
        params = {"advsearch": "1", **params}
    return " ".join(rest), params
