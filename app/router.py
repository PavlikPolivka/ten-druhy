"""Decide per message what context to fetch: book excerpts, a web search, the weather.

Similarity scores don't separate small talk from lore questions (both ~0.65 cosine), so a tiny
Flash-Lite call classifies instead. On any failure we fetch nothing; the lore bible still covers basics.
"""

import json
from dataclasses import dataclass

from app import config, llm

SYSTEM = """Rozhoduješ, co si chatbot (postava Ten druhý z knih Jiřího Kulhánka) musí dohledat, než odpoví.

books: ANO jen když se zpráva ptá na děj, postavy, místa, věci nebo vzpomínky z knih (Cesta krve, Noční klub, \
Divocí a zlí, Vládci strachu, Stroncium, Vyhlídka na věčnost…).
weather: ANO když se ptá na počasí, nebo když odpověď na počasí přímo závisí (výlet, kolo, co si vzít na sebe).
web: ANO když odpověď potřebuje aktuální nebo faktické info ze světa, které chatbot nemůže vědět z hlavy: \
otevírací doby, ceny, zprávy, výsledky, události, program, konkrétní fakta o firmách/místech/lidech, „kolik stojí“, \
„kdy hraje“, „co je nového“. NE pro běžný hovor, osobní věci, rady, názory, vtipy, pozdravy.

Vrať JSON: {"books": bool, "book_query": "<krátký dotaz do knih>", "weather": bool, "place": "<obec, nebo prázdné \
= domov>", "web": bool, "web_query": "<krátký vyhledávací dotaz česky, jako do vyhledávače>"}"""


@dataclass
class Route:
    books: bool = False
    book_query: str = ""
    weather: bool = False
    place: str = ""
    web: bool = False
    web_query: str = ""


def route(previous_user: str, message: str) -> Route:
    user = f"Předchozí zpráva uživatele: {previous_user or '-'}\nAktuální zpráva: {message}"
    try:
        o = json.loads(llm.generate(SYSTEM, user, model=config.EXTRACT_MODEL, json_mode=True, temperature=0, patient=False))
        return Route(books=bool(o.get("books")), book_query=o.get("book_query") or message,
                     weather=bool(o.get("weather")), place=(o.get("place") or "").strip(),
                     web=bool(o.get("web")), web_query=o.get("web_query") or message)
    except Exception as e:  # quota, overload, bad JSON
        print(f"  [router] skipped: {e}", flush=True)
        return Route()
