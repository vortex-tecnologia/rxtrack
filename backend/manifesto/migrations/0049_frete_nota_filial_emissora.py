# Copyright (c) 2026 Luiz Gustavo. Todos os direitos reservados. Licença Proprietária.
# Adiciona a FILIAL EMISSORA (corporationId da ESL) e o ID interno do frete (freight.id).
# Migration puramente ADITIVA (somente AddField nullable): não altera nem apaga dados existentes.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0032_merge_filial_sp_duplicada'),
        ('manifesto', '0048_add_moto_carro_veiculo_types'),
    ]

    operations = [
        # ── Frete ──
        migrations.AddField(
            model_name='frete',
            name='esl_freight_id',
            field=models.CharField(blank=True, db_index=True, max_length=50, null=True, verbose_name='ID interno do frete na ESL (freight.id)'),
        ),
        migrations.AddField(
            model_name='frete',
            name='filial_emissora',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='fretes_emitidos', to='usuarios.filial', verbose_name='Filial Emissora do Frete'),
        ),
        migrations.AddField(
            model_name='frete',
            name='id_filial_emissora_tms',
            field=models.CharField(blank=True, db_index=True, max_length=50, null=True, verbose_name='ID da filial emissora na ESL (corporationId)'),
        ),
        migrations.AddField(
            model_name='frete',
            name='nome_filial_emissora_tms',
            field=models.CharField(blank=True, max_length=150, null=True, verbose_name='Nome da filial emissora na ESL'),
        ),
        migrations.AddField(
            model_name='frete',
            name='graphql_sincronizado_em',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Última sincronização via GraphQL'),
        ),
        # ── NotaFiscal ──
        migrations.AddField(
            model_name='notafiscal',
            name='filial_emissora',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='notas_emitidas', to='usuarios.filial', verbose_name='Filial Emissora'),
        ),
        migrations.AddField(
            model_name='notafiscal',
            name='id_filial_emissora_tms',
            field=models.CharField(blank=True, db_index=True, max_length=50, null=True, verbose_name='ID da filial emissora na ESL (corporationId)'),
        ),
        migrations.AddField(
            model_name='notafiscal',
            name='nome_filial_emissora_tms',
            field=models.CharField(blank=True, max_length=150, null=True, verbose_name='Nome da filial emissora na ESL'),
        ),
    ]

