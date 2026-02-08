# Generated manually - type d'abonnement pour affichage navbar

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0002_add_ai_credits_and_subscription'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='subscription_plan',
            field=models.CharField(
                blank=True,
                help_text="pass24h, sprint ou pro",
                max_length=20,
                null=True,
                verbose_name="Type d'abonnement",
            ),
        ),
    ]
