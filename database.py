import sqlite3
import os

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "ourshout.db")

def get_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def create_teams_table():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS teams (
        team_id TEXT PRIMARY KEY,
        team_name TEXT NOT NULL
    );
    """)
    conn.commit()
    conn.close()

def create_employees_table():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS employees (
        employee_id TEXT PRIMARY KEY,
        employee_name TEXT NOT NULL,
        email_id TEXT UNIQUE NOT NULL,
        team_id TEXT NOT NULL,
        manager_id TEXT,
        country TEXT DEFAULT 'AU',
        job_title TEXT,
        role TEXT DEFAULT 'EMPLOYEE',
        status TEXT DEFAULT 'ACTIVE',
        FOREIGN KEY (team_id) REFERENCES teams(team_id),
        FOREIGN KEY (manager_id) REFERENCES employees(employee_id)
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_employees_team ON employees(team_id);")
    conn.commit()
    conn.close()

def create_principles_table():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS principles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT NOT NULL,
        display_order INTEGER NOT NULL,
        status TEXT DEFAULT 'ACTIVE'
    );
    """)
    conn.commit()
    conn.close()

def init_db():
    create_teams_table()
    create_employees_table()
    create_principles_table()

if __name__ == "__main__":
    init_db()
    print("Tables 'teams', 'employees', and 'principles' created successfully in ourshout.db.")

