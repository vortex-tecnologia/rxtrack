from django.db import migrations


def adicionar_patch_v2_5_0_configuracao(apps, schema_editor):
    AtualizacaoSistema = apps.get_model('configuracao', 'AtualizacaoSistema')

    # Desmarca destaque de versões anteriores
    AtualizacaoSistema.objects.filter(destaque=True).update(destaque=False)

    AtualizacaoSistema.objects.update_or_create(
        versao="v2.5.0",
        defaults={
            "titulo": "Validação Instantânea de Qualidade de Canhotos no App (V1)",
            "resumo": "Novo motor leve no frontend que avalia nitidez, iluminação e contraste do canhoto em tempo real antes de liberar a baixa da entrega.",
            "conteudo": """<h5>📸 Principais Destaques do Patch v2.5.0:</h5>
<ul>
    <li><b>Diagnóstico Técnico em Tempo Real:</b> Avalia nitidez (variância do Laplaciano), iluminação (escura/estourada), contraste e resolução antes do envio ao servidor.</li>
    <li><b>Bloqueio Inteligente na Ocorrência 01:</b> Durante a análise ou se a foto estiver borrada/ilegível, o botão <i>'Confirmar Registro'</i> fica bloqueado com feedback visual claro e botão direto para <i>'Tirar nova foto'</i>.</li>
    <li><b>Otimização para Aparelhos 4GB:</b> Todo o cálculo ocorre em micro-operações assíncronas sobre uma cópia temporária reduzida (≤1280px), consumindo menos de 6MB de RAM temporária e descartando recursos de memória imediatamente.</li>
    <li><b>Exceção para Retenção e Insucessos:</b> Canhotos retidos para conferência e ocorrências de insucesso/devolução não exigem validação de foto.</li>
    <li><b>Resiliência & Zero Travamento:</b> Em caso de timeout ou incompatibilidade de hardware, o sistema aciona fallback automático seguro sem travar o aplicativo.</li>
</ul>""",
            "categoria": "NOVIDADE",
            "destaque": True,
            "ativo": True,
        }
    )


class Migration(migrations.Migration):

    dependencies = [
        ('configuracao', '0012_atualizacaosistema'),
    ]

    operations = [
        migrations.RunPython(adicionar_patch_v2_5_0_configuracao, reverse_code=migrations.RunPython.noop),
    ]
