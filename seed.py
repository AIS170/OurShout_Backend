import os
from datetime import datetime, timedelta, timezone
from database import get_db, init_db

# 15 Official Sandoz Australia Teams
TEAMS_DATA = [
    ("T01", "Audit & Finance"),
    ("T02", "Commercial & General Management"),
    ("T03", "Communications & Public Affairs"),
    ("T04", "Data Science"),
    ("T05", "Facilities & Administration"),
    ("T06", "Human Resources"),
    ("T07", "Legal & Intellictual Property & Compliance"),
    ("T08", "Market Acess"),
    ("T09", "Marketing"),
    ("T10", "Procurement"),
    ("T11", "Quality"),
    ("T12", "RND"),
    ("T13", "Sales"),
    ("T14", "Technical Operations"),
    ("T15", "Technology Transform")
]

# 5 Official Principles + 1 Retired Test Principle
PRINCIPLES_DATA = [
    (1, "We Think Sandoz", "We think beyond our own department or business unit, asking \"What is best for Sandoz?\"", 1, "ACTIVE"),
    (2, "We are passionate about performance", "We focus on, and execute against, ambitious priorities to drive performance and deliver on our Purpose.", 2, "ACTIVE"),
    (3, "We seek and create clarity", "We make sure everyone understands the context for decisions and actions, and what is expected of them.", 3, "ACTIVE"),
    (4, "We decide smart, do simple", "We make sure everyone knows who decides what, align behind decisions once made, and drive simple, fast execution.", 4, "ACTIVE"),
    (5, "We develop each other", "We encourage and challenge everyone to learn and grow, keeping our careers and our company ahead of the curve.", 5, "ACTIVE"),
    (6, "Retired test principle", "A legacy principle retired from active recognition to test form validation.", 6, "RETIRED")
]

