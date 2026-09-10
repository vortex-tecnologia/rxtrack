import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0002_add_patch_v2_5_0'),
    ]

    operations = [
        migrations.CreateModel(
            name='AlertaSistema',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('titulo', models.CharField(help_text='Ex: Instabilidade na integração com ESL Cloud (Despacho / Transferência)', max_length=200, verbose_name='Título do Alerta')),
                ('tipo', models.CharField(choices=[('PERIGO', '🔴 Intermitência / Falha Crítica'), ('AVISO', '🟡 Atenção / Instabilidade Parcial'), ('INFO', '🔵 Informativo / Comunicado'), ('SUCESSO', '🟢 Normalizado / Resolvido')], default='AVISO', max_length=20, verbose_name='Severidade / Tipo')),
                ('tms_alvo', models.CharField(choices=[('TODOS', '🌐 Todos os Provedores (Geral)'), ('esl_cloud', '⚡ ESL Cloud'), ('brudam', '🚚 Brudam TMS'), ('totvs', '🏢 TOTVS'), ('sap_tm', '💼 SAP TM'), ('intelipost', '📦 Intelipost'), ('nenhum', '⚪ Sem integração TMS')], default='TODOS', help_text="Selecione qual sistema TMS receberá este alerta. Se 'Todos', todos os clientes verão.", max_length=30, verbose_name='Provedor TMS Afetado')),
                ('schemas_especificos', models.CharField(blank=True, default='', help_text='Deixe em branco para todos os clientes do provedor selecionado. Ou separe schemas por vírgula (ex: rdexpresso, homolog)', max_length=500, verbose_name='Schemas Específicos (Opcional)')),
                ('conteudo_html', models.TextField(help_text='Escreva a mensagem em HTML com explicações, passos a tomar, prazos e orientações.', verbose_name='Conteúdo Detalhado (HTML)')),
                ('ativo', models.BooleanField(default=True, help_text='Se desmarcado, o ícone flutuante desaparece imediatamente para todos.', verbose_name='Alerta Ativo / Visível')),
                ('fixar_topo', models.BooleanField(default=False, help_text='Se marcado, força animação de pulsação contínua e destaque no ícone flutuante.', verbose_name='Alta Prioridade (Glow / Pulsação)')),
                ('data_criacao', models.DateTimeField(default=django.utils.timezone.now, verbose_name='Data de Criação')),
                ('data_expiracao', models.DateTimeField(blank=True, help_text='Se preenchido, o alerta deixará de ser exibido automaticamente após esse horário.', null=True, verbose_name='Data/Hora de Expiração Automática (Opcional)')),
            ],
            options={
                'verbose_name': 'Alerta do Sistema (Notificação Global)',
                'verbose_name_plural': 'Alertas do Sistema (Notificações Globais)',
                'ordering': ['-fixar_topo', '-data_criacao', '-id'],
            },
        ),
    ]
