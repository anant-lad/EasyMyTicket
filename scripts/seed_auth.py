"""
Seed auth credentials:
- Assign real emails to TECH001 (anantlad66) and TECH002 (anantlad0628, admin)
- Set bcrypt passwords for all 8 technicians
- Create 2 users
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from src.auth.password import hash_password
from src.database.db_connection import DatabaseConnection

db = DatabaseConnection()

# ── Technician passwords ────────────────────────────────────────────────────
tech_updates = [
    # (tech_id, new_email,                   password,             is_admin)
    ("TECH001", "anantlad66@gmail.com",      "EasyMT@Tech66",      False),
    ("TECH002", "anantlad0628@gmail.com",    "EasyMT@Admin2024",   True),
    ("TECH003", "carol.davis@company.com",   "EasyMT@Tech123",     False),
    ("TECH004", "david.kim@company.com",     "EasyMT@Tech123",     False),
    ("TECH005", "emma.wilson@company.com",   "EasyMT@Tech123",     False),
    ("TECH006", "frank.lee@company.com",     "EasyMT@Tech123",     False),
    ("TECH007", "grace.patel@company.com",   "EasyMT@Tech123",     False),
    ("TECH008", "henry.chen@company.com",    "EasyMT@Tech123",     False),
]

for tech_id, email, password, is_admin in tech_updates:
    hashed = hash_password(password)
    db.execute_query(
        "UPDATE technician_data SET tech_mail=%s, tech_password=%s, is_admin=%s WHERE tech_id=%s",
        (email, hashed, is_admin, tech_id), fetch=False,
    )
    role = "ADMIN" if is_admin else "tech"
    print(f"  [{role}] {tech_id} → {email}  password={password}")

# ── Users ───────────────────────────────────────────────────────────────────
users = [
    ("USR001", "Anant SRTTC",  "anant.221269@srttc.ai.in", "EasyMT@User221"),
    ("USR002", "Anant Lad",    "ladanant09@gmail.com",      "EasyMT@User09"),
]

for user_id, name, email, password in users:
    hashed = hash_password(password)
    db.execute_query(
        """INSERT INTO user_data (user_id, user_name, user_mail, user_password, no_tickets_raised, available)
           VALUES (%s,%s,%s,%s,0,TRUE)
           ON CONFLICT (user_id) DO UPDATE
           SET user_name=%s, user_mail=%s, user_password=%s""",
        (user_id, name, email, hashed, name, email, hashed),
        fetch=False,
    )
    print(f"  [user] {user_id} → {email}  password={password}")

print("\nDone! Credential summary:")
print("=" * 60)
print(f"{'Role':<8} {'Email':<35} {'Password'}")
print("-" * 60)
for tech_id, email, pwd, is_admin in tech_updates:
    role = "admin" if is_admin else "tech"
    print(f"{role:<8} {email:<35} {pwd}")
for uid, name, email, pwd in users:
    print(f"{'user':<8} {email:<35} {pwd}")
print("=" * 60)
