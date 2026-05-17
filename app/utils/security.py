from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY is not set. Define it in backend/.env before starting the server."
    )

ALGORITHM = "HS256"
# JWT lifetime is the upper bound on how long a session can last. It is NOT
# refreshed by client activity — refreshSession() in auth.service.ts only
# extends a client-side idle clock. Setting this equal to the idle timeout
# would log active users out the moment the JWT expired even though they
# never went idle, so we set it generously (12 h) and let the client-side
# 20-minute idle timer be the actual gatekeeper for inactivity.
ACCESS_TOKEN_EXPIRE_MINUTES = 12 * 60

pwd_context = CryptContext(schemes=["sha512_crypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt
