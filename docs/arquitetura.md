# Arquitetura — IORM Radar v3

Visão geral de como os módulos se conectam. Para o "porquê" de cada
escolha, ver `docs/decisoes.md`. Para "como usar", ver `README.md`.

## Camadas

```
paginas/*.py        → só desenha a tela e chama processamento/. Nunca
                        calcula score, valida dado ou monta SQL direto.
processamento/*.py   → toda a lógica: validação, cálculo de score,
                        motor de aderência, acesso ao banco. Testável
                        sem abrir o Streamlit (é por isso que os 147
                        testes rodam em ~2s).
coleta/*.py          → os únicos scripts que falam com APIs externas
                        (SALIC). Rodam fora do Streamlit, por linha de
                        comando.
dados/iorm_radar.db  → SQLite, um arquivo só. 19 tabelas (ver abaixo).
```

`paginas/_shared.py` é a fronteira entre as duas primeiras camadas: abre
a conexão SQLite, carrega e cacheia (`st.cache_data`, TTL 60s) os
DataFrames que várias páginas reaproveitam, e concentra o sistema visual
(tokens de cor, cabeçalho, seções, badges de status).

## Como o Cérebro da OSC alimenta o resto do sistema

Este é o fio condutor da v3 — sem ele, cada módulo seria uma ilha.

```
osc / osc_territorios (Cérebro da OSC)
        │
        ▼
_shared.obter_territorio_osc()  → lista de cidades estratégicas
        │
        ├──▶ metricas.estatisticas_gerais(cidades_estrategicas=...)
        │     metricas.carregar_empresas(cidades_estrategicas=...)
        │     metricas.resumo_cidades_iorm(cidades_estrategicas=...)
        │          → define "cidade_estrategica" no Radar de Empresas
        │            e no cálculo do IORM Score
        │
        └──▶ osc.carregar_perfil_completo() (território + temas +
              programas + público)
                  │
                  ▼
             editais.calcular_aderencia(edital, perfil)
                  → nota 0–10 do Radar de Editais
```

Editar o território ou os temas na tela Cérebro da OSC muda, na próxima
carga de dados, quais empresas contam como prioritárias e como cada
edital é pontuado — sem precisar editar código. `osc.semear_organizacao_padrao()`
só popula esses dados na primeira execução (tabela `osc` vazia); depois
disso, edições manuais nunca são sobrescritas.

## Abstração de provedor de busca

```
processamento/busca_providers.py
    SearchProvider (ABC)
        ├── SerpApiProvider     → usa SERPAPI_API_KEY do .env
        └── FilaManualProvider  → sempre disponível, não busca nada

obter_provider_ativo() → SerpApiProvider se houver chave, senão FilaManualProvider

processamento/pesquisa_empresa.py
    pesquisar_empresa(conexao, empresa_id, nome, cidade, provider)
        → chama provider.buscar() com 2 queries (site oficial / ESG)
        → classifica cada resultado (site/linkedin/instagram/...)
        → grava em presenca_digital / evidencias, nunca com confiança "ALTO"
          (é busca automática não revisada por humano)
```

Trocar de provedor de busca no futuro (ex: sair da SerpApi) significa
escrever uma nova subclasse de `SearchProvider` — a orquestração em
`pesquisa_empresa.py` e a UI em `radar_empresas.py` não mudam.

## Scoring — sempre explicável, nunca fabricado

| Score | Onde | Fórmula |
|---|---|---|
| IORM Score (0–100) | `metricas.py` | afinidade histórica: já doou via Rouanet, cidade estratégica, já apoiou projeto do IORM |
| Contactability Score (0–100) | `metricas.py` | achamos site / e-mail / telefone / LinkedIn? |
| Prioridade de Prospecção (0–100) | `metricas.py` | 0,5×IORM + 0,5×Contactability + bônus de 10 se houver evidência de ESG |
| Aderência de edital (0–10) | `editais.calcular_aderencia` | média ponderada de 6 critérios (área 25%, território 20%, público 15%, elegibilidade 15%, valor 10%, prazo 15%), **renormalizada só sobre os critérios com dado disponível** — nunca inventa um critério que falta |

