# Database Liveness (PostgreSQL/MySQL)

This app provides a simple database connection and liveness check for PostgreSQL or MySQL, selected by environment variable, with detailed error messages.

## Environment variables

- `DB_TYPE`: `postgresql` (default) or `mysql`
- `DB_HOST`: Hostname (default `localhost`)
- `DB_PORT`: Port (default `5432` for PostgreSQL, `3306` for MySQL)
- `DB_USER`: Username
- `DB_PASSWORD`: Password
- `DB_NAME`: Database name (default `postgres` for PostgreSQL, `mysql` for MySQL)

## How to run

- Install dependencies:

```powershell
# From the workspace root
pip install -r requirements.txt
```

- Start the server (default behavior):

```powershell
python app.py
```

- Health endpoint:

```text
GET /db/health
```
Returns 200 with details on success, or 503 with an error payload on failure. Passwords are never printed.

- CLI liveness check:

```powershell
python app.py check
```
Returns exit code 0 on success, 2 on failure. Prints a JSON payload with details either way.

- Explicitly run the server via CLI:

```powershell
python app.py serve --host 0.0.0.0 --port 5000
```

## Drivers

- PostgreSQL: `psycopg2-binary`
- MySQL: `PyMySQL`

If you see an error like `NoSuchModuleError`, install the missing driver (these are already in `requirements.txt`).

## Notes

- The liveness query uses `SELECT 1`, which works for both PostgreSQL and MySQL.
- The connection string is built with SQLAlchemy and printed with the password hidden.
