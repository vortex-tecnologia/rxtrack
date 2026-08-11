from rest_framework.views import APIView
from rest_framework.response import Response
from manifesto.models import Ocorrencia

class ListarOcorrenciasView(APIView):
    def get(self, request):
        is_coleta = request.query_params.get('is_coleta')
        queryset = Ocorrencia.objects.all()
        
        if is_coleta == 'true':
            queryset = queryset.filter(is_coleta=True)
            
        ocorrencias = queryset.order_by('codigo_tms')
        
        data = [
            {
                'codigo_tms': occ.codigo_tms,
                'descricao': occ.descricao,
                'tipo': occ.tipo,
                'is_coleta': occ.is_coleta
            }
            for occ in ocorrencias
        ]
        
        return Response(data)