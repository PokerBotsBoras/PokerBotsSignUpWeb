import sqlite3
from fastapi import FastAPI, Request, Body, Header
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import os
import json
import httpx
from github import Github
import asyncio
from github import GithubException
from contextlib import asynccontextmanager
import logging
from pydantic import BaseModel, Field
from typing import List
from tinydb import TinyDB
from datetime import datetime
from ratings import get_final_ratings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Ensure persistence directory exists
PERSISTENCE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "persistence"))
if not os.path.exists(PERSISTENCE_DIR):
    logger.info(f"Persistence directory '{PERSISTENCE_DIR}' does not exist. Creating it.")
    os.makedirs(PERSISTENCE_DIR, exist_ok=True)

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
GITHUB_REDIRECT_URI = os.getenv("GITHUB_REDIRECT_URI")
GITHUB_ORG_NAME = "PokerBotsBoras"
GITHUB_BOT_TOKEN = os.getenv("GITHUB_POKERBOTS_ORG_SECRET")

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "persistence", "users.db")
RESULTS_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "persistence", "results.json")

# TinyDB setup
results_db = TinyDB(RESULTS_DB_PATH)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            github_username TEXT UNIQUE NOT NULL,
            email TEXT,
            name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            joined_org_at TIMESTAMP,
            has_repo INTEGER DEFAULT 0
        )
    """
    )
    conn.commit()
    conn.close()


init_db()


def add_user_to_db(github_username, email=None, name=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        INSERT OR IGNORE INTO users (github_username, email, name)
        VALUES (?, ?, ?)
    """,
        (github_username, email, name),
    )
    conn.commit()
    conn.close()


def set_joined_org_date(github_username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        UPDATE users
        SET joined_org_at = CURRENT_TIMESTAMP
        WHERE github_username = ?
        AND joined_org_at IS NULL
        """,
        (github_username,),
    )
    conn.commit()
    conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(poll_for_new_members())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(lifespan=lifespan)

@app.get("/auth/login")
async def login():
    redirect_url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&redirect_uri={GITHUB_REDIRECT_URI}"
        f"&scope=read:user%20user:email"
    )
    return RedirectResponse(redirect_url)


@app.get("/auth/github/callback")
async def callback(request: Request):
    code = request.query_params.get("code")
    if not code:
        return JSONResponse({"error": "Missing code"}, status_code=400)

    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": GITHUB_REDIRECT_URI,
            },
        )
        token_json = token_res.json()
        access_token = token_json.get("access_token")

        if not access_token:
            return JSONResponse({"error": "Failed to get access token"}, status_code=400)

        user_res = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_data = user_res.json()
        github_username = user_data.get("login")
        email = user_data.get("email")
        name = user_data.get("name")

    # Add user to SQLite database
    if github_username:
        add_user_to_db(github_username, email, name)
        set_joined_org_date(github_username)

    invite_status = "not processed"

    # Invite user to organization using PyGitHub
    if github_username:
        g = Github(GITHUB_BOT_TOKEN)
        org = g.get_organization(GITHUB_ORG_NAME)
        try:
            # Get the user object
            user = g.get_user(github_username)
            # Check if user is already a member
            if not org.has_in_members(user):
                # Check if user has a pending invite
                pending_invites = org.invitations()
                already_invited = any(
                    invitee.login == github_username for invitee in pending_invites
                )
                if not already_invited:
                    org.invite_user(user=user)
                    invite_status = "invitation sent"
                else:
                    invite_status = "already invited, invite pending"
            else:
                invite_status = "you are a member"
        except Exception as e:
            return JSONResponse({"error": f"Failed to invite user: {str(e)}"}, status_code=500)

    return JSONResponse(
        {
            "user": github_username,
            "invite_status": invite_status
        }
    )

async def poll_for_new_members():
    while True:
        try:
            logger.info("[Poller] Checking for new members...")

            g = Github(GITHUB_BOT_TOKEN)
            org = g.get_organization(GITHUB_ORG_NAME)
            template_repo = org.get_repo("BotTemplate")

            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT github_username FROM users WHERE joined_org_at IS NOT NULL AND has_repo = 0")
            users = c.fetchall()

            for (username,) in users:
                try:
                    user = g.get_user(username)
                    if org.has_in_members(user):
                        logger.info(f"[Poller] {username} is a confirmed member. Creating repo...")

                        # the bot prefix is important
                        repo_name = f"bot-{username}"
                        new_repo = org.create_repo_from_template(
                            name=repo_name,
                            repo=template_repo,
                            private=True,
                            include_all_branches=False
                        )

                        new_repo.add_to_collaborators(username, permission="admin")
                        c.execute("UPDATE users SET has_repo = 1 WHERE github_username = ?", (username,))
                        conn.commit()
                        logger.info(f"Repository '{repo_name}' created and '{username}' added as admin.")
                    else:
                        logger.info(f"[Poller] {username} hasn't accepted the invite yet.")
                except GithubException as e:
                    logger.info(f"[Poller] Error processing {username}: {e}")

            conn.close()

        except Exception as e:
            logger.info(f"[Poller] Unexpected error: {e}")
        finally:
            await asyncio.sleep(150)



# Pydantic models for validation
class ResultItem(BaseModel):
    BotA: str
    BotB: str
    BotAWins: int
    BotBWins: int

class ResultsPayload(BaseModel):
    Date: str = Field(..., example="2025-06-26T15:42:00Z")
    Results: List[ResultItem]

RESULTS_SECRET = os.getenv("RESULTS_SECRET")

@app.post("/results")
async def save_results(
    payload: ResultsPayload = Body(...),
    x_secret: str = Header(None)
):
    if x_secret != RESULTS_SECRET:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        dt = datetime.fromisoformat(payload.Date.replace("Z", "+00:00"))
    except Exception:
        return JSONResponse({"error": "Invalid date format"}, status_code=400)

    result_dicts = [item.dict() for item in payload.Results]

    # Save results to DB
    results_db.insert({
        "Date": payload.Date,
        "Results": result_dicts
    })

    # Calculate final ratings
    final_ratings = get_final_ratings(result_dicts)

    # Save to ../www/ratings.json
    ratings_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "www", "ratings.json"))
    with open(ratings_path, "w") as f:
        json.dump(final_ratings, f, indent=2)

    return {
        "status": "ok",
        "ratings": final_ratings
    }


static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "www"))
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
