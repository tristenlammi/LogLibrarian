import os
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict

from jose import JWTError, jwt
from fastapi import HTTPException, status

# Configuration
# SECRET_KEY MUST be set in environment for production
# Without a persistent SECRET_KEY, all JWTs become invalid on restart
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    print("")
    print("=" * 70)
    print("⚠️  WARNING: SECRET_KEY environment variable not set!")
    print("=" * 70)
    print("A temporary key will be generated, but:")
    print("  - All users will be logged out on every container restart")
    print("  - JWT tokens will be invalidated on restart")
    print("")
    print("To fix: Add SECRET_KEY to your docker-compose.yml or .env file:")
    print('  SECRET_KEY: "your-32-character-or-longer-secret-key"')
    print("")
    print("Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\"")
    print("=" * 70)
    print("")
    SECRET_KEY = secrets.token_urlsafe(32)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30  # 30 days

class AuthManager:
    """
    Manages JWT authentication: token creation and validation.
    """
    
    def __init__(self, secret_key: str = SECRET_KEY, algorithm: str = ALGORITHM):
        self.secret_key = secret_key
        self.algorithm = algorithm

    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """
        Create a new JWT access token
        """
        to_encode = data.copy()
        
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
            
        to_encode.update({"exp": expire})
        
        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt

    def decode_token(self, token: str) -> Optional[dict]:
        """
        Decode and validate a JWT token.
        Returns the payload dict if valid, or raises HTTPException.
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            
            # Check expiration (handled by jwt.decode, but explicit check for safety)
            exp = payload.get("exp")
            if exp and datetime.fromtimestamp(exp) < datetime.utcnow():
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token expired",
                    headers={"WWW-Authenticate": "Bearer"},
                )
                
            return payload
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except Exception as e:
            print(f"Token decode error: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="Authentication failed",
                headers={"WWW-Authenticate": "Bearer"},
            )

# Global instance
auth_manager = AuthManager()
