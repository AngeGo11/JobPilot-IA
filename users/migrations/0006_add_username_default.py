# Ajoute la colonne username (tu l'avais supprimée) avec défaut pour compatibilité AbstractUser.

import django.contrib.auth.validators
from django.db import migrations, models


def set_username_from_email(apps, schema_editor):
    """Remplit username avec l'email pour éviter les doublons (username est unique)."""
    CustomUser = apps.get_model("users", "CustomUser")
    for user in CustomUser.objects.all():
        if user.email:
            user.username = user.email
            user.save(update_fields=["username"])


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0005_alter_customuser_email"),
    ]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="username",
            field=models.CharField(
                max_length=150,
                null=True,
                validators=[django.contrib.auth.validators.UnicodeUsernameValidator()],
                verbose_name="username",
            ),
        ),
        migrations.RunPython(set_username_from_email, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="customuser",
            name="username",
            field=models.CharField(
                max_length=150,
                default="temp_user",
                unique=True,
                validators=[django.contrib.auth.validators.UnicodeUsernameValidator()],
                verbose_name="username",
            ),
        ),
    ]