Nenhum machine learning é usado em nenhum score. Todas as fórmulas ficam
visíveis para o usuário na página Configurações, e o motor de aderência
mostra "por que recomendamos" e "pontos de atenção" por edital.

## Tabelas do banco (19)

**Radar de empresas / incentivos** (v1–v2): `empresas`, `incentivos`,
`fontes`, `presenca_digital`, `contatos`, `evidencias`,
`historico_pesquisa`.

**Cérebro da OSC** (v3): `osc`, `osc_territorios`, `osc_areas_atuacao`,
`osc_programas`, `osc_mecanismos`, `osc_links`, `osc_documentos`,
`osc_palavras_chave`. Cada linha carrega `origem` (FONTE_EXTERNA/MANUAL)
e, quando aplicável, `fonte`/`data`.

**Radar de Editais** (v3): `editais`, `editais_aderencia` (o resultado
calculado fica salvo, mas é sempre recalculável a partir do perfil atual
da OSC — "🧭 Encontrar oportunidades para minha OSC" recalcula todas).

**Pipeline / CRM** (v3): `crm_oportunidades` (pode referenciar uma
`empresa_id` e um `programa_relacionado` do Cérebro da OSC, ambos
opcionais), `crm_interacoes` (timeline de contatos feitos).

Todas as migrações de schema são idempotentes: checam `PRAGMA
table_info()` antes de `ALTER TABLE`, e as `CREATE TABLE ... IF NOT
EXISTS` já incluem as colunas mais recentes, para que um banco novo (ex:
de teste) nasça no formato atual sem precisar de migração nenhuma.

## O que explicitamente não existe ainda

- Autenticação / multi-usuário / seleção de OSC ativa (arquitetura
  pronta para isso — ver `docs/decisoes.md` item 7.8 — mas não
  implementado).
- Fonte automática de editais (nenhuma API/portal brasileiro real e
  gratuito foi encontrado nesta etapa — pesquisa documentada em
  `docs/decisoes.md` item 7.4).
- Migração para Postgres (schema não impede, mas segue em SQLite).

## v9 — projetos × edital e descoberta nacional

**Projetos × edital** (`processamento/projetos_editais.py`): `analisar(edital, perfil)` compara o texto do edital com `osc_programas` e devolve, por
projeto, nível (Alta/Média/Baixa/Não identificada), evidências, justificativa e o detalhamento (área/tema, território, público); a elegibilidade
é calculada à parte por `avaliar_elegibilidade`. Fica salva em `editais_projetos` e `editais_analise` com hash da base (edital + Cérebro da OSC +
versão da regra); `garantir_analise`/`reanalisar_todos` recalculam só o que mudou. Sem IA generativa.

**Alta aderência no Dashboard:** `editais.abertos_com_aderencia` → filtro `situação = ABERTO ∧ nota ≥ 7,0 ∧ critérios ≥ 3` em `paginas/dashboard.py`.
Todos os que passam são exibidos (paginação explícita acima de 6). Os critérios dependem de o extrator preencher território/requisitos/valor/público
a partir da página do edital.

**Descoberta de empresas** (`processamento/descoberta_empresas.py`): `CompanyDiscoveryProvider` (SALIC, SerpApi Maps, Apollo, Lusha, Snov.io);
`executar_descoberta` percorre os níveis 1→4 respeitando meta diária, limite por provedor, teto de chamadas e cota; `ingerir` aplica a deduplicação
(CNPJ → domínio → id externo → nome+local → parecido só sinaliza) e grava a proveniência em `empresas_origens`. Empresa sem CNPJ =
`estagio_cadastro = CANDIDATA` (fora dos prospects). **Rotina em etapas** em `processamento/rotina_etapas.py` (`rotina_etapas`).
Tabelas novas: `empresas_origens`, `descoberta_execucoes`, `descoberta_itens`, `descoberta_estado`, `descoberta_providers`, `uso_api_eventos`,
`rotina_etapas`, `editais_projetos`, `editais_analise`; colunas novas em `empresas`: `dominio`, `estagio_cadastro`, `possivel_duplicata_de`,
`origem_descoberta`. Conectores MCP (Apollo/Lusha/Snov.io) ≠ provedores do app: ver `docs/decisoes.md` 11.3.