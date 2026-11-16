# OurShout — Backend (Python / Flask / SQLite)

Backend service for **OurShout**, a peer-recognition prototype for Sandoz Australia built with Python (Flask) and SQLite.

---

## 1. Prerequisites

- **Python 3.10+** (Python 3.13 recommended)
- `pip` (Python package manager)

---

## 2. Environment Setup

### Create and Activate Virtual Environment

From the `OurShout_Backend` directory:

#### On macOS / Linux:
```bash
python3 -m venv venv
source venv/bin/activate
```

#### On Windows (Command Prompt / PowerShell):
```cmd
python -m venv venv
venv\Scripts\activate
```

---

## 3. Install Dependencies

Install the required packages defined in `requirements.txt`:

```bash
pip install -r requirements.txt
```

### Packages Installed:
- **`Flask`**: REST API framework, request handling, routing, and error management.
- **`flask-cors`**: Cross-Origin Resource Sharing handling for the Vite frontend (`localhost:5173`).
- **`PyJWT`**: JWT verification and creation for Entra ID single-tenant mock simulation (HS256).
- **`python-dotenv`**: Environment variable loading from `.env`.
- *Built-in Standard Libraries*: `sqlite3` (database engine), `hashlib`, `re`, `json`, `datetime`, `threading`.

---

## 4. Configuration (`.env`)

A default `.env` file can be placed in `OurShout_Backend/.env` with the following variables:

```ini
PORT=3001
JWT_SECRET=sandoz-mock-jwt-secret-key-2026
TENANT_ID=sandoz-mock-tenant
DATABASE_PATH=data/ourshout.db
ADAPTER_MODE=mock
```

- **`PORT`**: API port (default: `3001`, matching the Vite proxy).
- **`TENANT_ID`**: Validated on every authenticated call to enforce the single-tenant requirement (`sandoz-mock-tenant`).
- **`ADAPTER_MODE`**: `mock` uses the local SQLite directory & mock mailer with simulated outage support. Setting to `azure` selects the Microsoft Graph and Azure Content Safety adapter stubs for enterprise handover.

---

## 5. Seed the Database

To create the SQLite database schema and load initial teams, employees, principles, and demo shout-outs:

```bash
python seed.py
```

This will initialize `data/ourshout.db` with 55 employees, 10 teams, 5 official principles, demo recognition cards, reciprocal alerts, and outbox email items.

---

## 6. Running the Server

Start the Flask development server on port 3001:

```bash
python app.py
```

The API will be available at: `http://localhost:3001`
- Test personas endpoint: `http://localhost:3001/api/auth/personas`
- Health check / user profile: `http://localhost:3001/api/me` (requires Bearer token)

