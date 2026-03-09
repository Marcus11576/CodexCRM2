import sqlite3
import json

def check_person():
    conn = sqlite3.connect('crm.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM PERSON WHERE email_primary LIKE '%james.allan%'")
    row = c.fetchone()
    if row:
        print("PERSON FOUND:")
        print(f"ID: {row['person_id']}")
        print(f"Name: {row['full_name']}")
        print(f"Email: {repr(row['email_primary'])}")
        print(f"Phone: {repr(row['phone_primary'])}")
    else:
        print("PERSON NOT FOUND")
    conn.close()

if __name__ == "__main__":
    check_person()
