import django.utils.timezone
from django.db import migrations, models


def popular_blog_inicial(apps, schema_editor):
    PostBlog = apps.get_model('blog', 'PostBlog')

    PostBlog.objects.get_or_create(
        versao="v2.4.0",
        defaults={
            "titulo": "Guardião de Canhotos & Verificação Inteligente de Fotos",
            "resumo": "Nova proteção inteligente no aplicativo que detecta fotos fora de foco ou borradas, retém preventivamente o envio no TMS e avisa o motorista.",
            "conteudo": """<p class="lead">O <b>Guardião de Canhotos</b> chegou para garantir que 100% dos comprovantes de entrega armazenados e enviados ao cliente tenham qualidade visual impecável e nitidez garantida.</p>

<h5 class="fw-bold mt-4 mb-3 text-primary"><i class="bi bi-shield-check me-2"></i>Principais Destaques do Lançamento:</h5>
<ul class="list-group list-group-flush mb-4">
    <li class="list-group-item bg-transparent ps-0"><b>🤖 Detecção Automática de Desfoque:</b> A Inteligência Artificial avalia matematicamente a nitidez da imagem capturada. Se a foto estiver fora de foco, tremida ou sem leitura, o canhoto é reprovado preventivamente.</li>
    <li class="list-group-item bg-transparent ps-0"><b>🔒 Retenção Preventiva no TMS:</b> Fotos recusadas não são enviadas para o ESL Cloud / Minuta até que o motorista tire uma nova foto nítida ou o SAC aprove manualmente na Torre.</li>
    <li class="list-group-item bg-transparent ps-0"><b>🔔 Notificações Push Nativas (APK e PWA):</b> O motorista recebe um aviso sonoro e notificação direta na barra de status do celular alertando qual nota fiscal precisa de uma nova captura.</li>
    <li class="list-group-item bg-transparent ps-0"><b>3️⃣ Limite Educativo de 3 Tentativas:</b> Para não travar a rotina na rua, o motorista tem até 3 chances. Na terceira tentativa, o sistema aceita a imagem registrando auditoria especial no painel.</li>
    <li class="list-group-item bg-transparent ps-0"><b>👨‍💼 Aprovação Manual pelo SAC:</b> Operadores da Torre de Controle contam com botão ágil para aprovar comprovantes manualmente caso a foto seja legível.</li>
</ul>""",
            "categoria": "NOVIDADE",
            "imagem_url": "/static/images/megafone_3d.png",
            "tags": "Inteligência Artificial, Guardião de Canhotos, Push Notification, Mobile",
            "autor": "Equipe de Engenharia QuickTrack",
            "destaque": True,
            "ativo": True,
        }
    )

    PostBlog.objects.get_or_create(
        versao="v2.3.8",
        defaults={
            "titulo": "Validação de Status do Manifesto e Bloqueio de Baixas Indevidas",
            "resumo": "Proteção no aplicativo que impede baixas e entregas caso o manifesto ainda esteja com status Pendente no TMS.",
            "conteudo": """<p class="lead">Implementada a blindagem de integridade operacional para assegurar que manifestos só recebam baixas após a devida liberação pela expedição no TMS.</p>

<h5 class="fw-bold mt-4 mb-3 text-primary"><i class="bi bi-lock-fill me-2"></i>Recursos e Melhorias:</h5>
<ul class="list-group list-group-flush mb-4">
    <li class="list-group-item bg-transparent ps-0"><b>🔍 Checagem Prévia no TMS:</b> O app valida o status em tempo real. Se o manifesto estiver 'Pendente', o motorista é orientado a aguardar a liberação.</li>
    <li class="list-group-item bg-transparent ps-0"><b>🚫 Bloqueio de Baixas Antecipadas:</b> Previne inconsistências de estoque e divergências fiscais na expedição.</li>
    <li class="list-group-item bg-transparent ps-0"><b>⚡ Finalização Blindada:</b> Sincronização segura que garante o encerramento do manifesto sem travamento do aplicativo mobile.</li>
</ul>""",
            "categoria": "CORRECAO",
            "imagem_url": "/static/images/megafone_3d.png",
            "tags": "TMS, Manifestos, Blindagem, Operacional",
            "autor": "Equipe de Engenharia QuickTrack",
            "destaque": False,
            "ativo": True,
        }
    )

    PostBlog.objects.get_or_create(
        versao="v2.3.5",
        defaults={
            "titulo": "Torre de Controle Live & Status TMS em Tempo Real",
            "resumo": "Acompanhamento ao vivo de notas, bloqueio de edições não autorizadas e sincronização automática via WebSocket.",
            "conteudo": """<p class="lead">A Torre de Controle Live agora oferece visão total e sincronizada de todas as notas fiscais da rota.</p>

<h5 class="fw-bold mt-4 mb-3 text-primary"><i class="bi bi-speedometer2 me-2"></i>O que mudou:</h5>
<ul class="list-group list-group-flush mb-4">
    <li class="list-group-item bg-transparent ps-0"><b>📦 Modal de Notas em Tempo Real:</b> Visualização instantânea de notas entregues, ocorrências e pendências sem recarregar a tela.</li>
    <li class="list-group-item bg-transparent ps-0"><b>🔒 Campos Readonly Sincronizados:</b> Veículo e status do TMS bloqueados para evitar alterações manuais conflitantes.</li>
    <li class="list-group-item bg-transparent ps-0"><b>🌐 Atualização Contínua:</b> WebSocket com feedback imediato de cada entrega realizada pelos motoristas.</li>
</ul>""",
            "categoria": "MELHORIA",
            "imagem_url": "/static/images/megafone_3d.png",
            "tags": "Torre de Controle, WebSocket, Tempo Real, Dashboard",
            "autor": "Equipe de Engenharia QuickTrack",
            "destaque": False,
            "ativo": True,
        }
    )

    PostBlog.objects.get_or_create(
        versao="v2.3.0",
        defaults={
            "titulo": "Novo Motor de Inteligência Artificial para Verificação e Leitura de Canhotos",
            "resumo": "Fim das notas de cabeça para baixo! Desviramento automático de fotos e leitura inteligente de recebedor.",
            "conteudo": """<p class="lead">Novo modelo de Inteligência Artificial para visão computacional com alta precisão e rapidez no reconhecimento de comprovantes.</p>

<h5 class="fw-bold mt-4 mb-3 text-primary"><i class="bi bi-cpu me-2"></i>Inovações da IA:</h5>
<ul class="list-group list-group-flush mb-4">
    <li class="list-group-item bg-transparent ps-0"><b>🔄 Desviramento Automático 180°:</b> A IA detecta a orientação do canhoto e corrige fotos tiradas invertidas automaticamente.</li>
    <li class="list-group-item bg-transparent ps-0"><b>✍️ Leitura Inteligente do Recebedor:</b> Extração automática de nome e documento preenchidos à mão ou carimbados no canhoto.</li>
    <li class="list-group-item bg-transparent ps-0"><b>⚡ Fila de Alta Performance:</b> Processamento desacoplado no Celery Worker sem lentidão para os usuários da plataforma.</li>
</ul>""",
            "categoria": "NOVIDADE",
            "imagem_url": "/static/images/megafone_3d.png",
            "tags": "Inteligência Artificial, OCR, Visão Computacional",
            "autor": "Equipe de Engenharia QuickTrack",
            "destaque": False,
            "ativo": True,
        }
    )


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='PostBlog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('versao', models.CharField(help_text='Ex: v2.4.0 ou Patch 10/08', max_length=50, verbose_name='Versão / Patch')),
                ('titulo', models.CharField(help_text='Ex: Guardião de Canhotos & Verificação Inteligente de Fotos', max_length=255, verbose_name='Título da Publicação')),
                ('slug', models.SlugField(blank=True, max_length=255, null=True, verbose_name='Slug (URL Amigável)')),
                ('resumo', models.CharField(help_text='Texto introdutório exibido no banner da dashboard e nos cards da listagem', max_length=350, verbose_name='Resumo Curto')),
                ('conteudo', models.TextField(help_text='Detalhes completos da atualização com listas, tópicos ou explicações', verbose_name='Conteúdo Completo (HTML)')),
                ('categoria', models.CharField(choices=[('NOVIDADE', '🚀 Nova Funcionalidade'), ('MELHORIA', '⚡ Melhoria de Desempenho'), ('CORRECAO', '🛠️ Correção & Blindagem'), ('AVISO', '📢 Comunicado Geral')], default='NOVIDADE', max_length=30, verbose_name='Categoria')),
                ('imagem_capa', models.ImageField(blank=True, null=True, upload_to='blog/', verbose_name='Imagem de Capa (Upload)')),
                ('imagem_url', models.CharField(blank=True, default='', help_text='URL direta ou estática (ex: /static/images/megafone_3d.png)', max_length=500, verbose_name='Imagem URL (Opcional)')),
                ('tags', models.CharField(blank=True, default='IA, App Mobile, Entregas', help_text='Tags separadas por vírgula (ex: IA, TMS, Notificações)', max_length=200, verbose_name='Tags / Palavras-chave')),
                ('autor', models.CharField(default='Equipe QuickTrack', max_length=100, verbose_name='Autor da Publicação')),
                ('data_publicacao', models.DateTimeField(default=django.utils.timezone.now, verbose_name='Data e Hora de Publicação')),
                ('destaque', models.BooleanField(default=False, verbose_name='⭐ Fixar como Destaque Principal')),
                ('ativo', models.BooleanField(default=True, verbose_name='Publicação Ativa / Visível')),
                ('visualizacoes', models.PositiveIntegerField(default=0, verbose_name='Nº de Visualizações')),
            ],
            options={
                'verbose_name': 'Post do Blog / Patch Note',
                'verbose_name_plural': 'Blog de Lançamentos & Novidades',
                'ordering': ['-destaque', '-data_publicacao', '-id'],
            },
        ),
        migrations.RunPython(popular_blog_inicial, reverse_code=migrations.RunPython.noop),
    ]
