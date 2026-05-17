import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.database import SessionLocal
from app.routers.credits import get_credits_overview

db = SessionLocal()
try:
    # We pass None for admin to bypass auth in direct call, assuming it's not used
    res = get_credits_overview(db=db, admin=None)
    print("Overview success:", len(res))
except Exception as e:
    import traceback
    traceback.print_exc()
finally:
    db.close()
