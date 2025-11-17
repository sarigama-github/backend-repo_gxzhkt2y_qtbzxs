import os
from typing import Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import requests
from datetime import datetime, timezone

from database import db, create_document, get_documents

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI Backend!"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}


@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"

            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"

    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"

    return response


# ----- Waitlist Models and Endpoints -----
class WaitlistSubmission(BaseModel):
    email: EmailStr
    token: str  # Cloudflare Turnstile token
    city: Optional[str] = None
    source: Optional[str] = None


@app.get("/waitlist/count")
def waitlist_count():
    try:
        if db is None:
            raise HTTPException(status_code=500, detail="Database not configured")
        count = db["waitlist"].count_documents({})
        return {"count": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/waitlist/submit")
def waitlist_submit(payload: WaitlistSubmission, request: Request):
    # Verify Turnstile token
    secret = os.getenv("TURNSTILE_SECRET_KEY")
    if not secret:
        raise HTTPException(status_code=500, detail="Turnstile secret not configured")

    remote_ip = request.client.host if request and request.client else None

    verify_url = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    data = {
        "secret": secret,
        "response": payload.token,
    }
    if remote_ip:
        data["remoteip"] = remote_ip

    try:
        r = requests.post(verify_url, data=data, timeout=6)
        vr = r.json()
        if not vr.get("success"):
            raise HTTPException(status_code=400, detail="CAPTCHA verification failed")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Verification error: {str(e)}")

    # Store in DB
    try:
        doc = {
            "email": str(payload.email).lower(),
            "city": payload.city or "Milano",
            "source": payload.source or "landing",
            "subscribed_at": datetime.now(timezone.utc),
        }
        # Ensure uniqueness on email (manual upsert-like)
        existing = db["waitlist"].find_one({"email": doc["email"]})
        if existing:
            db["waitlist"].update_one({"_id": existing["_id"]}, {"$set": {"updated_at": datetime.now(timezone.utc)}})
        else:
            create_document("waitlist", doc)
        count = db["waitlist"].count_documents({})
        return {"ok": True, "count": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
