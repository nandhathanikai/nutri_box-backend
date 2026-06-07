import app.models.credit, app.models.delivery
from app.database import SessionLocal
from sqlalchemy import text
from datetime import date

db = SessionLocal()
today = date.today()

db.execute(text(
    "UPDATE users SET latitude = 13.0827, longitude = 80.2707 "
    "WHERE email = 'nandhagopalt@gmail.com'"
))
db.commit()

row = db.execute(text(
    "SELECT s.id, u.full_name, s.start_date, s.end_date "
    "FROM subscriptions s JOIN users u ON u.id = s.customer_id "
    "WHERE u.email = 'nandhagopalt@gmail.com' "
    "AND s.end_date >= '" + str(today) + "'"
)).fetchone()

print('Subscription confirmed:', row[0], row[1], str(row[2]), '->', str(row[3]))
print('GPS set: Chennai 13.0827, 80.2707')
print('DONE - check Admin -> Todays Orders')
db.close()
