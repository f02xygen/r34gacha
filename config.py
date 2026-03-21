import os

# Load .env file
env_path = ".env"
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                parts = line.split('=', 1)
                if len(parts) == 2:
                    os.environ[parts[0].strip()] = parts[1].strip()

class Settings:
    bot_token: str = os.environ.get("BOT_TOKEN", "")
    database_url: str = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///gacha.db")
    proxy: str = os.environ.get("PROXY", "")
    danbooru_login: str = os.environ.get("DANBOORU_LOGIN", "")
    danbooru_api_key: str = os.environ.get("DANBOORU_API_KEY", "")

settings = Settings()
