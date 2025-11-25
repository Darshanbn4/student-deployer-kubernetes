import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv(*args, **kwargs):
        return None

# Load env from backend/.env if present
env_path = Path(__file__).with_name(".env")
load_dotenv(dotenv_path=env_path)

MONGODB_URL = os.environ.get("MONGODB_URL")
DB_NAME = os.environ.get("DB_NAME", "studentDeployer")

# Lazy client + collection initialization
_mongo_client = None
_students_col = None


def _init_db():
    """Initialize MongoDB client and collection on first use."""
    global _mongo_client, _students_col
    if _students_col is not None:
        return
    if not MONGODB_URL:
        raise RuntimeError("MONGODB_URL not configured. Set it in backend/.env or the environment.")
    try:
        from pymongo import MongoClient
    except Exception as e:
        raise RuntimeError(f"pymongo is required but not installed: {e}")

    _mongo_client = MongoClient(MONGODB_URL, tls=True, serverSelectionTimeoutMS=5000)
    db = _mongo_client[DB_NAME]
    _students_col = db["students"]


def save_or_update_student(doc: dict, status: str = "pending"):
    """Save or update a student document in MongoDB."""
    _init_db()
    doc["status"] = status
    _students_col.update_one({"name": doc["name"]}, {"$set": doc}, upsert=True)


def get_student(name: str) -> dict | None:
    """Get a student document by name."""
    _init_db()
    return _students_col.find_one({"name": name}, {"_id": 0})


def list_students():
    """List all student documents."""
    _init_db()
    out = []
    for d in _students_col.find({}, {"_id": 0}):
        out.append(d)
    return out


def delete_student(name: str) -> int:
    """Remove the student record by name. Returns deleted count (0/1)."""
    _init_db()
    res = _students_col.delete_one({"name": name})
    return res.deleted_count


def update_student_status(name: str, status: str, error: str | None = None):
    """Update the status of a student document."""
    _init_db()
    update = {"status": status}
    if error:
        update["last_error"] = error
    _students_col.update_one({"name": name}, {"$set": update})
