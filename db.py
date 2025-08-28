# shared/db.py
import psycopg2
from psycopg2.extras import RealDictCursor
import hashlib

DB_CONFIG = {
    "user": "postgres.jsjlthhnrtwjcyxowpza",
    "password": "@Deep7067",
    "host": "aws-1-ap-south-1.pooler.supabase.com",
    "port": "6543",
    "dbname": "postgres",
    "sslmode": "require"
}

def get_connection():
    return psycopg2.connect(**DB_CONFIG)

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()
