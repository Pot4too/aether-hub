import sqlite3

from fastapi import APIRouter, Depends, Response

from app.deps import get_db

router = APIRouter()


@router.get("/health")
def health(response: Response, conn: sqlite3.Connection = Depends(get_db)):
    try:
        conn.execute("SELECT 1")
    except sqlite3.Error:
        response.status_code = 503
        return {"status": "error"}
    return {"status": "ok"}
