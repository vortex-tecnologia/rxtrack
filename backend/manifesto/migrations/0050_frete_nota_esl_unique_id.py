# Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados. Licença Proprietária.
# Adiciona o código único da etiqueta ESL (`freight.uniqueId`) em Frete e NotaFiscal.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('manifesto', '0049_frete_nota_filial_emissora'),
    ]

    operations = [
        migrations.AddField(
            model_name='frete',
            name='esl_unique_id',
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=50,
                null=True,
                verbose_name='Código da Etiqueta ESL (uniqueId)',
            ),
        ),
        migrations.AddField(
            model_name='notafiscal',
            name='esl_unique_id',
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=50,
                null=True,
                verbose_name='Código da Etiqueta ESL (uniqueId)',
            ),
        ),
    ]

