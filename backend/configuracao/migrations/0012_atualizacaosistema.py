from django.db import migrations, models


def popular_patch_notes_iniciais(apps, schema_editor):
    AtualizacaoSistema = apps.get_model('configuracao', 'AtualizacaoSistema')
    if AtualizacaoSistema.objects.exists():
        return

    AtualizacaoSistema.objects.create(
        versao="v2.4.0",
        titulo="Guardião de Canhotos & Validação Inteligente de Nitidez",
        resumo="Nova proteção que detecta fotos desfocadas ou ilegíveis, retém o envio no TMS e notifica o motorista no celular.",
        conteudo="""<h5>🛡️ Principais Novidades do Patch v2.4.0:</h5>
<ul>
    <li><b>Detecção Matemática de Desfoque:</b> A IA analisa a nitidez da imagem antes de qualquer processo. Se a foto estiver fora de foco, borrada ou ilegível, o canhoto é recusado preventivamente.</li>
    <li><b>Retenção Preventiva no TMS:</b> Canhotos reprovados não são mais enviados para o ESL Cloud / Minuta até que uma foto de qualidade seja capturada ou o SAC aprove manualmente.</li>
    <li><b>Notificações Push Nativas (APK e PWA):</b> O motorista recebe aviso instantâneo na barra do celular quando um canhoto precisar de uma nova foto.</li>
    <li><b>Regra de 3 Tentativas:</b> O motorista tem até 3 chances para bater a foto nítida. Na 3ª tentativa, o sistema aceita com auditoria especial para não travar a rotina de entregas.</li>
    <li><b>Aprovação Manual na Torre:</b> Operadores do SAC agora contam com botão direto para aprovar canhotos manualmente caso consigam ler a foto.</li>
</ul>""",
        categoria="NOVIDADE",
        destaque=True,
        ativo=True
    )

    AtualizacaoSistema.objects.create(
        versao="v2.3.5",
        titulo="Torre de Controle Live & Status TMS em Tempo Real",
        resumo="Acompanhamento ao vivo de notas, bloqueio de edições não autorizadas e visualização do status real no TMS.",
        conteudo="""<h5>⚡ O que há de novo na Torre de Controle:</h5>
<ul>
    <li><b>Modal de Notas em Tempo Real:</b> Visualização instantânea de notas entregues, com ocorrência ou pendentes direto na tela de monitoramento.</li>
    <li><b>Campos Bloqueados no TMS:</b> Status e veículo sincronizados diretamente do TMS ESL, impedindo alterações manuais acidentais.</li>
    <li><b>Sincronização Bidirecional:</b> Encerramento e status finalizado sincronizados sem travamento do aplicativo do motorista.</li>
</ul>""",
        categoria="MELHORIA",
        destaque=False,
        ativo=True
    )

    AtualizacaoSistema.objects.create(
        versao="v2.3.0",
        titulo="Novo Motor de Inteligência Artificial para Verificação e Leitura de Canhotos",
        resumo="Fim das notas de cabeça para baixo! Desviramento automático de fotos e leitura inteligente de recebedor.",
        conteudo="""<h5>🤖 Inteligência Artificial no Reconhecimento de Fotos:</h5>
<ul>
    <li><b>Desviramento Automático 180°:</b> A IA detecta se a foto foi tirada invertida e corrige a rotação instantaneamente.</li>
    <li><b>Leitura Inteligente do Recebedor:</b> Preenchimento automático de nome e documento caso o motorista não digite.</li>
    <li><b>Aceleração no Processamento:</b> Fila de processamento ultra-rápida sem impacto na navegação do painel.</li>
</ul>""",
        categoria="NOVIDADE",
        destaque=False,
        ativo=True
    )


class Migration(migrations.Migration):

    dependencies = [
        ('configuracao', '0011_configuracaosistema_modulo_cargas_fretes'),
    ]

    operations = [
        migrations.CreateModel(
            name='AtualizacaoSistema',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('versao', models.CharField(help_text='Ex: v2.4.0 ou Patch 10/08', max_length=50, verbose_name='Versão / Patch')),
                ('titulo', models.CharField(help_text='Ex: Guardião de Canhotos & Nova Leitura IA', max_length=200, verbose_name='Título da Novidade')),
                ('resumo', models.CharField(help_text='Texto curto que aparece no banner da dashboard', max_length=300, verbose_name='Resumo (Linha Única)')),
                ('conteudo', models.TextField(help_text='Detalhes completos das novidades e melhorias para o modal', verbose_name='Descrição Completa (Texto/HTML)')),
                ('data_lancamento', models.DateTimeField(auto_now_add=True, verbose_name='Data de Lançamento')),
                ('ativo', models.BooleanField(default=True, verbose_name='Visível aos Usuários')),
                ('destaque', models.BooleanField(default=False, verbose_name='Fixar como Destaque Principal')),
                ('categoria', models.CharField(choices=[('NOVIDADE', '🚀 Nova Funcionalidade'), ('MELHORIA', '⚡ Melhoria de Desempenho'), ('CORRECAO', '🛠️ Correção de Erros'), ('AVISO', '📢 Comunicado Importante')], default='NOVIDADE', max_length=20, verbose_name='Categoria')),
            ],
            options={
                'verbose_name': 'Atualização / Patch Note',
                'verbose_name_plural': 'Atualizações do Sistema (Patch Notes)',
                'ordering': ['-data_lancamento', '-id'],
            },
        ),
        migrations.RunPython(popular_patch_notes_iniciais, reverse_code=migrations.RunPython.noop),
    ]