# 55 AU Employees: (employee_id, employee_name, email_id, team_id, manager_id, country, job_title, role, status)
# status values: 'ACTIVE' | 'SUSPENDED' | 'INACTIVE'
EMPLOYEES_DATA = [
    # T02: Commercial & General Management
    ("E0001", "Marcus Vance", "marcus.vance@sandoz.test", "T02", None, "AU", "Country President - Australia & New Zealand", "EMPLOYEE", "ACTIVE"),
    ("E0002", "Chloe Bennett", "chloe.bennett@sandoz.test", "T02", "E0001", "AU", "Commercial Operations Director", "EMPLOYEE", "ACTIVE"),
    ("E0011", "Olivia Chen", "olivia.chen@sandoz.test", "T02", "E0002", "AU", "Head of Commercial & Biosimilars", "EMPLOYEE", "ACTIVE"),
    ("E0015", "Lucas Martin", "lucas.martin@sandoz.test", "T02", "E0011", "AU", "Commercial Strategy Lead", "EMPLOYEE", "ACTIVE"),

    # T13: Sales
    ("E0003", "Liam Cooper", "liam.cooper@sandoz.test", "T13", "E0002", "AU", "Sales Director", "EMPLOYEE", "ACTIVE"),
    ("E0004", "Emily Watson", "emily.watson@sandoz.test", "T13", "E0003", "AU", "Senior Key Account Manager", "EMPLOYEE", "ACTIVE"),
    ("E0005", "Priya Raman", "priya.raman@sandoz.test", "T13", "E0004", "AU", "Retail Pharmacy Sales Specialist", "EMPLOYEE", "ACTIVE"),
    ("E0008", "Ryan Mitchell", "ryan.mitchell@sandoz.test", "T13", "E0004", "AU", "Retail Channel Specialist", "EMPLOYEE", "ACTIVE"),
    ("E0009", "Grace Kelly", "grace.kelly@sandoz.test", "T13", "E0004", "AU", "Field Sales Representative", "EMPLOYEE", "ACTIVE"),
    ("E0012", "Samuel Wilson", "samuel.wilson@sandoz.test", "T13", "E0011", "AU", "Senior Biosimilars Sales Specialist", "EMPLOYEE", "ACTIVE"),
    ("E0013", "Aisha Rahman", "aisha.rahman@sandoz.test", "T13", "E0011", "AU", "Hospital Account Manager", "EMPLOYEE", "ACTIVE"),
    ("E0014", "Sarah Nguyen", "sarah.nguyen.sales@sandoz.test", "T13", "E0011", "AU", "Hospital Account Specialist", "EMPLOYEE", "ACTIVE"),
    ("E0016", "Mia Anderson", "mia.anderson@sandoz.test", "T13", "E0011", "AU", "Oncology Portfolio Specialist", "EMPLOYEE", "ACTIVE"),

    # T05: Facilities & Administration
    ("E0006", "Jack Davies", "jack.davies@sandoz.test", "T05", "E0001", "AU", "Facilities & Office Services Manager", "EMPLOYEE", "ACTIVE"),
    ("E0007", "Jessica Taylor", "jessica.taylor@sandoz.test", "T05", "E0006", "AU", "Administration Coordinator", "EMPLOYEE", "ACTIVE"),

    # T10: Procurement
    ("E0010", "Ethan Brown", "ethan.brown@sandoz.test", "T10", "E0002", "AU", "Procurement Operations Specialist", "EMPLOYEE", "ACTIVE"),
    ("E0020", "Thomas Harris", "thomas.harris@sandoz.test", "T10", "E0010", "AU", "Strategic Sourcing Analyst", "EMPLOYEE", "ACTIVE"),

    # T14: Technical Operations
    ("E0017", "Oliver Smith", "oliver.smith@sandoz.test", "T14", "E0001", "AU", "Head of Technical Operations", "EMPLOYEE", "ACTIVE"),
    ("E0018", "Arjun Patel", "arjun.patel@sandoz.test", "T14", "E0017", "AU", "Logistics & Warehouse Coordinator", "EMPLOYEE", "ACTIVE"),
    ("E0028", "Daniel Green", "daniel.green@sandoz.test", "T14", "E0017", "AU", "Technical Operations Analyst", "EMPLOYEE", "ACTIVE"),
    ("E0029", "Oliver Grant", "oliver.grant@sandoz.test", "T14", "E0017", "AU", "Supply Chain & Operations Planner", "EMPLOYEE", "SUSPENDED"),

    # T11: Quality
    ("E0019", "Zoe Martin", "zoe.martin@sandoz.test", "T11", "E0017", "AU", "Quality Assurance Associate", "EMPLOYEE", "ACTIVE"),
    ("E0030", "Isabella Scott", "isabella.scott@sandoz.test", "T11", "E0019", "AU", "Quality Control Specialist", "EMPLOYEE", "ACTIVE"),

    # T07: Legal & Intellictual Property & Compliance
    ("E0021", "Sarah Nguyen", "sarah.nguyen.legal@sandoz.test", "T07", "E0022", "AU", "Compliance & IP Specialist", "EMPLOYEE", "ACTIVE"),
    ("E0022", "James Wilson", "james.wilson@sandoz.test", "T07", "E0001", "AU", "Head of Legal, IP & Compliance", "EMPLOYEE", "ACTIVE"),
    ("E0023", "Emma Roberts", "emma.roberts@sandoz.test", "T07", "E0022", "AU", "Legal Counsel", "EMPLOYEE", "ACTIVE"),
    ("E0054", "Victoria Simmons", "victoria.simmons@sandoz.test", "T07", "E0022", "AU", "Compliance Operations Associate", "EMPLOYEE", "ACTIVE"),

    # T12: RND
    ("E0024", "William Turner", "william.turner@sandoz.test", "T12", "E0001", "AU", "R&D Operations Director", "EMPLOYEE", "ACTIVE"),
    ("E0025", "Charlotte White", "charlotte.white@sandoz.test", "T12", "E0024", "AU", "Senior Clinical Research Scientist", "EMPLOYEE", "ACTIVE"),
    ("E0027", "Amelia King", "amelia.king@sandoz.test", "T12", "E0024", "AU", "Medical Science Researcher", "EMPLOYEE", "ACTIVE"),
    ("E0031", "Henry Hall", "henry.hall@sandoz.test", "T12", "E0024", "AU", "Clinical Trial Coordinator", "EMPLOYEE", "ACTIVE"),
    ("E0032", "Benjamin Clarke", "benjamin.clarke@sandoz.test", "T12", "E0024", "AU", "Former Clinical Researcher", "EMPLOYEE", "INACTIVE"),

    # T03: Communications & Public Affairs
    ("E0026", "Noah Evans", "noah.evans@sandoz.test", "T03", "E0001", "AU", "Communications & Media Manager", "EMPLOYEE", "ACTIVE"),
    ("E0052", "Hannah Russell", "hannah.russell@sandoz.test", "T03", "E0026", "AU", "Public Affairs Partner", "EMPLOYEE", "ACTIVE"),

    # T01: Audit & Finance
    ("E0033", "Alexander Adams", "alexander.adams@sandoz.test", "T01", "E0001", "AU", "Head of Audit & Finance", "EMPLOYEE", "ACTIVE"),
    ("E0034", "Sophia Campbell", "sophia.campbell@sandoz.test", "T01", "E0033", "AU", "Senior Financial Analyst", "EMPLOYEE", "ACTIVE"),
    ("E0035", "Mason Phillips", "mason.phillips@sandoz.test", "T01", "E0033", "AU", "Senior Internal Auditor", "EMPLOYEE", "ACTIVE"),
    ("E0036", "Daniel Taylor", "daniel.taylor@sandoz.test", "T01", "E0033", "AU", "Former Finance Associate", "EMPLOYEE", "INACTIVE"),
    ("E0038", "Logan Brooks", "logan.brooks@sandoz.test", "T01", "E0033", "AU", "Financial Controller", "EMPLOYEE", "ACTIVE"),

    # T08: Market Acess
    ("E0037", "Ava Parker", "ava.parker@sandoz.test", "T08", "E0002", "AU", "Market Access Strategy Lead", "EMPLOYEE", "ACTIVE"),
    ("E0053", "David Patterson", "david.patterson@sandoz.test", "T08", "E0037", "AU", "Health Economics & Pricing Manager", "EMPLOYEE", "ACTIVE"),

    # T06: Human Resources
    ("E0039", "Natalie Moreau", "natalie.moreau@sandoz.test", "T06", "E0001", "AU", "Head of Human Resources", "ADMIN", "ACTIVE"),
    ("E0040", "Jacob Wood", "jacob.wood@sandoz.test", "T06", "E0039", "AU", "Talent Acquisition Lead", "EMPLOYEE", "ACTIVE"),
    ("E0041", "Harper Price", "harper.price@sandoz.test", "T06", "E0039", "AU", "HR Business Partner", "EMPLOYEE", "ACTIVE"),
    ("E0042", "Michael Barnes", "michael.barnes@sandoz.test", "T06", "E0039", "AU", "People Experience Specialist", "EMPLOYEE", "ACTIVE"),
    ("E0043", "Ella Ward", "ella.ward@sandoz.test", "T06", "E0039", "AU", "Diversity & Inclusion Lead", "EMPLOYEE", "ACTIVE"),

    # T15: Technology Transform
    ("E0044", "David Novak", "david.novak@sandoz.test", "T15", "E0001", "AU", "Director of Technology Transform", "ADMIN", "ACTIVE"),
    ("E0045", "Benjamin Hughes", "benjamin.hughes@sandoz.test", "T15", "E0044", "AU", "Cloud Systems Infrastructure Lead", "EMPLOYEE", "ACTIVE"),
    ("E0046", "Scarlett Foster", "scarlett.foster@sandoz.test", "T15", "E0044", "AU", "Enterprise Tech Specialist", "EMPLOYEE", "ACTIVE"),
    ("E0047", "Jackson Ross", "jackson.ross@sandoz.test", "T15", "E0044", "AU", "Digital Solutions Architect", "EMPLOYEE", "ACTIVE"),

    # T09: Marketing
    ("E0048", "Evelyn Powell", "evelyn.powell@sandoz.test", "T09", "E0001", "AU", "Marketing Director", "EMPLOYEE", "ACTIVE"),
    ("E0049", "Aiden Jenkins", "aiden.jenkins@sandoz.test", "T09", "E0048", "AU", "Brand Strategy Lead", "EMPLOYEE", "ACTIVE"),
    ("E0050", "Lily Perry", "lily.perry@sandoz.test", "T09", "E0048", "AU", "Product Marketing Specialist", "EMPLOYEE", "ACTIVE"),
    ("E0051", "Matthew Butler", "matthew.butler@sandoz.test", "T09", "E0048", "AU", "Digital Marketing Specialist", "EMPLOYEE", "ACTIVE"),

    # T04: Data Science
    ("E0055", "Christopher Foster", "christopher.foster@sandoz.test", "T04", "E0044", "AU", "Senior Data Scientist", "EMPLOYEE", "ACTIVE")
]

