from github import Github
import os
from dotenv import load_dotenv
load_dotenv()
GITHUB_BOT_TOKEN = os.getenv("GITHUB_POKERBOTS_ORG_SECRET")
g = Github(GITHUB_BOT_TOKEN)
org = g.get_organization("PokerBotsBoras")
print(org)
user = g.get_user("gherghett")

# Check if user is already a member
if org.has_in_members(user):
    print(f"{user.login} is already a member of the organization.")
else:
    org.invite_user(user=user)
    print(f"Invitation sent to {user.login}.")
