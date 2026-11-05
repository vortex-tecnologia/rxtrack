# Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados. Licença Proprietária.
# Adiciona o sequenceCode do frete na ESL (`freight.sequenceCode`) em Frete e NotaFiscal.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('manifesto', '0050_frete_nota_esl_unique_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='frete',
            name='sequence_code',
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=50,
                null=True,
                verbose_name='Sequence Code ESL (sequenceCode)',
            ),
        ),
        migrations.AddField(
            model_name='notafiscal',
            name='sequence_code',
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=50,
                null=True,
                verbose_name='Sequence Code ESL (sequenceCode)',
            ),
        ),
    ]
