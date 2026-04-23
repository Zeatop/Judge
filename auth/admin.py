# auth/admin.py
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from auth.models import User, get_db
from auth.jwt import get_current_user_id
from auth.config import ADMIN_EMAILS


def get_admin_user(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> User:
    """
    Dépendance FastAPI qui :
    - Raise 401 si pas de token / token invalide (via get_current_user_id)
    - Raise 403 si l'user connecté n'est pas admin
    - Retourne le User complet sinon
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur introuvable",
        )
    if not user.email or user.email.lower() not in ADMIN_EMAILS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès administrateur requis",
        )
    return user