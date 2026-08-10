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
