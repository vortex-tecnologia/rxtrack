from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.utils.timezone import localtime
from celery import shared_task

@shared_task(bind=True, max_retries=3)
def enviar_email_erro_tms_task(self, baixa_id, mensagem_erro):
    from manifesto.models import BaixaNF
    
    try:
        # Busca corrigida: nota_fiscal em vez de nota
        baixa = BaixaNF.objects.select_related(
            'nota_fiscal__manifesto__filial', 
            'nota_fiscal__manifesto__motorista',
            'ocorrencia'
        ).get(id=baixa_id)
        
        nota = baixa.nota_fiscal
        manifesto = nota.manifesto
        filial = manifesto.filial
        
        # --- LÓGICA DE DESTINATÁRIOS ---
        destinatarios = ['legalhints@gmail.com', 'suporte@rdexp.com.br']
        if filial and filial.email_sac:
            emails_filial = [e.strip() for e in filial.email_sac.split(',') if e.strip()]
            destinatarios.extend(emails_filial)
        destinatarios = list(set(destinatarios))

        if not destinatarios:
            return "Nenhum destinatário encontrado."

        # --- MONTAGEM DO HTML (Baseado no seu código) ---
        # Definindo as variáveis para o f-string
        filial_nome = filial.nome if filial else 'N/A'
        manifesto_num = manifesto.numero_manifesto
        motorista_nome = manifesto.motorista.nome_completo
        nota_num = nota.numero_nota
        chave = nota.chave_acesso
        destinatario_nome = nota.destinatario
        tipo_baixa = baixa.get_tipo_display()
        ocorrencia_desc = baixa.ocorrencia.descricao if baixa.ocorrencia else 'N/A'
        data_baixa = localtime(baixa.data_baixa).strftime('%d/%m/%Y %H:%M')
        foto_url = baixa.comprovante_foto_url if hasattr(baixa, 'comprovante_foto_url') else None

        html_content = f"""
        <table width="600" align="center" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #e2e8f0;">
            <tr>
              <td bgcolor="#0f172a" align="center" style="padding:20px;">
                <img src="https://rdexp.com.br/images/logo.png" alt="Logo" width="160" style="display:block;">
              </td>
            </tr>
            <tr>
              <td style="padding:20px; font-family: Arial, sans-serif;">
                <h2 style="margin:0;color:#c62828;">🚨 Falha na Integração Automática</h2>
                <p style="margin-top:8px;color:#333333;">Foi detectado um erro na integração com o <strong>ESL Cloud</strong>.</p>
              </td>
            </tr>
            <tr>
              <td style="padding:0 20px 15px; font-family: Arial, sans-serif;">
                <h3 style="margin-bottom:5px;border-bottom:1px solid #dddddd;">📦 Dados da Operação</h3>
                <p><strong>Filial:</strong> {filial_nome}</p>
                <p><strong>Manifesto:</strong> #{manifesto_num}</p>
                <p><strong>Motorista:</strong> {motorista_nome}</p>
              </td>
            </tr>
            <tr>
              <td style="padding:0 20px 15px; font-family: Arial, sans-serif;">
                <h3 style="margin-bottom:5px;border-bottom:1px solid #dddddd;">📄 Dados da Nota Fiscal</h3>
                <p><strong>NF:</strong> {nota_num}</p>
                <p><strong>Chave:</strong><br><small>{chave}</small></p>
                <p><strong>Destinatário:</strong> {destinatario_nome}</p>
                <p><strong>Tipo de Baixa:</strong> {tipo_baixa}</p>
                <p><strong>Ocorrência:</strong> {ocorrencia_desc}</p>
                <p><strong>Data:</strong> {data_baixa}</p>
              </td>
            </tr>
            <tr>
              <td style="padding:0 20px 15px; font-family: Arial, sans-serif;">
                <h3 style="margin-bottom:5px;border-bottom:1px solid #dddddd;">📸 Comprovante</h3>
                {f'<p><a href="{foto_url}" target="_blank">Abrir imagem</a></p><img src="{foto_url}" width="500" style="display:block;border:1px solid #ccc;">' if foto_url else '<p>Sem foto.</p>'}
              </td>
            </tr>
            <tr>
              <td style="padding:0 20px 20px; font-family: Arial, sans-serif;">
                <h3 style="color:#b71c1c;border-bottom:1px solid #f2bcbc;">⚠️ Detalhes do Erro Técnico (TMS)</h3>
                <table width="100%" cellpadding="10" cellspacing="0" bgcolor="#fdecea">
                  <tr><td style="color:#7f1d1d;font-family:monospace;font-size:12px;">{mensagem_erro}</td></tr>
                </table>
              </td>
            </tr>
            <tr>
              <td bgcolor="#f1f1f1" align="center" style="padding:12px;font-size:11px;color:#666666; font-family: Arial, sans-serif;">
                Este é um e-mail automático — Aplicativo Entrega Rápida
                <br>                Desenvolvido por Luiz Gustavo
              </td>

            </tr>
        </table>
        """

        subject = f"⚠️ Falha Integração NF {nota_num} - {filial_nome}"
        text_content = strip_tags(html_content) # Versão em texto para e-mails que não abrem HTML

        msg = EmailMultiAlternatives(subject, text_content, settings.DEFAULT_FROM_EMAIL, destinatarios)
        msg.attach_alternative(html_content, "text/html")
        msg.send()

        return f"E-mail HTML enviado para {len(destinatarios)} pessoas."

    except BaixaNF.DoesNotExist:
        return f"Erro: Baixa {baixa_id} não encontrada."
    except Exception as e:
        raise self.retry(exc=e, countdown=60)