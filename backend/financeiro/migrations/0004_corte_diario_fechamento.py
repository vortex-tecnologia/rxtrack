# Generated for RXTrack - Horário de Corte Diário e Auditoria de Tempo no Fechamento de Agregados

import datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('financeiro', '0003_fechamentoagregado_filial'),
    ]

    operations = [
        migrations.AddField(
            model_name='configuracaofinanceiro',
            name='horario_corte_diario',
            field=models.TimeField(
                default=datetime.time(20, 0),
                help_text='Horário limite diário (horário de Brasília) para finalização do manifesto pelo agregado. Manifestos finalizados após este horário têm diária e notas zeradas.',
                verbose_name='Horário de Corte Diário (Brasília)',
            ),
        ),
        migrations.AddField(
            model_name='configuracaofinanceiro',
            name='fechamento_diario_automatico_ativo',
            field=models.BooleanField(
                default=True,
                help_text='Se ativo, executa automaticamente o fechamento diário todos os dias no horário de corte configurado.',
                verbose_name='Fechamento Automático Diário Ativo',
            ),
        ),
        migrations.AddField(
            model_name='configuracaofinanceiro',
            name='ultimo_fechamento_diario_em',
            field=models.DateField(
                blank=True,
                null=True,
                verbose_name='Data do Último Fechamento Automático',
            ),
        ),
        migrations.AddField(
            model_name='linhafechamento',
            name='total_notas_manifesto',
            field=models.IntegerField(default=0, verbose_name='Total de Notas no Manifesto'),
        ),
        migrations.AddField(
            model_name='linhafechamento',
            name='qtd_ocorrencias',
            field=models.IntegerField(default=0, verbose_name='Qtd Ocorrências (Problemas)'),
        ),
        migrations.AddField(
            model_name='linhafechamento',
            name='data_hora_inicio',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Início do Manifesto'),
        ),
        migrations.AddField(
            model_name='linhafechamento',
            name='data_hora_finalizacao',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Finalização do Manifesto'),
        ),
        migrations.AddField(
            model_name='linhafechamento',
            name='tempo_manifesto_minutos',
            field=models.IntegerField(default=0, verbose_name='Tempo de Manifesto (min)'),
        ),
        migrations.AddField(
            model_name='linhafechamento',
            name='horario_corte_aplicado',
            field=models.TimeField(default=datetime.time(20, 0), verbose_name='Horário de Corte Aplicado'),
        ),
        migrations.AddField(
            model_name='linhafechamento',
            name='dentro_do_corte',
            field=models.BooleanField(default=True, verbose_name='Finalizado Dentro do Corte'),
        ),
        migrations.AddField(
            model_name='linhafechamento',
            name='status_corte',
            field=models.CharField(
                default='DENTRO_DO_CORTE',
                help_text='DENTRO_DO_CORTE, APOS_CORTE, NAO_FINALIZADO ou EM_ANDAMENTO',
                max_length=25,
                verbose_name='Status do Corte',
            ),
        ),
        migrations.AddField(
            model_name='linhafechamento',
            name='atraso_apos_corte_minutos',
            field=models.IntegerField(default=0, verbose_name='Minutos Após o Corte'),
        ),
        migrations.AddField(
            model_name='linhafechamento',
            name='valor_bloqueado_corte',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text='Valor que seria pago (diária + entregas + coletas) caso tivesse finalizado dentro do horário de corte.',
                max_digits=10,
                verbose_name='Valor Bloqueado por Corte (R$)',
            ),
        ),
    ]
