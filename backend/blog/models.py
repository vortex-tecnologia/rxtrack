from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class PostBlog(models.Model):
    """
    Model Global (SHARED_APP / schema public).
    Armazena os artigos do blog de lançamentos e patch notes da plataforma,
    sendo visível para todos os clientes e subdomínios.
    """
    versao = models.CharField(
        max_length=50, 
        verbose_name="Versão / Patch", 
        help_text="Ex: v2.4.0 ou Patch 10/08"
    )
    titulo = models.CharField(
        max_length=255, 
        verbose_name="Título da Publicação",
        help_text="Ex: Guardião de Canhotos & Verificação Inteligente de Fotos"
    )
    slug = models.SlugField(
        max_length=255, 
        blank=True, 
        null=True, 
        verbose_name="Slug (URL Amigável)"
    )
    resumo = models.CharField(
        max_length=350, 
        verbose_name="Resumo Curto",
        help_text="Texto introdutório exibido no banner da dashboard e nos cards da listagem"
    )
    conteudo = models.TextField(
        verbose_name="Conteúdo Completo (HTML)",
        help_text="Detalhes completos da atualização com listas, tópicos ou explicações"
    )
    
    CATEGORIA_CHOICES = [
        ('NOVIDADE', '🚀 Nova Funcionalidade'),
        ('MELHORIA', '⚡ Melhoria de Desempenho'),
        ('CORRECAO', '🛠️ Correção & Blindagem'),
        ('AVISO', '📢 Comunicado Geral'),
    ]
    categoria = models.CharField(
        max_length=30, 
        choices=CATEGORIA_CHOICES, 
        default='NOVIDADE', 
        verbose_name="Categoria"
    )
    
    imagem_capa = models.ImageField(
        upload_to='blog/', 
        blank=True, 
        null=True, 
        verbose_name="Imagem de Capa (Upload)"
    )
    imagem_url = models.CharField(
        max_length=500, 
        blank=True, 
        default='', 
        verbose_name="Imagem URL (Opcional)",
        help_text="URL direta ou estática (ex: /static/images/megafone_3d.png)"
    )
    
    tags = models.CharField(
        max_length=200, 
        blank=True, 
        default='IA, App Mobile, Entregas', 
        verbose_name="Tags / Palavras-chave",
        help_text="Tags separadas por vírgula (ex: IA, TMS, Notificações)"
    )
    autor = models.CharField(
        max_length=100, 
        default='Equipe RXTrack', 
        verbose_name="Autor da Publicação"
    )
    
    data_publicacao = models.DateTimeField(
        default=timezone.now, 
        verbose_name="Data e Hora de Publicação"
    )
    destaque = models.BooleanField(
        default=False, 
        verbose_name="⭐ Fixar como Destaque Principal"
    )
    ativo = models.BooleanField(
        default=True, 
        verbose_name="Publicação Ativa / Visível"
    )
    visualizacoes = models.PositiveIntegerField(
        default=0, 
        verbose_name="Nº de Visualizações"
    )

    class Meta:
        verbose_name = "Post do Blog / Patch Note"
        verbose_name_plural = "Blog de Lançamentos & Novidades"
        ordering = ['-destaque', '-data_publicacao', '-id']

    def __str__(self):
        return f"[{self.versao}] {self.titulo}"

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(f"{self.versao}-{self.titulo}")
            self.slug = base_slug[:250]
        super().save(*args, **kwargs)

    def get_tags_list(self):
        if not self.tags:
            return []
        return [t.strip() for t in self.tags.split(',') if t.strip()]

    def get_imagem_exibicao(self):
        if self.imagem_capa:
            return self.imagem_capa.url
        if self.imagem_url:
            return self.imagem_url
        return '/static/images/megafone_3d.png'


