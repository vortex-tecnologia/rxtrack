# Generated for RXTrack - Filial no FechamentoAgregado

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('financeiro', '0002_clientebasepagadora'),
        ('usuarios', '0030_alter_motorista_tipo_usuario'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='fechamentoagregado',
            options={
                'ordering': ['-periodo_inicio', '-id'],
                'verbose_name': 'Fechamento de Agregado',
                'verbose_name_plural': 'Fechamentos de Agregados',
            },
        ),
        migrations.AddField(
            model_name='fechamentoagregado',
            name='filial',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='fechamentos_agregados',
                to='usuarios.filial',
                verbose_name='Filial Calculada',
            ),
        ),
    ]

