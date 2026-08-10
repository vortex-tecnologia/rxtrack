from django.shortcuts import render, get_object_or_404
from django.views.generic import ListView, DetailView
from django.db.models import Q
from .models import PostBlog


class BlogListView(ListView):
    model = PostBlog
    template_name = 'desktop/paginas/blog/blog_lista.html'
    context_object_name = 'posts'
    paginate_by = 12

    def get_queryset(self):
        qs = PostBlog.objects.filter(ativo=True)
        
        # Filtro de busca por texto
        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(
                Q(titulo__icontains=q) | 
                Q(resumo__icontains=q) | 
                Q(conteudo__icontains=q) |
                Q(versao__icontains=q) |
                Q(tags__icontains=q)
            )

        # Filtro por Categoria
        categoria = self.request.GET.get('categoria')
        if categoria:
            qs = qs.filter(categoria=categoria)

        # Filtro por Versão
        versao = self.request.GET.get('versao')
        if versao:
            qs = qs.filter(versao=versao)

        return qs.order_by('-destaque', '-data_publicacao', '-id')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Informações do usuário logado (se houver)
        if self.request.user.is_authenticated:
            context['usuario_nome'] = self.request.user.get_full_name() or self.request.user.username
        else:
            context['usuario_nome'] = "Usuário"

        # Post em Destaque Principal (se não houver filtros ativos)
        q = self.request.GET.get('q')
        categoria = self.request.GET.get('categoria')
        versao = self.request.GET.get('versao')
        
        if not q and not categoria and not versao:
            context['post_destaque'] = PostBlog.objects.filter(ativo=True, destaque=True).first()
            if not context['post_destaque']:
                context['post_destaque'] = PostBlog.objects.filter(ativo=True).order_by('-data_publicacao').first()
        else:
            context['post_destaque'] = None

        context['categorias'] = PostBlog.CATEGORIA_CHOICES
        context['categoria_ativa'] = categoria or ''
        context['versao_ativa'] = versao or ''
        context['busca_ativa'] = q or ''
        context['versoes_recentes'] = PostBlog.objects.filter(ativo=True).values_list('versao', flat=True).distinct()[:8]
        return context


class BlogDetailView(DetailView):
    model = PostBlog
    template_name = 'desktop/paginas/blog/blog_detalhe.html'
    context_object_name = 'post'
    slug_url_kwarg = 'slug'

    def get_object(self, queryset=None):
        # Tenta buscar por slug ou por ID
        slug = self.kwargs.get('slug')
        if slug.isdigit():
            obj = get_object_or_404(PostBlog, pk=int(slug), ativo=True)
        else:
            obj = get_object_or_404(PostBlog, slug=slug, ativo=True)
        
        PostBlog.objects.filter(pk=obj.pk).update(visualizacoes=obj.visualizacoes + 1)
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.user.is_authenticated:
            context['usuario_nome'] = self.request.user.get_full_name() or self.request.user.username
        else:
            context['usuario_nome'] = "Usuário"

        post_atual = self.object
        context['post_anterior'] = PostBlog.objects.filter(
            ativo=True, 
            data_publicacao__lt=post_atual.data_publicacao
        ).order_by('-data_publicacao').first()

        context['post_proximo'] = PostBlog.objects.filter(
            ativo=True, 
            data_publicacao__gt=post_atual.data_publicacao
        ).order_by('data_publicacao').first()

        context['posts_relacionados'] = PostBlog.objects.filter(
            ativo=True
        ).exclude(pk=post_atual.pk).order_by('-data_publicacao')[:3]

        return context
