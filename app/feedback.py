"""Dump rated exchanges for persona tuning: docker compose exec tendruhy python -m app.feedback [--bad]"""

import sys

from app import sessions

if __name__ == "__main__":
    bad_only = "--bad" in sys.argv
    for x in sessions.rated_exchanges():
        if bad_only and x["rating"] > 0:
            continue
        print(f"{'👍' if x['rating'] > 0 else '👎'} {x['ts']} {x['user']}\n  Ty: {x['message']}\n  TD: {x['reply']}\n")