# Demo shout-outs for the newsfeed. "days_ago" is counted back from the moment you seed, so the
# feed always looks recent. Use either "to" (hand-picked people) or "team" (every active member
# of that team except the sender). "liked_by" lists the employees who liked the post.
SHOUTOUTS_DATA = [
    {"from": "E0013", "to": ["E0005"], "principle": 5, "kindness": True, "days_ago": 0.4,
     "reason": "Priya spent her lunch break walking me through the new pharmacy ordering portal.",
     "impact": "I can now answer my customers' questions myself instead of escalating them.",
     "liked_by": ["E0011", "E0003", "E0004", "E0039", "E0016", "E0012"]},
    {"from": "E0005", "to": ["E0013"], "principle": 1, "kindness": True, "days_ago": 1.2,
     "reason": "Aisha jumped in to help Retail with a hospital stock question that wasn't her job at all.",
     "impact": "Two pharmacies got their biosimilar orders on time instead of a week late.",
     "liked_by": ["E0011", "E0003", "E0008", "E0009"]},
    {"from": "E0048", "to": ["E0049", "E0050"], "principle": 2, "kindness": False, "days_ago": 2.1,
     "reason": "Aiden and Lily rebuilt the launch pack in four days after the brief changed late.",
     "impact": "Sales had the new material in hand before the first customer meetings.",
     "liked_by": ["E0051", "E0003", "E0011"]},
    {"from": "E0005", "team": "T06", "principle": 2, "kindness": False, "days_ago": 5.0, "edited": True,
     "reason": "The team ran every onboarding session in October, even with two people on leave. \"Whatever it takes\" & then some!",
     "impact": "All twelve new starters had their laptops, logins and a buddy on day one.",
     "liked_by": ["E0005", "E0013", "E0011", "E0001", "E0002", "E0044", "E0048", "E0033", "E0017"]},
    {"from": "E0013", "to": ["E0005"], "principle": 2, "kindness": False, "days_ago": 6.3,
     "reason": "Priya chased down three overdue pharmacy orders in one afternoon.",
     "impact": "Every order shipped the next morning and the customers stayed with us.",
     "liked_by": ["E0004", "E0003"]},
    {"from": "E0005", "to": ["E0013"], "principle": 3, "kindness": False, "days_ago": 8.5,
     "reason": "Aisha wrote a one-page summary of the new hospital tender rules.",
     "impact": "The whole Sales team now quotes the same terms.",
     "liked_by": ["E0011", "E0012", "E0016"]},
    {"from": "E0039", "to": ["E0005", "E0013", "E0011", "E0018", "E0019"], "principle": 3, "kindness": True, "days_ago": 11.0,
     "reason": "You five wrote the one-page guide to the new leave policy that everyone actually read.",
     "impact": "Questions to Human Resources dropped by half in the first fortnight.",
     "liked_by": ["E0005", "E0040", "E0041", "E0042", "E0043", "E0001", "E0002", "E0044", "E0033", "E0048", "E0017", "E0024"]},
    {"from": "E0013", "to": ["E0005"], "principle": 1, "kindness": True, "days_ago": 13.2,
     "reason": "Priya covered my hospital visits while I was at the conference.",
     "impact": "No customer went a week without hearing from us.",
     "liked_by": ["E0011"]},
    {"from": "E0005", "to": ["E0013"], "principle": 5, "kindness": False, "days_ago": 15.6,
     "reason": "Aisha coached me through my first hospital formulary presentation.",
     "impact": "I ran the next one on my own and the pharmacy director asked for a follow-up.",
     "liked_by": ["E0004", "E0011", "E0003"]},
    {"from": "E0011", "to": ["E0013"], "principle": 4, "kindness": False, "days_ago": 20.0,
     "reason": "Aisha noticed that three hospitals were ordering the same biosimilar through different contracts, pulled the numbers together over a weekend, and brought a single proposal to the Monday meeting. She had already spoken to each account lead, so nobody was surprised and the decision took ten minutes instead of the usual three rounds of email.",
     "impact": "One contract now covers all three hospitals. Pricing is consistent, the pharmacy teams reorder from one form, and we freed up about a day a month that used to go on reconciling invoices between the three agreements.",
     "liked_by": ["E0002", "E0001"]},
    {"from": "E0018", "to": ["E0019"], "principle": 1, "kindness": True, "days_ago": 28.0,
     "reason": "Zoe stayed back to recheck a pallet that had sat outside the cold chain for a few minutes.",
     "impact": "We shipped with confidence and the customer never saw a delay.",
     "liked_by": ["E0017", "E0030", "E0028"]},
    {"from": "E0019", "to": ["E0018"], "principle": 5, "kindness": False, "days_ago": 35.0,
     "reason": "Arjun taught me how the warehouse system flags short-dated stock.",
     "impact": "I caught two batches before they reached the release queue.",
     "liked_by": ["E0017"]},
    {"from": "E0044", "to": ["E0055"], "principle": 2, "kindness": False, "days_ago": 46.0,
     "reason": "Christopher rebuilt the weekly sales forecast so it runs in minutes, not hours.",
     "impact": "Sales leads now get Monday numbers before their 9am meeting.",
     "liked_by": ["E0003", "E0011", "E0045", "E0046", "E0047", "E0002", "E0033"]},
    {"from": "E0011", "to": ["E0005"], "principle": 3, "kindness": False, "days_ago": 61.0,
     "reason": "Priya wrote up the pharmacy feedback from her September visits in one clear page.",
     "impact": "Marketing changed the launch pack based on it.",
     "liked_by": ["E0048", "E0049", "E0003", "E0004", "E0013"]},
]

