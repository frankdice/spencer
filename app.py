import os
import sys
import json
from typing import Optional, Tuple

from flask import Flask, jsonify, make_response

# Optional imports guarded to provide helpful errors if missing
try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import URL
    from sqlalchemy.exc import (
        SQLAlchemyError,
        NoSuchModuleError,
        OperationalError,
        ProgrammingError,
        ArgumentError,
    )
except Exception as import_err:  # Broad on purpose to surface helpful guidance later
    create_engine = None  # type: ignore
    URL = None  # type: ignore
    text = None  # type: ignore
    SQLAlchemyError = Exception  # type: ignore
    NoSuchModuleError = Exception  # type: ignore
    OperationalError = Exception  # type: ignore
    ProgrammingError = Exception  # type: ignore
    ArgumentError = Exception  # type: ignore
    _sqlalchemy_import_error = import_err
else:
    _sqlalchemy_import_error = None


app = Flask(__name__)


def _get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Fetch an environment variable with fallback and strip whitespace."""
    val = os.getenv(key)
    return (val.strip() if isinstance(val, str) else default)


def _normalize_db_type(db_type: Optional[str]) -> str:
    if not db_type:
        return "postgresql"
    v = db_type.strip().lower()
    if v in ("postgres", "postgresql", "pgsql", "psql"):
        return "postgresql"
    if v in ("mysql",):
        return "mysql"
    # Fallback to postgres if unknown
    return "postgresql"


def build_db_url_from_env() -> Tuple[str, dict]:
    """
    Build a SQLAlchemy URL string from environment variables.

    Environment variables:
      - DB_TYPE: postgresql (default) | mysql
      - DB_HOST: host name (default localhost)
      - DB_PORT: numeric port (default 5432 for postgres, 3306 for mysql)
      - DB_USER: database user
      - DB_PASSWORD: database password
      - DB_NAME: database name (default 'postgres' for postgres, 'mysql' for mysql)

    Returns a tuple of (safe_url_string, details_dict) where the URL hides password.
    """
    db_type = _normalize_db_type(_get_env("DB_TYPE", "postgresql"))
    is_pg = db_type == "postgresql"

    host = _get_env("DB_HOST", "localhost") or "localhost"
    port = _get_env("DB_PORT", "5432" if is_pg else "3306")
    # Ensure port is numeric string
    port = str(port) if port is not None else ("5432" if is_pg else "3306")
    user = _get_env("DB_USER", None)
    password = _get_env("DB_PASSWORD", None)
    dbname = _get_env("DB_NAME", "postgres" if is_pg else "mysql")

    # Choose driver explicitly to ensure helpful errors when missing
    drivername = "postgresql+psycopg2" if is_pg else "mysql+pymysql"

    if URL is None:  # SQLAlchemy not imported
        raise RuntimeError(
            "SQLAlchemy is not installed. Please install dependencies first."
        )

    url = URL.create(
        drivername=drivername,
        username=user,
        password=password,
        host=host,
        port=int(port),
        database=dbname,
    )

    safe_url = url.render_as_string(hide_password=True)
    details = {
        "db_type": db_type,
        "driver": drivername,
        "host": host,
        "port": int(port),
        "database": dbname,
        "username": user,
        "url": safe_url,
    }
    return safe_url, details


def create_engine_from_env():
    """Create a SQLAlchemy engine using env vars and return (engine, details)."""
    if _sqlalchemy_import_error:
        raise RuntimeError(
            "Failed to import SQLAlchemy. Install requirements and retry."
        ) from _sqlalchemy_import_error

    safe_url, details = build_db_url_from_env()

    # Re-create a URL object from its string representation (password is hidden though).
    # Instead, rebuild from the details for the real engine URL.
    db_type = details["db_type"]
    driver = details["driver"]
    from sqlalchemy.engine import URL as _URL

    real_url = _URL.create(
        drivername=driver,
        username=details["username"],
        password=_get_env("DB_PASSWORD", None),  # real password (may be None)
        host=details["host"],
        port=details["port"],
        database=details["database"],
    )

    engine = create_engine(real_url, pool_pre_ping=True, future=True)
    return engine, details


def check_db_liveness() -> Tuple[bool, dict]:
    """Attempt a liveness query (SELECT 1). Returns (ok, payload_dict)."""
    try:
        engine, details = create_engine_from_env()
    except NoSuchModuleError as e:
        # Likely missing driver package
        msg = (
            f"Database driver not found for URL '{str(e)}'. "
            "Install the appropriate driver: psycopg2-binary for PostgreSQL, or PyMySQL for MySQL."
        )
        return False, {"error": "NoSuchModuleError", "message": msg}
    except ArgumentError as e:
        return False, {
            "error": "ArgumentError",
            "message": str(e),
            "hint": "Check DB_HOST/DB_PORT/DB_NAME/DB_USER formatting.",
        }
    except Exception as e:
        # Import errors or URL build errors
        base = {
            "error": type(e).__name__,
            "message": str(e),
        }
        if _sqlalchemy_import_error is not None:
            base["hint"] = "Install dependencies from requirements.txt"
        return False, base

    try:
        with engine.connect() as conn:
            # Use a simple liveness query compatible with both PostgreSQL and MySQL
            conn.execute(text("SELECT 1"))
        return True, {"status": "ok", "details": {k: v for k, v in details.items() if k != "username" or v}}
    except OperationalError as e:
        return False, {
            "error": "OperationalError",
            "message": str(e.orig) if getattr(e, "orig", None) else str(e),
            "code": getattr(getattr(e, "orig", None), "pgcode", None),
            "details": {k: v for k, v in details.items() if k != "username" or v},
            "hint": (
                "Verify the database is running, network access, credentials, and that the driver is installed."
            ),
        }
    except ProgrammingError as e:
        return False, {
            "error": "ProgrammingError",
            "message": str(e.orig) if getattr(e, "orig", None) else str(e),
            "details": {k: v for k, v in details.items() if k != "username" or v},
        }
    except SQLAlchemyError as e:
        return False, {
            "error": type(e).__name__,
            "message": str(e),
            "details": {k: v for k, v in details.items() if k != "username" or v},
        }


@app.route('/')
def hello_world():
    return 'Hello, World!'


@app.route('/db/health')
def db_health():
    ok, payload = check_db_liveness()
    status_code = 200 if ok else 503
    return make_response(jsonify(payload), status_code)


def _print_json(d: dict):
    print(json.dumps(d, indent=2, sort_keys=True))


def _run_cli(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Database liveness checker")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("check", help="Run a liveness check against the configured database")
    serve_p = sub.add_parser("serve", help="Run the Flask app (default if no command)")
    serve_p.add_argument("--host", default="0.0.0.0")
    serve_p.add_argument("--port", default=5000, type=int)
    serve_p.add_argument("--debug", action="store_true", default=True)

    # If no command provided, emulate default 'serve' behavior
    if len(argv) == 0:
        app.run(debug=True)
        return 0

    args = parser.parse_args(argv)
    if args.command == "check":
        ok, payload = check_db_liveness()
        _print_json(payload)
        return 0 if ok else 2
    elif args.command == "serve":
        app.run(host=args.host, port=args.port, debug=args.debug)
        return 0
    else:
        parser.print_help()
        return 1


if __name__ == '__main__':
    sys.exit(_run_cli(sys.argv[1:]))