# secrets_manager.py
import os
import subprocess
import json
import time
from filelock import FileLock

branch = os.getenv('FLASK_ENV', 'dev') 
bws_session = os.getenv('BWS_ACCESS_TOKEN')
if not bws_session:
    raise EnvironmentError("BWS_ACCESS_TOKEN environment variable not set.")


SECRETS_CACHE = {}
CACHE_EXPIRATION_SECONDS = 300  # Cache expiration time (5 minutes)
LOCK_FILE = 'secrets.lock'

def update_secrets_cache():
    with FileLock(LOCK_FILE):
        try:
            output = subprocess.check_output(['bws', 'secret', 'list'], text=True)
            secrets = json.loads(output)
            current_time = time.time()
            
            for secret in secrets:
                secret_key = secret['key'].lower()
                SECRETS_CACHE[secret_key] = {
                    'value': secret['value'],
                    'expires': current_time + CACHE_EXPIRATION_SECONDS
                }
        except subprocess.CalledProcessError as e:
            raise ValueError(f"Failed to list or retrieve secrets from Secret Store: {str(e)}")

def get_secret(secret_key, field_name=None):
    secret_key_lower = secret_key.lower()
    
    if secret_key_lower in SECRETS_CACHE and time.time() < SECRETS_CACHE[secret_key_lower]['expires']:
        secret = SECRETS_CACHE[secret_key_lower]['value']
        return secret.get(field_name) if field_name else secret
    
    update_secrets_cache()
    
    if secret_key_lower in SECRETS_CACHE:
        secret = SECRETS_CACHE[secret_key_lower]['value']
        return secret.get(field_name) if field_name else secret
    
    raise ValueError(f"Secret with key '{secret_key}' not found.")