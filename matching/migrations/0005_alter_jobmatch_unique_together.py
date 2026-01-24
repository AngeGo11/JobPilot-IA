# Generated manually for JobPilot - Cloisonnement des matches par CV

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('matching', '0004_jobmatch_resume'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='jobmatch',
            unique_together={('resume', 'job_offer')},
        ),
    ]
