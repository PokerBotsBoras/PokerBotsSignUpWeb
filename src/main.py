import sqlite3
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import os
import httpx
from github import Github
import asyncio
from github import GithubException
from contextlib import asynccontextmanager

load_dotenv()

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
GITHUB_REDIRECT_URI = os.getenv("GITHUB_REDIRECT_URI")
GITHUB_ORG_NAME = "PokerBotsBoras"
GITHUB_BOT_TOKEN = os.getenv("GITHUB_POKERBOTS_ORG_SECRET")

DB_PATH = "users.db"


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
        print("[Poller] Checking for new members...")

        g = Github(GITHUB_BOT_TOKEN)
        org = g.get_organization(GITHUB_ORG_NAME)

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT github_username FROM users WHERE joined_org_at IS NOT NULL AND has_repo = 0")
        users = c.fetchall()

        for (username,) in users:
            try:
                user = g.get_user(username)
                if org.has_in_members(user):
                    print(f"[Poller] {username} is a confirmed member. Creating repo...")

                    # Create repo from template
                    template_repo = org.get_repo("BotTemplate") 
                    new_repo = template_repo.create_using_template(
                        name=f"{username}-starter",
                        owner=GITHUB_ORG_NAME,
                        private=True,
                        include_all_branches=False
                    )

                    # Add them to the new repo
                    new_repo.add_to_collaborators(username, permission="admin")

                    # Update DB
                    c.execute("UPDATE users SET has_repo = 1 WHERE github_username = ?", (username,))
                    conn.commit()
                else:
                    print(f"[Poller] {username} hasn't accepted the invite yet.")
            except GithubException as e:
                print(f"[Poller] Error processing {username}: {e}")

        conn.close()

        await asyncio.sleep(300)  # Wait 5 minutes


static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "www"))
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")