# Generated manually on 2026-08-28
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0024_filial_whatsapp_operacional_filial_whatsapp_sac'),
    ]

    operations = [
        migrations.AddField(
            model_name='filial',
            name='operacao_ativa',
            field=models.BooleanField(
                default=True,
                help_text='Se desmarcado, o webhook ignorará novos manifestos desta filial para evitar acúmulo de rotas não utilizadas.',
                verbose_name='Operação Ativa no App'
            ),
        ),
    ]
