"""Czech-friendly lexical tokenization for the sparse (BM25-style) vectors.

Shared by ingest and the app so documents and queries are tokenized identically.
Lowercase, strip diacritics, drop stopwords, truncate to a crude stem.
"""

import re
import unicodedata
import zlib
from collections import Counter

STEM_LEN = 6
STOPWORDS = set(
    """a aby ale ani ano asi az bez bude budem budes by byl byla byli bylo byt co coz
    do i jak jake jako je jeho jej jeji jen jeste ji jine jiz jsem jses jsi jsme jsou jste k kam
    kde kdo kdyz ke ktera ktere ktery kteri mi mne mnou mu muj my na nad nam nas nasi ne
    nebo nez nic nich nim nas o od on ona oni ono pak po pod pokud pro proc pred pri s se si
    sve svuj ta tak take tam te tedy ten tento teto tim to tohle toho tom tomu tu tuto ty tyto
    u uz v vam vas ve vice vsak z za ze zde ze""".split()
)
TOKEN = re.compile(r"[a-z0-9]+")


def fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def tokens(text: str) -> list[str]:
    return [t[:STEM_LEN] for t in TOKEN.findall(fold(text)) if len(t) > 1 and t not in STOPWORDS]


def sparse_vector(text: str) -> tuple[list[int], list[float]]:
    """Term-frequency sparse vector; Qdrant applies IDF via the collection's `modifier=idf`."""
    counts = Counter(zlib.crc32(t.encode()) for t in tokens(text))
    if not counts:
        return [], []
    idx = sorted(counts)
    # BM25-like saturation of term frequency (k1=1.2), no length norm.
    return idx, [c * 2.2 / (c + 1.2) for c in (counts[i] for i in idx)]
