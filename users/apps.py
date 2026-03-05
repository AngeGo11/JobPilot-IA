from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "users"
    verbose_name = "Utilisateurs"

    def ready(self):
        import users.signals  # noqa: F401
        self._ensure_site_domain()

    def _ensure_site_domain(self):
        """Met à jour le Site Django (SITE_ID) avec le domaine de SITE_URL pour les emails et liens."""
        from django.conf import settings
        from django.contrib.sites.models import Site
        site_url = getattr(settings, "SITE_URL", "").strip()
        if not site_url:
            return
        domain = site_url.replace("https://", "").replace("http://", "").rstrip("/").split("/")[0]
        if not domain:
            return
        try:
            site = Site.objects.filter(pk=settings.SITE_ID).first()
            if site and site.domain != domain:
                site.domain = domain
                site.name = site.name or domain
                site.save(update_fields=["domain", "name"])
        except Exception:
            pass