class AlertaSistema(models.Model):
    """
    Model Global (SHARED_APP / schema public).
    Alertas Operacionais e Notificações Globais da Plataforma.
    Permite aos administradores emitir avisos sobre instabilidades ou comunicados técnicos
    filtrados por provedor TMS (ex: ESL, Brudam, Todos) ou schemas específicos.
    """
    TIPO_CHOICES = [
        ('PERIGO', '🔴 Intermitência / Falha Crítica'),
        ('AVISO', '🟡 Atenção / Instabilidade Parcial'),
        ('INFO', '🔵 Informativo / Comunicado'),
        ('SUCESSO', '🟢 Normalizado / Resolvido'),
    ]

    TMS_ALVO_CHOICES = [
        ('TODOS', '🌐 Todos os Provedores (Geral)'),
        ('esl_cloud', '⚡ ESL Cloud'),
        ('brudam', '🚚 Brudam TMS'),
        ('totvs', '🏢 TOTVS'),
        ('sap_tm', '💼 SAP TM'),
        ('intelipost', '📦 Intelipost'),
        ('nenhum', '⚪ Sem integração TMS'),
    ]

    titulo = models.CharField(
        max_length=200,
        verbose_name="Título do Alerta",
        help_text="Ex: Instabilidade na integração com ESL Cloud (Despacho / Transferência)"
    )
    tipo = models.CharField(
        max_length=20,
        choices=TIPO_CHOICES,
        default='AVISO',
        verbose_name="Severidade / Tipo"
    )
    tms_alvo = models.CharField(
        max_length=30,
        choices=TMS_ALVO_CHOICES,
        default='TODOS',
        verbose_name="Provedor TMS Afetado",
        help_text="Selecione qual sistema TMS receberá este alerta. Se 'Todos', todos os clientes verão."
    )
    schemas_especificos = models.CharField(
        max_length=500,
        blank=True,
        default="",
        verbose_name="Schemas Específicos (Opcional)",
        help_text="Deixe em branco para todos os clientes do provedor selecionado. Ou separe schemas por vírgula (ex: rdexpresso, homolog)"
    )
    conteudo_html = models.TextField(
        verbose_name="Conteúdo Detalhado (HTML)",
        help_text="Escreva a mensagem em HTML com explicações, passos a tomar, prazos e orientações."
    )
    ativo = models.BooleanField(
        default=True,
        verbose_name="Alerta Ativo / Visível",
        help_text="Se desmarcado, o ícone flutuante desaparece imediatamente para todos."
    )
    fixar_topo = models.BooleanField(
        default=False,
        verbose_name="Alta Prioridade (Glow / Pulsação)",
        help_text="Se marcado, força animação de pulsação contínua e destaque no ícone flutuante."
    )
    data_criacao = models.DateTimeField(
        default=timezone.now,
        verbose_name="Data de Criação"
    )
    data_expiracao = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Data/Hora de Expiração Automática (Opcional)",
        help_text="Se preenchido, o alerta deixará de ser exibido automaticamente após esse horário."
    )

    class Meta:
        verbose_name = "Alerta do Sistema (Notificação Global)"
        verbose_name_plural = "Alertas do Sistema (Notificações Globais)"
        ordering = ['-fixar_topo', '-data_criacao', '-id']

    def __str__(self):
        return f"[{self.get_tipo_display()}] {self.titulo} ({self.get_tms_alvo_display()})"

    @property
    def cor_badge(self):
        mapa = {
            'PERIGO': 'danger',
            'AVISO': 'warning',
            'INFO': 'primary',
            'SUCESSO': 'success'
        }
        return mapa.get(self.tipo, 'warning')

    @property
    def icone_bootstrap(self):
        mapa = {
            'PERIGO': 'bi-exclamation-octagon-fill',
            'AVISO': 'bi-exclamation-triangle-fill',
            'INFO': 'bi-info-circle-fill',
            'SUCESSO': 'bi-check-circle-fill'
        }
        return mapa.get(self.tipo, 'bi-exclamation-triangle-fill')

