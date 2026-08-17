import django.utils.timezone
from django.db import migrations


def adicionar_patch_v2_5_0(apps, schema_editor):
    PostBlog = apps.get_model('blog', 'PostBlog')

    # Desmarca destaque de versões anteriores
    PostBlog.objects.filter(destaque=True).update(destaque=False)

    PostBlog.objects.update_or_create(
        versao="v2.5.0",
        defaults={
            "titulo": "Validação Instantânea de Qualidade de Canhotos no App (V1)",
            "slug": "validacao-instantanea-qualidade-canhotos-app-v2-5-0",
            "resumo": "Novo motor leve no frontend que avalia nitidez, iluminação e contraste do canhoto em tempo real antes de liberar a confirmação de baixa da entrega.",
            "conteudo": """<p class="lead">Lançamos a <b>Validação V1 de Qualidade de Canhotos</b> diretamente no aplicativo mobile (PWA e APK Capacitor), realizando uma triagem ultrarrápida da foto antes do envio ao servidor.</p>

<h5 class="fw-bold mt-4 mb-3 text-primary"><i class="bi bi-camera-fill me-2"></i>Principais Destaques do Patch v2.5.0:</h5>
<ul class="list-group list-group-flush mb-4">
    <li class="list-group-item bg-transparent ps-0"><b>🔍 Diagnóstico Técnico em Tempo Real:</b> Avalia matematicamente nitidez (variância do Laplaciano), iluminação (escura/estourada), contraste e resolução da imagem antes do envio.</li>
    <li class="list-group-item bg-transparent ps-0"><b>🚦 Bloqueio Inteligente na Ocorrência 01:</b> Durante a análise ou se a foto estiver borrada/ilegível, o botão <i>'Confirmar Registro'</i> fica bloqueado com feedback visual claro e botão direto para <i>'Tirar nova foto'</i>.</li>
    <li class="list-group-item bg-transparent ps-0"><b>⚡ Otimização Extrema para Aparelhos 4GB:</b> Todo o cálculo ocorre em micro-operações assíncronas sobre uma cópia temporária reduzida (≤1280px), consumindo menos de 6MB de RAM temporária e descartando recursos de memória imediatamente.</li>
    <li class="list-group-item bg-transparent ps-0"><b>📦 Exceção para Retenção e Insucessos:</b> Canhotos retidos para conferência e ocorrências de insucesso/devolução não exigem validação de foto, garantindo agilidade na rotina de rua.</li>
    <li class="list-group-item bg-transparent ps-0"><b>🛡️ Resiliência & Zero Travamento:</b> Em caso de timeout ou incompatibilidade de hardware, o sistema aciona fallback automático seguro sem impedir a finalização da entrega pelo motorista.</li>
</ul>""",
            "categoria": "NOVIDADE",
            "imagem_url": "/static/images/megafone_3d.png",
            "tags": "Qualidade de Imagem, Canhotos, Mobile, PWA, Otimização 4GB, Inteligência Artificial",
            "autor": "Equipe de Engenharia RXTrack",
            "data_publicacao": django.utils.timezone.now(),
            "destaque": True,
            "ativo": True,
        }
    )


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(adicionar_patch_v2_5_0, reverse_code=migrations.RunPython.noop),
    ]
