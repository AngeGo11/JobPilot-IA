"""
Adaptateur personnalisé pour django-allauth.
Remplit correctement email, first_name et last_name depuis les providers (Google, GitHub).
"""

from allauth.socialaccount.adapter import DefaultSocialAccountAdapter


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Surcharge populate_user pour extraire les données des providers
    et les assigner au modèle User avant sauvegarde.
    """

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        extra = sociallogin.account.extra_data
        provider = sociallogin.account.get_provider().id

        if provider == "google":
            if extra.get("given_name"):
                user.first_name = extra["given_name"]
            if extra.get("family_name"):
                user.last_name = extra["family_name"]



        return user
