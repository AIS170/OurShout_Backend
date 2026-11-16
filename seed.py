import os
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

def seed_database():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = OFF;")

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

    cursor.execute("PRAGMA foreign_keys = ON;")
    conn.commit()
    conn.close()
    print("✅ Seed completed successfully with single clean status column!")

if __name__ == "__main__":
    seed_database()
