from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "users"
    verbose_name = "Utilisateurs"

    def ready(self):
        import users.signals  # noqa: F401
        
        # Créer automatiquement le Site Django s'il n'existe pas
        try:
            from django.contrib.sites.models import Site
            from django.conf import settings
            
            site_id = getattr(settings, 'SITE_ID', 1)
            if not Site.objects.filter(id=site_id).exists():
                # Récupérer le domaine depuis les settings
                site_url = getattr(settings, 'SITE_URL', 'https://JobPilot-IA.fr')
                # Nettoyer l'URL si elle contient https:// ou http://
                default_domain = site_url.replace('https://', '').replace('http://', '').rstrip('/')
                
                Site.objects.get_or_create(
                    id=site_id,
                    defaults={
                        'domain': default_domain,
                        'name': 'JobPilot-IA'
                    }
                )
        except Exception:
            # Ignorer les erreurs lors du démarrage (par exemple si la table n'existe pas encore)
            pass
