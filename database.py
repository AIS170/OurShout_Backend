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
        avatar_url TEXT DEFAULT NULL,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (team_id) REFERENCES teams(team_id),
        FOREIGN KEY (manager_id) REFERENCES employees(employee_id)
    );
    """)
    # Migration: add avatar_url if table was created previously without it
    cursor.execute("PRAGMA table_info(employees);")
    cols = [r["name"] for r in cursor.fetchall()]
    if "avatar_url" not in cols:
        cursor.execute("ALTER TABLE employees ADD COLUMN avatar_url TEXT DEFAULT NULL;")
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

def create_shoutouts_tables():
    """Shout-outs, who received them, who liked them and the comments under them (used by the newsfeed)."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS shoutouts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id TEXT NOT NULL,
        recognition_type TEXT NOT NULL DEFAULT 'INDIVIDUAL',
        target_team_id TEXT,
        principle_id INTEGER NOT NULL,
        reason TEXT NOT NULL,
        impact TEXT NOT NULL,
        act_of_kindness INTEGER NOT NULL DEFAULT 0,
        country TEXT NOT NULL DEFAULT 'AU',
        visibility TEXT NOT NULL DEFAULT 'VISIBLE',
        like_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        edited_at TEXT,
        kind TEXT NOT NULL DEFAULT 'STANDARD',
        scheduled_for TEXT,
        FOREIGN KEY (sender_id) REFERENCES employees(employee_id),
        FOREIGN KEY (target_team_id) REFERENCES teams(team_id),
        FOREIGN KEY (principle_id) REFERENCES principles(id)
    );
    """)
    # kind: STANDARD, or SLT for a shout-out an admin posts on the Senior Leadership Team's behalf.
    # Migration: add it if the table was created previously without it.
    cursor.execute("PRAGMA table_info(shoutouts);")
    existing_cols = [r["name"] for r in cursor.fetchall()]
    if "kind" not in existing_cols:
        cursor.execute("ALTER TABLE shoutouts ADD COLUMN kind TEXT NOT NULL DEFAULT 'STANDARD';")
    if "scheduled_for" not in existing_cols:
        cursor.execute("ALTER TABLE shoutouts ADD COLUMN scheduled_for TEXT DEFAULT NULL;")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS shoutout_recipients (
        shoutout_id INTEGER NOT NULL,
        recipient_id TEXT NOT NULL,
        PRIMARY KEY (shoutout_id, recipient_id),
        FOREIGN KEY (shoutout_id) REFERENCES shoutouts(id),
        FOREIGN KEY (recipient_id) REFERENCES employees(employee_id)
    );
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS likes (
        shoutout_id INTEGER NOT NULL,
        employee_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (shoutout_id, employee_id),
        FOREIGN KEY (shoutout_id) REFERENCES shoutouts(id),
        FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
    );
    """)
    # The feed reads by country + visibility, newest first or most liked first.
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_shoutouts_feed ON shoutouts(country, visibility, created_at DESC, id DESC);"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_shoutouts_liked ON shoutouts(country, visibility, like_count DESC, created_at DESC, id DESC);"
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_shoutouts_sender ON shoutouts(sender_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_recipients_recipient ON shoutout_recipients(recipient_id);")
    # Comments under a shout-out. Deleting a comment removes its row.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS shoutout_comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shoutout_id INTEGER NOT NULL,
        author_id TEXT NOT NULL,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (shoutout_id) REFERENCES shoutouts(id),
        FOREIGN KEY (author_id) REFERENCES employees(employee_id)
    );
    """)
    # A post's comments are read oldest first.
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_comments_shoutout ON shoutout_comments(shoutout_id, created_at, id);"
    )
    conn.commit()
    conn.close()

def create_auction_tables():
    """
    Auction items and the bids on them (points are spent here).
    An item's state comes from the clock: upcoming before starts_at, live until ends_at, then ended.
    Its highest bid leads; once the item has ended, that bid is what the winner spent.
    Timestamps are UTC ISO strings like the shout-outs', so they compare as text.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS auction_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        image_url TEXT,
        starting_bid INTEGER NOT NULL,
        starts_at TEXT NOT NULL,
        ends_at TEXT NOT NULL,
        country TEXT NOT NULL DEFAULT 'AU',
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (created_by) REFERENCES employees(employee_id)
    );
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS auction_bids (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL,
        bidder_id TEXT NOT NULL,
        amount INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (item_id) REFERENCES auction_items(id),
        FOREIGN KEY (bidder_id) REFERENCES employees(employee_id)
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_auction_bids_item ON auction_bids(item_id, amount DESC, id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_auction_bids_bidder ON auction_bids(bidder_id);")
    conn.commit()
    conn.close()

def create_settings_table():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)
    conn.commit()
    conn.close()

def init_db():
    create_teams_table()
    create_employees_table()
    create_principles_table()
    create_shoutouts_tables()
    create_auction_tables()
    create_settings_table()

if __name__ == "__main__":
    init_db()
    print("Tables 'teams', 'employees', 'principles', 'shoutouts', 'shoutout_recipients' and 'likes' created successfully in ourshout.db.")

