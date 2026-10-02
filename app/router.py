"""Decide per message whether book excerpts are worth retrieving.

Similarity scores don't separate small talk from lore questions (both ~0.65 cosine), so a tiny
Flash-Lite call classifies instead. On any failure we skip retrieval; the lore bible still covers basics.
"""

import json

from app import config, llm

SYSTEM = """Rozhoduješ, jestli chatbot (postava Ten druhý z knih Jiřího Kulhánka) potřebuje k odpovědi \
dohledat konkrétní pasáže z knih. ANO jen když se zpráva ptá na děj, postavy, místa, věci nebo vzpomínky \
z knih (Cesta krve, Noční klub, Divocí a zlí, Vládci strachu, Stroncium, Vyhlídka na věčnost…). \
NE pro běžný hovor, osobní věci uživatele, rady, názory, vtipy, pozdravy.
Vrať JSON: {"books": true|false, "query": "<krátký vyhledávací dotaz česky, pokud books=true, jinak prázdné>"}"""


def route(previous_user: str, message: str) -> tuple[bool, str]:
    user = f"Předchozí zpráva uživatele: {previous_user or '-'}\nAktuální zpráva: {message}"
    try:
        out = json.loads(llm.generate(SYSTEM, user, model=config.EXTRACT_MODEL, json_mode=True, temperature=0, patient=False))
        return bool(out.get("books")), (out.get("query") or message)
    except Exception as e:  # quota, overload, bad JSON
        print(f"  [router] skipped: {e}", flush=True)
        return False, message
