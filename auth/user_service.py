# auth/user_service.py
"""
Service utilisateur : logique métier pour créer / retrouver un user après OAuth callback.
"""

from sqlalchemy.orm import Session
from auth.models import User, OAuthAccount


def get_or_create_user(
    db: Session,
    provider: str,
    provider_user_id: str,
    email: str | None = None,
    display_name: str | None = None,
    avatar_url: str | None = None,
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> User:
    """
    Cherche un utilisateur par son compte OAuth (provider + provider_user_id).
    - Si trouvé : met à jour les tokens et retourne le user.
    - Si pas trouvé mais email existant : lie le nouveau provider au user existant.
    - Si pas trouvé du tout : crée un nouveau user + OAuthAccount.
    """
    # 1. Chercher par provider + provider_user_id
    oauth_account = (
        db.query(OAuthAccount)
        .filter_by(provider=provider, provider_user_id=provider_user_id)
        .first()
    )

    if oauth_account:
        # Mettre à jour les tokens
        oauth_account.access_token = access_token
        oauth_account.refresh_token = refresh_token
        # Mettre à jour les infos du user si elles ont changé
        user = oauth_account.user
        if display_name and not user.display_name:
            user.display_name = display_name
        if avatar_url:
            user.avatar_url = avatar_url
        db.commit()
        return user

    # 2. Chercher par email (pour lier un nouveau provider à un user existant)
    user = None
    if email:
        user = db.query(User).filter_by(email=email).first()

    # 3. Créer un nouveau user si nécessaire
    if not user:
        user = User(
            email=email,
            display_name=display_name,
            avatar_url=avatar_url,
        )
        db.add(user)
        db.flush()  # Pour obtenir user.id avant de créer l'OAuthAccount

    # 4. Créer le lien OAuthAccount
    new_oauth = OAuthAccount(
        user_id=user.id,
        provider=provider,
        provider_user_id=provider_user_id,
        access_token=access_token,
        refresh_token=refresh_token,
    )
    db.add(new_oauth)
    db.commit()
    db.refresh(user)
    return user