import jwt
from fastapi.security import HTTPBearer

from app.core.config import env_config

security = HTTPBearer()
jwks_client = jwt.PyJWKClient(env_config.JWKS_ISSUER_URL)