def seed_shoutouts(cursor):
    """Loads the demo shout-outs, their recipients and their likes."""
    now = datetime.now(timezone.utc).replace(microsecond=0)

    def iso(moment):
        return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    for post in SHOUTOUTS_DATA:
        sender = post["from"]
        team_id = post.get("team")
        if team_id:
            recipients = [
                row["employee_id"] for row in cursor.execute(
                    "SELECT employee_id FROM employees WHERE team_id = ? AND status = 'ACTIVE' AND employee_id != ?",
                    (team_id, sender)
                ).fetchall()
            ]
        else:
            recipients = post["to"]

        created = now - timedelta(days=post["days_ago"])
        edited = iso(created + timedelta(minutes=30)) if post.get("edited") else None
        liked_by = post.get("liked_by", [])

        cursor.execute("""
            INSERT INTO shoutouts (sender_id, recognition_type, target_team_id, principle_id, reason, impact,
                                   act_of_kindness, country, visibility, like_count, created_at, edited_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'AU', 'VISIBLE', ?, ?, ?)
        """, (
            sender, "TEAM" if len(recipients) > 1 else "INDIVIDUAL", team_id, post["principle"],
            post["reason"], post["impact"], 1 if post["kindness"] else 0, len(liked_by), iso(created), edited
        ))
        shoutout_id = cursor.lastrowid

        cursor.executemany(
            "INSERT INTO shoutout_recipients (shoutout_id, recipient_id) VALUES (?, ?)",
            [(shoutout_id, recipient) for recipient in recipients]
        )
        cursor.executemany(
            "INSERT INTO likes (shoutout_id, employee_id, created_at) VALUES (?, ?, ?)",
            [(shoutout_id, liker, iso(created + timedelta(hours=2))) for liker in liked_by]
        )

