"""Registry of source books: raw filename -> metadata."""

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
TEXT = ROOT / "data" / "text"
DERIVED = ROOT / "data" / "derived"


@dataclass(frozen=True)
class Book:
    slug: str
    title: str
    year: int
    raw: str
    core: bool = False  # Ten druhý is a significant character in this book


BOOKS = [
    Book("vladci-strachu", "Vládci strachu", 1995, "Kulhanek Jiri - 1995 - Vladci strachu.doc"),
    Book("ck1-dobrak", "Cesta krve I. – Dobrák", 1996, "Kulhanek_Jiri_1996_Cesta_krve_(1.cast)_Dobrak.doc", core=True),
    Book("ck2-cynik", "Cesta krve II. – Cynik", 1997, "Kulhanek_Jiri_1997_Cesta_krve_(2.cast)_Cynik.doc", core=True),
    Book("daz1-cas-mrtvych", "Divocí a zlí I. – Čas mrtvých", 1999, "Kulhanek_Jiri_1999_Divoci_a_zli_(1.cast)_Cas_mrtvych.doc"),
    Book("daz2-hardcore", "Divocí a zlí II. – Hardcore", 1999, "Kulhanek_Jiri_1999_Divoci_a_zli_(2.cast)_Hardcore.doc"),
    Book("daz3-temny-prorok", "Divocí a zlí III. – Temný prorok", 2000, "Kulhanek_Jiri_2000_Divoci_a_zli_(3.cast)_Temny_prorok.doc"),
    Book("daz4-krize", "Divocí a zlí IV. – Kříže", 2000, "Kulhanek_Jiri_2000_Divoci_a_zli_(4.cast)_Krize.doc"),
    Book("nk1", "Noční klub – díl první", 2002, "Kulhanek_Jiri_2002_Nocni_klub_(1.dil).doc", core=True),
    Book("nk2", "Noční klub – díl druhý", 2003, "Kulhanek_Jiri_2003_Nocni_klub_(2.dil).doc", core=True),
    Book("povidky", "Povídky", 1994, "Kulhanek-Jiri-(cca1994)-Povidky-(v-2024).docx"),
    Book("soulacka", "Šoulačka", 1994, "Kulhanek-Jiri-(cca1994)-Soulacka.docx"),
    Book("stroncium", "Stroncium", 2006, "Kulhanek-Jiri-2006-Stroncium.txt"),
    Book("vyhlidka-na-vecnost", "Vyhlídka na věčnost", 2011, "Kulhanek-Jiri-2011-Vyhlidka-na-vecnost.txt"),
]

BY_SLUG = {b.slug: b for b in BOOKS}
