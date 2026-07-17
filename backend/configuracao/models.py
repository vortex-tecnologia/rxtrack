from django.db import models


class ConfiguracaoSistema(models.Model):
    """
    Model Singleton - Sempre terá apenas 1 registro no banco.
    Gerencia tokens, URLs e feature flags do sistema.
    Editável pelo Django Admin sem necessidade de redeploy.
    """

    class Meta:
        verbose_name = "Configuração do Sistema"
        verbose_name_plural = "Configuração do Sistema"

    # ===== TOKENS DA API ESL =====
    token_analytics = models.CharField(
        max_length=200, 
        blank=True, 
        default="",
        verbose_name="Token Data Export / GraphQL",
        help_text="Token para endpoints de Analytics, Data Export e GraphQL da ESL (zy...kw)"
    )
    token_invoices = models.CharField(
        max_length=200, 
        blank=True, 
        default="",
        verbose_name="Token Invoices / Ocorrências",
        help_text="Token para endpoints de Invoice Occurrences, Freights e Picks da ESL (jz...LA)"
    )

    # ===== DOMÍNIO BASE ESL =====
    dominio_esl = models.CharField(
        max_length=200, 
        default="quickdelivery.eslcloud.com.br",
        verbose_name="Domínio ESL",
        help_text="Ex: quickdelivery.eslcloud.com.br"
    )

    # ===== IDs DE REPORTS =====
    report_validacao = models.CharField(
        max_length=20, 
        default="2972",
        verbose_name="ID Report Validação",
        help_text="ID do report de validação de manifestos"
    )
    report_busca_nfe = models.CharField(
        max_length=20, 
        default="9873",
        verbose_name="ID Report Busca NF-e",
        help_text="ID do report de busca de notas fiscais"
    )
    report_coletas = models.CharField(
        max_length=20, 
        default="11324",
        verbose_name="ID Report Busca Coletas",
        help_text="ID do report de busca de coletas"
    )

    # ===== FEATURE FLAGS (Liga/Desliga) =====
    processar_yolo = models.BooleanField(
        default=True,
        verbose_name="🤖 Processar YOLO (Recorte de Canhoto)",
        help_text="Se desligado, a foto vai direto para o TMS sem recorte da IA"
    )
    processar_ocr = models.BooleanField(
        default=True,
        verbose_name="📖 Processar OCR (Leitura/Rotação)",
        help_text="Se desligado, a IA não tenta ler nem girar o canhoto"
    )
    enviar_tms = models.BooleanField(
        default=False,
        verbose_name="📤 Enviar para TMS (Integração ESL)",
        help_text="Se desligado, as baixas são salvas no app mas NÃO enviadas ao TMS. Ideal para ambiente de desenvolvimento."
    )
    enviar_email_falhas = models.BooleanField(
        default=False,
        verbose_name="📧 Enviar E-mail de Falhas",
        help_text="Se ligado, envia e-mail quando uma integração com TMS falhar"
    )
    emails_notificacao = models.TextField(
        blank=True,
        default="",
        verbose_name="📨 E-mails para Notificações",
        help_text="E-mails que vão receber as notificações de falha. Separe múltiplos e-mails por vírgula. Ex: cliente@empresa.com, gestor@empresa.com"
    )
    armazenar_foto_backup = models.BooleanField(
        default=True,
        verbose_name="💾 Armazenar Foto Original (Backup)",
        help_text="Se desligado, não salva a foto original no campo comprovante_original_url"
    )

    habilitar_chat_sac = models.BooleanField(
        default=False,
        verbose_name="💬 Habilitar Chat SAC (App)",
        help_text="Se ligado, o ícone de chat flutuante será visível para os motoristas no app Mobile."
    )

    # ===== MÓDULO: TORRE DE ERROS =====
    modulo_torre_erros = models.BooleanField(
        default=False,
        verbose_name="🚨 Módulo Torre de Controle de Erros",
        help_text="Se desativado, a Torre de Erros não aparece no menu e nenhum log é gerado."
    )

    # ===== PROVEDOR TMS =====
    TMS_CHOICES = [
        ('esl_cloud', 'ESL Cloud'),
        ('totvs', 'TOTVS'),
        ('sap_tm', 'SAP TM'),
        ('intelipost', 'Intelipost'),
        ('nenhum', 'Sem integração TMS'),
    ]
    tms_provider = models.CharField(
        max_length=30,
        choices=TMS_CHOICES,
        default='esl_cloud',
        verbose_name="🔗 Provedor TMS",
        help_text="Define qual sistema TMS este cliente usa para integração de manifestos."
    )
    tms_config = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="⚙️ Configuração JSON do TMS",
        help_text="Parâmetros de configuração extras específicos para o TMS (ex: tokens secundários, credenciais, etc)."
    )
    
    grupos_relatorio_whatsapp = models.TextField(
        blank=True,
        default="",
        verbose_name="Grupos para Relatório Diário",
        help_text="Lista de JIDs dos grupos de WhatsApp separados por vírgula que receberão o relatório 22h."
    )

    # ===== CÓDIGOS DE OCORRÊNCIA QUE ATIVAM A IA =====
    codigos_ocorrencia_yolo = models.CharField(
        max_length=100,
        default="01,02,1,2",
        verbose_name="Códigos que ativam YOLO",
        help_text="Códigos de ocorrência TMS separados por vírgula que passam pelo Agente IA (ex: 01,02,1,2)"
    )

    # ===== CONTROLE SINGLETON =====
    def save(self, *args, **kwargs):
        # Garante que só exista 1 registro
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Impede exclusão do único registro
        pass

    @classmethod
    def load(cls):
        """Carrega ou cria a configuração singleton"""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Configuração do Sistema"

    def get_codigos_yolo_list(self):
        """Retorna a lista de códigos como array"""
        return [c.strip() for c in self.codigos_ocorrencia_yolo.split(',') if c.strip()]

    def get_emails_notificacao_list(self):
        """Retorna a lista de e-mails de notificação como array limpo"""
        return [e.strip() for e in self.emails_notificacao.split(',') if e.strip()]
