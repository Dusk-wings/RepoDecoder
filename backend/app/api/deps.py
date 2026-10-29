from fastapi.security import HTTPAuthorizationCredentials
from fastapi import Depends, HTTPException, status

import jwt

from app.core.security import security, jwks_client
from app.core.config import env_config


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials

    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
            issuer=env_config.ISSUER_URL,
            options={"verify_iss": True},
        )

        user_id = payload.get("sub")
        is_anonymous: bool = payload.get("is_anonymous", False)

        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="INVALID AUTHENTICATION CREDENTIALS",
            )

        return {
            "user_id": user_id,
            "is_anonymous": is_anonymous,
            "email": payload.get("email"),
        }

    except jwt.PyJWKClientError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="TOKEN VALIDATION FAILED"
        )

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="TOKEN IS EXPIRED",
        )

    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID AUTHENTICATION CREDENTIALS",
        )
