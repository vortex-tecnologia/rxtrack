# Generated manually on 2026-08-28
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0027_filial_cnpj'),
    ]

    operations = [
        migrations.AlterField(
            model_name='filial',
            name='cnpj',
            field=models.CharField(
                blank=True,
                help_text='Informe um ou mais CNPJs separados por vírgula (ex: 14539546000120, 14539546000200). Usado para unificar manifestos recebidos via Webhook.',
                max_length=255,
                null=True,
                verbose_name='CNPJ(s) da Filial'
            ),
        ),
    ]
