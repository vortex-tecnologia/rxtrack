from rest_framework.views import APIView
from rest_framework.response import Response
from manifesto.models import Ocorrencia

class ListarOcorrenciasView(APIView):
    def get(self, request):
        ocorrencias = Ocorrencia.objects.all().order_by('codigo_tms')
        
        data = [
            {
                'codigo_tms': occ.codigo_tms,
                'descricao': occ.descricao,
                'tipo': occ.tipo
            }
            for occ in ocorrencias
        ]
        
        return Response(data)