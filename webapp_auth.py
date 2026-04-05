import hmac
import hashlib
from urllib.parse import parse_qsl

def validate_webapp_data(init_data: str, bot_token: str) -> dict | None:
    """
    Validates Telegram WebApp initData and returns parsed user data if valid.
    """
    try:
        parsed_data = dict(parse_qsl(init_data))
        if 'hash' not in parsed_data:
            return None
            
        hash_ = parsed_data.pop('hash')
        # Sort key-value pairs alphabetically by key
        data_check_string = '\n'.join(f"{k}={v}" for k, v in sorted(parsed_data.items()))
        
        # Secret key is HMAC-SHA-256 of bot_token with key "WebAppData"
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        
        # Calculate hash and compare
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        if calculated_hash == hash_:
            return parsed_data
        return None
    except Exception:
        return None