def seed_database():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = OFF;")

    cursor.execute("DROP TABLE IF EXISTS likes;")
    cursor.execute("DROP TABLE IF EXISTS shoutout_recipients;")
    cursor.execute("DROP TABLE IF EXISTS shoutouts;")
    cursor.execute("DROP TABLE IF EXISTS app_users;")
    cursor.execute("DROP TABLE IF EXISTS employees;")
    cursor.execute("PRAGMA foreign_keys = ON;")
    conn.commit()

    init_db()

    cursor.execute("PRAGMA foreign_keys = OFF;")

    print("🌱 Seeding Sandoz Australia teams (15 official teams)...")
    cursor.executemany("""
        INSERT OR REPLACE INTO teams (team_id, team_name)
        VALUES (?, ?)
    """, TEAMS_DATA)

    print("🌱 Seeding Sandoz Way principles...")
    cursor.executemany("""
        INSERT OR REPLACE INTO principles (id, name, description, display_order, status)
        VALUES (?, ?, ?, ?, ?)
    """, PRINCIPLES_DATA)

    print("🌱 Seeding 55 AU employees (status: ACTIVE / SUSPENDED / INACTIVE)...")
    cursor.executemany("""
        INSERT OR REPLACE INTO employees (employee_id, employee_name, email_id, team_id, manager_id, country, job_title, role, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, EMPLOYEES_DATA)

    print(f"🌱 Seeding {len(SHOUTOUTS_DATA)} demo shout-outs with recipients and likes...")
    seed_shoutouts(cursor)

    cursor.execute("PRAGMA foreign_keys = ON;")
    conn.commit()
    conn.close()
    print("✅ Seed completed successfully with single clean status column!")

if __name__ == "__main__":
    seed_database()
