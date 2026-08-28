# Generated manually on 2026-08-28
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0026_alter_filial_operacao_ativa'),
    ]

    operations = [
        migrations.AddField(
            model_name='filial',
            name='cnpj',
            field=models.CharField(
                blank=True,
                help_text='CNPJ da base (usado para unificar com os manifestos recebidos via Webhook)',
                max_length=20,
                null=True,
                verbose_name='CNPJ da Filial'
            ),
        ),
        migrations.AlterField(
            model_name='filial',
            name='id_filial_tms',
            field=models.CharField(
                blank=True,
                help_text='ID numérico da ESL Cloud (usado na Busca Manual)',
                max_length=50,
                null=True,
                verbose_name='ID da Filial na ESL'
            ),
        ),
    ]
