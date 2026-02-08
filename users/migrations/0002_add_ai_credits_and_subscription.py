# Generated manually for JobPilot hybrid pricing

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='ai_credits',
            field=models.IntegerField(default=3, verbose_name='Crédits IA'),
        ),
        migrations.AddField(
            model_name='customuser',
            name='subscription_end_date',
            field=models.DateTimeField(blank=True, null=True, verbose_name="Fin d'abonnement"),
        ),
    ]
