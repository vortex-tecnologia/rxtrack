# Roteirização Manual do Motorista — RXTrack

## 1. Visão Geral e Objetivo
A funcionalidade de **Roteirização Manual do Track** permite que o motorista organize manualmente a sequência de entregas e coletas de um manifesto ativo via interface interativa com arrasto (Drag-and-Drop) e mapa Leaflet. A rota gerada torna-se uma entidade persistente da sessão do manifesto e alimenta diretamente os aplicativos externos de navegação (**Waze** e **Google Maps**), respeitando estritamente a sequência definida pelo motorista.

---

## 2. Mapa de Arquivos e Componentes

| Arquivo | Função / Responsabilidade |
| :--- | :--- |
| `backend/manifesto/rotas/listagem.py` | Expõe `latitude`, `longitude` e `cep` da `NotaFiscal` no endpoint do manifesto para consumo do frontend sem necessidade de geocodificação adicional. |
| `backend/templates/aplicativo/manifesto.html` | Inclusão dos assets do **Leaflet 1.9.4** e **SortableJS 1.15.2**, modal `#modalRoteirizacao`, modal `#modalEscolhaNavegador`, e estilos visuais dos marcadores. |
| `backend/static/js/manifesto_v19.js` | Injeção do container do banner de rota (`#container-roteirizacao-principal`), hooks no fluxo de baixa de entrega (`processarSumiçoNota`) e coleta (`salvarRegistroColeta`), e refresh no retorno de background. |
| `backend/static/js/roteirizacao_v1.js` | Motor de roteirização: persistência local, máquina de estados, sincronização de lista, marcadores e polyline, cálculo de estimativas e geração dos deep links. |
| `backend/tests/test_roteirizacao_suite.py` | Suíte de testes automatizados cobrindo os 10 requisitos de negócio. |

---

## 3. Máquina de Estados da Rota

Cada parada da rota assume rigorosamente um dos seguintes estados:

- **`CONCLUIDA`**: A entrega/coleta já foi realizada e baixada (online ou offline).
- **`ATUAL`**: **Exatamente UMA nota** por vez. É a primeira nota selecionada da sequência que ainda não foi concluída.
- **`PENDENTE`**: Todas as notas selecionadas subsequentes à nota atual.
- **`DESMARCADA`**: Notas desmarcadas pelo motorista para não fazerem parte do trajeto roteirizado.

### Regra de Transição Pós-Baixa:
1. Quando a nota `ATUAL` é baixada (seja por foto com IA ou ocorrência), a função `Roteirizacao.avancarProximaEntregaAposBaixa(numeroNF)` é disparada.
2. A nota recebe `concluida = true` e estado `CONCLUIDA`.
3. A próxima nota pendente na sequência escolhida pelo motorista é promovida a `ATUAL`.
4. O banner e o botão `[ NAVEGAR PARA PRÓXIMA ]` são atualizados em tempo real com os dados do novo destino.

---

## 4. Persistência de Sessão da Rota

A rota é tratada como uma entidade de sessão persistida em `localStorage` sob a chave:
```
rxtrack_rota_${manifestoId}
```

### Estrutura do Objeto Persistido:
```json
{
  "manifestoId": "7385",
  "atualizadoEm": "2026-09-06T22:30:00.000Z",
  "segmentoGoogleAtual": 0,
  "paradas": [
    {
      "id": 101,
      "numero": "12345",
      "chave": "3326...",
      "destinatario": "DROGARIA SAO PAULO",
      "endereco": "AVENIDA BRASIL, 1500, RIO DE JANEIRO, RJ",
      "cep": "21040-360",
      "latitude": -22.8645,
      "longitude": -43.2532,
      "tipo": "ENTREGA",
      "concluida": false,
      "selecionada": true,
      "estado": "ATUAL",
      "ordem": 1
    }
  ]
}
```

---

## 5. Prioridade de Coordenadas e Fallback de Endereço

1. **Prioridade Absoluta**: Se `latitude` e `longitude` do model `NotaFiscal` forem válidos, eles são utilizados diretamente nos links de navegação:
   - Google Maps: `&origin=...&destination=-22.8645,-43.2532&waypoints=...`
   - Waze: `https://waze.com/ul?ll=-22.8645,-43.2532&navigate=yes`
2. **Fallback**: Caso as coordenadas estejam ausentes ou zeradas:
   - O endereço é higienizado removendo quebras de linha e sufixado com `, Brasil`.
   - Google Maps: `&destination=AVENIDA%20BRASIL...`
   - Waze: `https://waze.com/ul?q=AVENIDA%20BRASIL...&navigate=yes`

---

## 6. Integração com Aplicativos de Navegação

### Google Maps (Estratégia de Segmentação)
O Google Maps Directions API suporta no máximo 1 origem, 9 waypoints intermediários e 1 destino por URL (total de 10 paradas por lote).
- Para rotas com **até 10 paradas**: URL única contendo todas as paradas em sequência exata.
- Para rotas com **mais de 10 paradas**: O Track divide automaticamente em **trechos ordenados** (ex: Trecho 1: paradas 1 a 10; Trecho 2: paradas 11 a 20).
- Conforme o motorista baixa as notas do primeiro trecho, o Track ajusta a lista pendente e prepara o próximo trecho sem perda de paradas.

### Waze (Parada Atual Guiada)
O protocolo do Waze não suporta waypoints intermediários via deep link.
- O Track envia **exclusivamente a parada com estado `ATUAL`**.
- Ao concluir a baixa no Track, o sistema promove a próxima parada e atualiza o botão `NAVEGAR PARA PRÓXIMA (Waze)`.

---

## 7. Compatibilidade Android e PWA

O disparo de links de navegação utiliza uma abordagem resiliente:
1. **Capacitor Nativo**: Tenta abrir via `window.Capacitor.Plugins.AppLauncher.openUrl({ url })`.
2. **Intent Nativo**: Tenta `window.open(url, '_system')`.
3. **Fallback PWA**: `window.location.href = url` ou tag `<a>` com `target="_blank"`.

### Ciclo de Vida em Background:
Quando o motorista sai do aplicativo para navegar no Waze/Google Maps e retorna ao Track:
- Os eventos `visibilitychange` e `focus` disparam `tratarRetornoAppFoco()`.
- O Track sincroniza baixas pendentes e atualiza o banner da rota sem recarregar a tela inteira.
