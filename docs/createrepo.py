import os
from github import Github
from dotenv import load_dotenv
load_dotenv()

GITHUB_ORG_NAME = "PokerBotsBoras"
GITHUB_BOT_TOKEN = os.getenv("GITHUB_POKERBOTS_ORG_SECRET")
TEMPLATE_REPO_NAME = "BotTemplate"
TARGET_USERNAME = "kaprifol"

def main():
    g = Github(GITHUB_BOT_TOKEN)
    org = g.get_organization(GITHUB_ORG_NAME)
    template_repo = org.get_repo(TEMPLATE_REPO_NAME)

    repo_name = f"{TARGET_USERNAME}-bot"
    print(f"Creating repo '{repo_name}' for user '{TARGET_USERNAME}' from template '{TEMPLATE_REPO_NAME}'...")

    new_repo = org.create_repo_from_template(
        name=repo_name,
        repo=template_repo,
        private=False,
        include_all_branches=False
    )

    new_repo.add_to_collaborators(TARGET_USERNAME, permission="admin")
    print(f"Repository '{repo_name}' created and '{TARGET_USERNAME}' added as admin.")

if __name__ == "__main__":
    main()