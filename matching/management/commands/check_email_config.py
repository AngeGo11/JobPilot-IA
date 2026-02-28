"""
Vérifie la configuration email et peut envoyer un email de test.

Usage:
  python manage.py check_email_config
  python manage.py check_email_config --send toi@example.com
"""
from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.mail import send_mail


class Command(BaseCommand):
    help = "Affiche la config email et optionnellement envoie un email de test."

    def add_arguments(self, parser):
        parser.add_argument(
            '--send',
            type=str,
            metavar='EMAIL',
            help='Envoie un email de test à cette adresse (utilise le backend configuré).',
        )

    def handle(self, *args, **options):
        backend = getattr(settings, 'EMAIL_BACKEND')
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None)
        host = getattr(settings, 'EMAIL_HOST', None)
        port = getattr(settings, 'EMAIL_PORT', None)
        use_tls = getattr(settings, 'EMAIL_USE_TLS', None)
        user = getattr(settings, 'EMAIL_HOST_USER', None)
        has_password = bool(getattr(settings, 'EMAIL_HOST_PASSWORD', None))

        self.stdout.write("--- Configuration email ---")
        self.stdout.write(f"  EMAIL_BACKEND      : {backend}")
        self.stdout.write(f"  DEFAULT_FROM_EMAIL : {from_email or '(vide)'}")
        if 'smtp' in str(backend).lower():
            self.stdout.write(f"  EMAIL_HOST         : {host or '(vide)'}")
            self.stdout.write(f"  EMAIL_PORT         : {port or '(vide)'}")
            self.stdout.write(f"  EMAIL_USE_TLS      : {use_tls}")
            self.stdout.write(f"  EMAIL_HOST_USER    : {user or '(vide)'}")
            self.stdout.write(f"  EMAIL_HOST_PASSWORD: {'*** défini' if has_password else '(vide)'}")

        ok = True
        if not from_email:
            self.stdout.write(self.style.WARNING("  ⚠ DEFAULT_FROM_EMAIL manquant (un fallback sera utilisé)."))
        if 'smtp' in str(backend).lower():
            if not all([host, user, has_password]):
                self.stdout.write(self.style.ERROR("  ✗ SMTP incomplet : EMAIL_HOST, EMAIL_HOST_USER et EMAIL_HOST_PASSWORD requis."))
                ok = False
            else:
                self.stdout.write(self.style.SUCCESS("  ✓ Config SMTP présente."))
        else:
            self.stdout.write(self.style.SUCCESS("  ✓ Backend non-SMTP (ex. console) : pas besoin de SMTP."))

        to_email = options.get('send')
        if to_email:
            self.stdout.write("")
            try:
                send_mail(
                    subject="[jobpilot-ai] Email de test",
                    message="Ceci est un email de test. La configuration email fonctionne.",
                    from_email=from_email or 'jobpilot-ai <noreply@jobpilot.local>',
                    recipient_list=[to_email],
                    fail_silently=False,
                )
                self.stdout.write(self.style.SUCCESS(f"  Email de test envoyé à {to_email}."))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  Échec envoi : {e}"))
                ok = False
        elif ok:
            self.stdout.write("")
            self.stdout.write("Pour envoyer un email de test : python manage.py check_email_config --send votre@email.com")
