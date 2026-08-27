# RULES.md — Regras Permanentes para Agentes de IA

> Este arquivo contém diretrizes obrigatórias e restrições comportamentais para qualquer agente que atue neste repositório.

---

## 1. Integridade do Sistema em Produção
1. **O sistema já está em produção**: Nunca assuma que este é um projeto greenfield/novo.
2. **Sem alterações destrutivas**: Nunca resete bancos de dados, não apague tabelas e não execute comandos de deleção em massa.
3. **Migrations obrigatórias**: Qualquer alteração em modelos ORM deve ser acompanhada de uma migration Django gerada e testada.
4. **Sem mudanças silenciosas**: Nunca remova campos, regras de negócio ou sinais existentes sem documentar e obter aprovação explícita.

---

## 2. Multi-Tenancy e Isolamento
1. **Respeito absoluto ao schema do tenant**: O sistema usa `django-tenants`. Toda query de modelo dentro de `TENANT_APPS` deve ser executada dentro do schema do tenant ativo.
2. **Nunca misturar dados entre tenants**: Jamais permitir que um usuário/motorista acesse manifestos ou notas pertencentes a outro schema/empresa.
3. **Redis & Cache Tenant-Aware**: Toda chave de cache no Redis que guarde dados de negócio deve conter o prefixo com o schema do tenant (ex: `routing:{schema_name}:...`).
4. **Celery com TenantAwareCelery**: Tarefas assíncronas devem sempre propagar o contexto do tenant correspondente.

---

## 3. Arquitetura e Padrões de Projeto
1. **Regra de Não-Acoplamento**:
   - Views **nunca** chamam APIs externas (OSRM, Google, TMS, etc.) diretamente.
   - O fluxo obrigatório é: `View / Task → Service → Provider / Adapter → API Externa`.
2. **Padrão Provider / Adapter**: Novos serviços externos devem implementar contratos abstratos (`ABC`), a exemplo de `BaseTMSAdapter` e `BaseRoutingProvider`.
3. **Regra de Não-Duplicação (DRY)**: Antes de criar um novo modelo, serializer, helper ou endpoint, verificar se já existe equivalente no projeto.
4. **Lógica de Negócio no Backend**: O PWA/Mobile é uma camada de apresentação e captura de dados (GPS, fotos). Toda validação e cálculo de regras pertence ao backend Django.

---

## 4. Segurança e Infraestrutura
1. **Zero Secrets no Código**: Tokens, senhas de banco, chaves de API e credenciais jamais devem ser colocados hardcoded no código ou nos templates. Use variáveis de ambiente via `.env`.
2. **Containers Internos**: Serviços de apoio (como `osrm-backend`) devem ficar exclusivamente na rede interna do Docker (`rxtrack_homolog_network`), sem expor portas para a internet.
3. **Validação de Autenticação**: Coordenadas de GPS enviadas por motoristas devem ser autenticadas via sessão do usuário, token JWT ou `DeviceToken`. Nunca confiar em IDs enviados arbitrariamente no corpo da requisição sem checagem de autorização.
4. **Resiliência e Fallbacks**: Chamadas HTTP para serviços de roteamento ou TMS devem possuir timeouts curtos (máx. 3s a 5s) e tratamento gracioso de exceções. Se o OSRM estiver fora do ar, o Django **não pode** quebrar ou travar a requisição.

---

## 5. Manutenção da Memória Técnica (.ai/)
1. **Fonte de Verdade**: O código fonte real é a fonte primária de verdade. Se houver divergência entre o código e a documentação em `.ai/`, atualize a documentação.
2. **Atualização Contínua**: Sempre que fizer mudanças estruturais relevantes (novo modelo, novo provider, nova task, nova decisão):
   - Atualizar `PROJECT_CONTEXT.md` (se novos módulos/modelos forem criados)
   - Atualizar `ARCHITECTURE.md` (se novos fluxos/serviços surgirem)
   - Atualizar `ROUTING_CONTEXT.md` (se o roteamento for expandido)
   - Atualizar `DECISIONS.md` (se uma decisão técnica for tomada ou alterada)
   - Atualizar `CHANGELOG.md` (com o resumo das entregas)
   - Atualizar `TODO.md` (marcando itens concluídos)
3. **Economia de Contexto/Tokens**: Agentes futuros devem consultar primeiramente os arquivos de `.ai/` para obter contexto antes de ler recursivamente todos os diretórios do projeto.
