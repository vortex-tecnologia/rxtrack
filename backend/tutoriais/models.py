from django.db import models

class VideoTreinamento(models.Model):
    titulo = models.CharField(max_length=255, verbose_name="Título do Vídeo")
    descricao = models.TextField(blank=True, null=True, verbose_name="Descrição (Opcional)")
    url_youtube = models.URLField(verbose_name="URL do YouTube (Não listado)")
    
    visualizacoes = models.PositiveIntegerField(default=0, verbose_name="Nº de Visualizações")
    likes = models.PositiveIntegerField(default=0, verbose_name="👍 Gostei")
    dislikes = models.PositiveIntegerField(default=0, verbose_name="👎 Não Gostei")
    
    ativo = models.BooleanField(default=True, verbose_name="Vídeo Ativo?")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Criado Em")

    def __str__(self):
        return f"{self.titulo} ({self.visualizacoes} views)"

    class Meta:
        verbose_name = "Vídeo de Treinamento"
        verbose_name_plural = "Central de Treinamentos"
        ordering = ['-created_at']
