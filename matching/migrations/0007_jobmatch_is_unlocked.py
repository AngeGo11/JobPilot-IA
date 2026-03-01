# Migration: verrouillage des offres (is_unlocked) - déblocage après consommation crédit

from django.db import migrations, models


def unlock_existing_matches(apps, schema_editor):
    """Rendre visibles les matches existants (comportement avant la mise en place du lock)."""
    JobMatch = apps.get_model('matching', 'JobMatch')
    JobMatch.objects.all().update(is_unlocked=True)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('matching', '0006_jobalert'),
    ]

    operations = [
        migrations.AddField(
            model_name='jobmatch',
            name='is_unlocked',
            field=models.BooleanField(default=False, verbose_name='Déblocage (crédit consommé)'),
        ),
        migrations.RunPython(unlock_existing_matches, noop_reverse),
    ]
