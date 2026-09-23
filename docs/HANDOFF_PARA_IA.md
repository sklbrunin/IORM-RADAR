# IORM Radar — Documento de alinhamento (handoff para outra IA)

Estado descrito: **23/09/2026**, commit local `e70e45e` (branch `main`, 2 commits à frente do GitHub — v6 e v7 ainda NÃO foram enviados; o app público está numa versão anterior).
Este documento é autossuficiente: explica o produto, as regras que não podem ser quebradas, a arquitetura, o que foi feito em cada rodada, o estado real dos dados, o que funciona, o que não funciona e o que falta.

---

## 1. O que é o projeto

**IORM Radar** é uma plataforma de inteligência de captação de recursos (Streamlit + SQLite + Python) para o **IORM — Instituto Oswaldo Ribeiro de Mendonça**, uma OSC de Guaíra/SP que trabalha com projetos sociais, culturais e desenvolvimento territorial (educação através da arte, dança/"Usina da Dança", cultura, esporte). Polos: **Ipuã, Guaíra, Miguelópolis e Orlândia (SP)**.

Objetivo: reduzir o trabalho manual da equipe de captação. Fluxo desejado:

```
CÉREBRO DA OSC (quem somos) → RADAR de empresas (prospects) → LINHA CRUZADA (quem já tem relacionamento)
→ INCENTIVOS (histórico de apoio) → CONTATOS (pessoas e canais) → EDITAIS (oportunidades abertas)
→ CRM/Pipeline → AUTOMAÇÃO diária → FONTES configuráveis → DOCUMENTOS (contexto da OSC)
```

Usuário: equipe de captação (o dono do projeto **não é programador**; comunicação em português do Brasil, objetiva). Repositório GitHub: `sklbrunin/iorm-radar`. App público: https://iorm-radar.streamlit.app (Streamlit Community Cloud; dorme por inatividade). Rodando localmente: `python -m streamlit run app.py` → http://localhost:8501.

## 2. Regras invioláveis (leia antes de mexer em qualquer coisa)

1. **Regra de ouro dos dados: nunca inventar.** Todo dado tem valor + fonte + URL + data + nível de confiança. Ausente = "Não disponível" / "Não identificado na fonte". Estimativa/inferência é rotulada como tal. Nunca confundir inferência com fato.
2. **Nunca apagar dados existentes.** Migrações só adicionam (idempotentes: `PRAGMA table_info` + `ALTER TABLE ADD COLUMN`). Nunca recriar o banco. **Backup do banco antes de mudança estrutural** (`dados/backups/`, ignorado pelo Git).
3. **Não dizer que funciona sem testar** (pytest **e** navegador). Não marcar como concluído só porque o código foi escrito.
4. **Nunca criar links falsos.** Link de inscrição só existe se encontrado/verificável; senão exibe "Link direto de inscrição não localizado". Portal genérico nunca é passado como "link de inscrição".
5. **Prospect × relacionamento são mutuamente exclusivos** (exceto reabertura explícita com justificativa).
6. **Segurança:** `SERPAPI_API_KEY` só em `.env` (git-ignored) / Secrets do Streamlit Cloud (viram variáveis de ambiente). Nunca imprimir a chave, nunca colocar em código/README/UI. `HUNTER_API_KEY` idem (não configurada). Sem caminhos absolutos no código (compatibilidade com Streamlit Cloud).
7. **Não redesenhar do zero; auditar antes, melhorar o que existe, evitar duplicar módulos.** Antes de criar algo, verificar se já existe.
8. **Sem reticências escondendo informação importante** na UI (texto quebra linha, colunas largas, detalhe na ficha). Valores em padrão brasileiro `R$ 1.000.000,00` (só a apresentação; o valor guardado não muda).
9. Git: commits terminam com `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`. **Não dar push** — o dono faz o push/deploy por conta própria.
10. Não perguntar coisas pequenas (nome de botão, cor, estrutura); só parar para: serviço pago, API key não fornecida, decisão irreversível, risco de destruir dados.

## 3. Stack e como rodar

- Python 3.14, Streamlit 1.63 (multipage via `st.navigation`/`st.Page`), pandas, SQLite (`dados/iorm_radar.db`, **versionado no Git** — decisão consciente para o deploy na nuvem; ver privacidade em §11), requests, altair, streamlit-sortables (Kanban drag-and-drop), pypdf/python-docx/openpyxl/xlrd (extração de documentos), python-dotenv.
- Rodar app: `python -m streamlit run app.py --server.headless true`. O Streamlit **não recarrega módulos de forma confiável neste ambiente → reiniciar o processo após editar**.
- Testes: `python -m pytest -q` → **435 passando** (≈17 s).
- `IORM_RADAR_DB=<caminho>` (opcional) aponta o app para outro banco (usado para validar UI numa cópia sem tocar o banco real).
- Ambiente do dono: Windows 10, PowerShell 5.1 (sem `&&`; cuidado com BOM/encoding — scripts `.ps1` precisam de UTF-8 com BOM).
- `.streamlit/config.toml`: `maxUploadSize = 25` (MB).

## 4. Estrutura do repositório

```
app.py                      entrada: monta navegação; guarda as páginas em st.session_state["_paginas"] (para st.switch_page)
paginas/                    UI (só apresentação; sem regra de negócio)
  _shared.py                CSS/design system, formatadores, conectar(), garantir_tabelas_novas(), grafico_barras(), ir_para_pagina()
  dashboard.py  radar_empresas.py  oportunidades.py (Oportunidades / Radar por Região / Linha Cruzada)
  radar_editais.py  cerebro_osc.py  contatos.py  crm.py (Pipeline)  rotina_diaria.py  configuracoes.py
processamento/              regras de negócio e acesso a dados (testáveis sem Streamlit)
  banco.py                  schema base (empresas, incentivos, fontes) + migrações + inserts idempotentes
  transformacao.py validadores.py formatacao.py filtros.py relatorio.py
  metricas.py               carregar_empresas() (scores, linha_cruzada, eh_prospect), contadores_empresas(), estatísticas
  relacionamento.py         classificação Linha Cruzada (persistida)
  regiao.py geografia.py    camadas geográficas + região dos polos via IBGE
  osc.py                    Cérebro da OSC (perfil, territórios, programas, temas, palavras-chave, links, mecanismos)
  documentos.py             repositório de documentos (upload, extração, busca, exclusão, leitura do original)
  editais.py                editais, situação efetiva, motor de aderência, confirmar_prazo
  links_editais.py          verificação de links, extrair_prazo, link de inscrição
  busca_editais.py busca_providers.py   busca automática via SerpApi (SearchProvider abstrato)
  fontes_dados.py           Central de Fontes de Dados (cadastro, avaliação de acesso, coleta de feed RSS/Atom)
  incentivos_providers.py   IncentivoProvider por mecanismo (Rouanet integrado; demais "indisponíveis" documentados)
  mecanismos.py             registro descritivo dos mecanismos (status real de cada um)
  enriquecimento.py pesquisa_empresa.py contact_providers.py   contatos (ContactProvider: Receita Federal, SerpApi, Hunter)
  fila_enriquecimento.py    rotina diária de 30 empresas
  crm.py                    Pipeline: oportunidades, interações, follow-ups, remover/restaurar
coleta/                     scripts de linha de comando
  coleta_salic.py coleta_salic_doacoes.py coleta_diaria.py (descoberta de empresas por UF)
  coleta_incentivos.py (--listar | --mecanismo LEI_ROUANET --uf MG)   consultar_fontes.py
  enriquecimento_diario.py (--meta 30 --sem-web --somente-regiao --pausa --agendada)   agendar_enriquecimento_windows.ps1
testes/                     435 testes (unitários + AppTest de páginas)
docs/                       decisoes.md (decisões e raciocínio; itens 8 e 9 = rodadas v6 e v7), arquitetura.md, este arquivo
dados/                      iorm_radar.db (versionado), backups/ logs/ brutos/ documentos_osc/ (ignorados)
```

## 5. Modelo de dados (SQLite) — tabelas principais

- `empresas` (8.311): cnpj (único), razao_social, nome_fantasia, cidade, estado, status (situação cadastral), **relacionamento_iorm/tipo/fonte/em, reabrir_prospeccao, reabrir_justificativa**.
- `incentivos` (8.516, todos `mecanismo='LEI_ROUANET'`): empresa_id, fonte, tipo_incentivo, projeto, ano, valor, uf, cidade, url_fonte (UNIQUE = chave de deduplicação), coletado_em, nivel_confianca, **mecanismo**.
- `fontes` (catálogo antigo de fontes do SALIC) e **`fontes_dados`** (central configurável, v7).
- Contatos/enriquecimento: `presenca_digital`, `contatos` (UNIQUE empresa+tipo+valor), `evidencias`, `historico_pesquisa`.
- Rotina: `enriquecimento_execucoes`, `enriquecimento_itens`, `enriquecimento_estado`, `uso_api` (cota mensal por provedor).
- Cérebro da OSC: `osc`, `osc_territorios`, `osc_areas_atuacao`, `osc_programas`, `osc_palavras_chave`, `osc_links`, `osc_mecanismos`, `osc_documentos` (arquivo + texto extraído + status), `regiao_municipios` (região IBGE dos polos, com `ativo` e origem IBGE/MANUAL).
- Editais: `editais` (título, instituição, descrição, url, url_inscricao, datas, valor, território, público, requisitos, área temática, `situacao_inscricao` gravada, `origem_descoberta` [MANUAL/AUTOMATICA/FONTE_CADASTRADA/TESTE_NAO_REAL], campos de verificação de link, `prazo_sugerido`, `prazo_sugerido_trecho`, `prazo_origem`), `editais_aderencia` (histórico de cálculos).
- CRM: `crm_oportunidades` (+ `removida_em`, `motivo_remocao`), `crm_interacoes`.

## 6. Conceitos de negócio (como o sistema decide)

**Linha Cruzada × Prospect.** `relacionamento.sincronizar` marca `relacionamento_iorm=1` para: a própria OSC (por CNPJ), doadoras com projeto de programa do IORM (`metricas.PROGRAMAS_IORM`) e empresas com oportunidade "Fechado — ganho" (não removida) no CRM. Marcação manual exige justificativa. `metricas.carregar_empresas` calcula `linha_cruzada` e `eh_prospect` (= não linha cruzada, ou prospecção reaberta com justificativa). **Cinco números distintos** (`metricas.contadores_empresas`): Empresas na base (8.311) · Prospects (8.302) · Linha Cruzada (9, inclui a própria OSC) · Prospects pesquisados (46) · Prospects não pesquisados (8.256). Nunca misturar.

**Scores** (empresas): IORM Score (0–100: histórico Rouanet, CNPJ válido, detalhe por projeto, cidade estratégica 25 pts em camadas de região, projeto do IORM, faixas de valor), Contactability (0–100; só conta contato profissional com `prioridade` — sócio genérico da Receita não infla), Prioridade de Prospecção = 0,5·IORM + 0,5·Contactability (+10 se evidência ESG/instituto).

**Região.** Camadas: Cidade de atuação (25) / Região próxima (15) / Interesse estratégico (8) / fora (0). A região de cada polo = **Região Geográfica Imediata do IBGE** (API de Localidades), gravada em `regiao_municipios` (editável, motivo obrigatório, sincronização nunca reativa o que o usuário desativou). Ipuã e Orlândia compartilham a mesma região.

**Editais — situação efetiva** (`editais.situacao_efetiva`, calculada na leitura): `ABERTO` exige data de encerramento real futura + URL da fonte + nenhum sinal contrário; `ENCERRADO` se data passou / página diz encerrado / status interno; senão `NAO_CONFIRMADO` (nunca tratado como aberto). Registros `TESTE_NAO_REAL` nunca são oportunidade. Prazo mencionado numa página/trecho de busca vira apenas **sugestão** com o trecho literal; a equipe confirma (`confirmar_prazo`) → só então "Aberto".
**Aderência** (0–10, explicável): 6 critérios (área 25%, território 20%, público 15%, elegibilidade 15%, valor 10%, prazo 15%); nota = média ponderada só dos critérios com dado; critério sem dado = "Não identificado na fonte"; retorna `detalhes`, `criterios_avaliados`. No Dashboard "alta aderência" = nota ≥ 7,0 **com ≥ 3 critérios avaliados** e edital ABERTO.

**Contatos.** Distinção estrita canal da empresa × pessoa. E-mail genérico (`financeiro@`) = canal institucional com "área do e-mail", **nunca** vira pessoa. Sócios/administradores vindos da Receita (BrasilAPI: só nome+qualificação; CPF/faixa etária descartados por LGPD) entram como pessoa com origem "quadro societário" e **não são presumidos responsáveis por ESG/marketing**. Sem scraping de LinkedIn. `contact_providers.persistir()` é o único ponto de escrita (valida e-mail/telefone, sem confiança ALTA fora da Receita).

**Rotina diária (30 empresas/dia).** `fila_enriquecimento` seleciona prospects com CNPJ (exclui Linha Cruzada), prioriza nunca pesquisadas e região IORM, enriquece via Receita Federal (BrasilAPI, gratuita, sem chave) e busca web (SerpApi) só dentro do orçamento mensal (`SERPAPI_LIMITE_MENSAL` padrão 100, `SERPAPI_RESERVA_MANUAL` 20); resultado SUCESSO/PARCIAL/FALHA; falha volta em 1 dia, parcial em 3, máx. 3 tentativas; idempotente por dia; backup do banco antes de cada execução; logs em `dados/logs/`. Página admin "Rotina diária". Realidade da cota gratuita: ~26 empresas/mês com busca web; as 30/dia são enriquecidas pela Receita (QSA, situação, telefone), com a camada web "PARCIAL" quando a cota acaba.

**Fontes de dados** (`fontes_dados.py`): FONTE → `avaliar_acesso` (olha a resposta real: FEED / API_JSON / PAGINA_PUBLICA / INACESSIVEL) → só feed RSS/Atom de tipo Editais é coletado automaticamente (filtro de relevância por palavras inteiras; entra como NÃO CONFIRMADO; parser recusa XML com entidades). Demais fontes ficam registradas (consulta manual/integração futura). **Sem raspagem frágil.**

**Provedores de incentivo** (`incentivos_providers.py`): `IncentivoProvider → RegistroIncentivo → ingerir()`. Só a **Lei Rouanet (SALIC)** é integrada. Investigação de 18/09/2026: LPIE-SP (PDF de projetos, não de doadores), Lei de Incentivo ao Esporte federal (dados.gov.br responde 401 — exige token), ProAC ICMS (sem arquivo/API de empresas), PRONON/PRONAS (lista projetos, não doadores), FIA/Fundo do Idoso (sem base pública por empresa) → provedores existem só para registrar o motivo e levantam `IntegracaoIndisponivel`.

**Documentos** (Cérebro da OSC → Documentos): upload PDF/DOCX/TXT/XLSX/XLS (25 MB), original em `dados/documentos_osc/` (git-ignored), caminho guardado **relativo**, texto extraído no banco, dedupe por SHA-256, status honesto (PROCESSADO / SEM_TEXTO_EXTRAIDO / ERRO / FORMATO_NAO_SUPORTADO — sem OCR), busca literal insensível a acento com "Fonte: documento X" (nenhuma IA interpreta), download do original, exclusão só com confirmação.

**Pipeline.** Kanban drag-and-drop (9 estágios). Remover = arquivar (`removida_em`), com janela de confirmação e "Restaurar"; empresa/histórico intactos; removida não conta em valor potencial, follow-ups, atividade nem relacionamento.

## 7. Páginas (UI)

Dashboard (5 números da base; **cartões clicáveis** de editais abertos com alta aderência → `st.switch_page` para Editais com `edital_em_foco`; captação; prioridades só de prospects; funil; melhores prospects) · Cérebro da OSC (8 abas: Identidade, Território [+ Região dos polos/IBGE], Programas, Temas, Mecanismos, Links, Documentos, Palavras-chave) · Radar de Empresas (5 KPIs + abas: Radar de Prospecção, Linha Cruzada, Buscar qualquer empresa, Histórico) com tabela clicável → ficha completa · Radar de Editais (abas Abertos / Não confirmados / Encerrados e histórico / Buscar e cadastrar; ficha com situação+motivo, dados, links VER EDITAL/INSCREVER-SE, aderência por critério, confirmar prazo) · Contatos (Canais da empresa / Pessoas identificadas) · Pipeline · Oportunidades (Oportunidades, Radar por Região polo→cidades→empresas→ficha, Linha Cruzada) · Rotina diária · Configurações (Sobre, Scores, Inteligência de Contatos/ContactProvider, Mecanismos de Incentivo, Fila, **Fontes de Dados**). Abas usam `key=` para não voltar à primeira a cada ação.

## 8. Histórico de rodadas (o que foi feito)

- **v1–v3:** coleta SALIC (Lei Rouanet, SP: ~8.2 mil empresas), banco, scores, dashboard, módulo de contatos, Cérebro da OSC, Radar de Editais (cadastro + aderência), CRM.
- **v4–v5:** SerpApi real, contatos mais úteis, ficha de empresa, visual; priorização geográfica em camadas; busca real de editais; Pipeline drag-and-drop; descoberta diária de empresas (SALIC multi-UF; MG entrou com 100 empresas).
- **v6 (commit `c37abc3`):** Linha Cruzada persistida; região via IBGE; verificação de links de editais; repositório de documentos; contatos por área; `ContactProvider` (Receita Federal, SerpApi, Hunter só simulado); rotina diária de 30 empresas + agendador do Windows (testado e removido; **não instalado**); auditoria visual.
- **v7 (commit `e70e45e`):** contadores separados (Dashboard/Radar); editais só abertos + situação efetiva + prazo sugerido/confirmado; **correção de bug grave** (a busca copiava as cidades da OSC como território do edital, fabricando aderência territorial 10/10 — corrigido; edital #2 do banco real teve o campo limpo); aderência com detalhes e cobertura de critérios; Dashboard com cartões clicáveis; Central de Fontes de Dados; provedores de incentivo + coluna `mecanismo`; documentos (excluir com confirmação, baixar, caminho relativo); Pipeline (remover/restaurar); abas com key; gráficos com rótulos completos e moeda BR; 6 fontes reais cadastradas; rotina diária rodou (30/30 sucesso, 0 da Linha Cruzada); documentação (`docs/decisoes.md` itens 8–9).
- Bugs reais achados só no navegador e corrigidos: NaN em e-mail derrubando Contatos, "nan" na ficha, rótulos de gráfico cortados, região próxima vazia em Território, `.ps1` sem BOM corrompendo acentos, tamanho "0 KB", caminho absoluto exibido, campos de texto do Cérebro cortados.

## 9. Estado atual dos dados (23/09/2026)

Empresas 8.311 · Prospects 8.302 · Linha Cruzada 9 (valor histórico ≈ R$ 18,1 mi) · Incentivos 8.516 (100% Rouanet; SP + 100 de MG) · Contatos 446 (sem duplicatas) · `regiao_municipios` 30 · Editais 2 (**0 abertos**; #2 "Lançamento do 39º Edital de Fomento à Dança" = não confirmado, página verificada, sem prazo; #1 = **registro de teste inventado por mim**, marcado `TESTE_NAO_REAL`, não apagado) · `fontes_dados` 6 · Documentos 1 (enviado pela equipe) · Pipeline 4 oportunidades ativas (dados reais da equipe — **não mexer**: ex.: "nova empresa"/Mina Mercantil, "nova oportunidade"/Aguetoni, Escandinávia Veículos, "Patrocínio Usina da Dança 2026") · Rotina: 3 execuções (30 empresas em 18/09 e 30 em 21/09, todas SUCESSO). SerpApi usada no mês: 3 buscas (de 100).

## 10. Validação realizada (e o que NÃO foi)

Validado: 435 testes (inclui AppTest que renderiza todas as páginas e o fluxo Dashboard→Editais); navegador em todas as páginas/abas (desktop e 375 px, sem rolagem horizontal, sem texto cortado); upload→extração→busca→exclusão de documento; remoção/cancelamento no Pipeline; confirmação de prazo; cadastro e consulta ao vivo de fonte (feed RSS); rotina diária real; scan de segredos (nenhuma chave em arquivos versionados nem no banco). Ações que gravam foram validadas numa **cópia** do banco.
**Não testado:** Hunter contra API real (só resposta simulada; API é paga); upload de PDF/DOCX pela tela (só TXT na UI; formatos cobertos por testes automáticos); coleta de feed de edital real (nenhuma fonte cadastrada oferece feed); rotina diária com busca web dentro da cota nesta rodada; agendador do Windows instalado de forma permanente.

## 11. Limitações reais e pontos de atenção

- **0 editais abertos hoje** — não é bug: nenhum edital real tem prazo confirmado. Prosas (principal agregador) serve página montada por JavaScript, sem prazo legível por requisição simples; a equipe confirma o prazo com um clique.
- **Só a Lei Rouanet tem dados de empresas incentivadoras**; os demais mecanismos não têm fonte pública estruturada confiável (ver §6).
- **Streamlit Cloud:** disco efêmero → arquivos de documentos enviados pela tela se perdem em reinício/deploy (texto extraído fica no banco). Persistência real exigiria armazenamento externo (não implementado). O agendador do Windows e o `.env` só funcionam localmente. Escritas feitas na nuvem também não voltam para o repositório.
- **Privacidade:** `dados/iorm_radar.db` é versionado e contém texto extraído de documentos e contatos; avaliar antes de tornar o repositório público.
- Cota SerpApi gratuita (~100–250/mês) não sustenta busca web em 30 empresas/dia.
- Tabelas do Streamlit são canvas (não quebram linha): nomes muito longos dependem de colunas largas; o nome completo está sempre na ficha.
- Linha Cruzada atual inclui a própria OSC (9 registros).
- O app público ainda roda versão anterior até o `git push`.

## 12. Pendências / próximos passos

1. Dono faz `git push` (v6+v7) e confere o app público.
2. Equipe confirma prazos de editais reais para que apareçam em "Abertos"/Dashboard.
3. Opcional: token do dados.gov.br para reavaliar a Lei de Incentivo ao Esporte; instalar o agendamento (`powershell -ExecutionPolicy Bypass -File coleta\agendar_enriquecimento_windows.ps1`); decidir armazenamento externo de documentos na nuvem; plano pago SerpApi/Hunter se quiserem busca web/e-mail profissional em escala.
4. Ideias já mapeadas: usar texto dos documentos como evidência (não pontuação) na aderência de editais ("Fonte: documento X"); consulta automática de fontes via Agendador; multi-OSC (arquitetura pronta, sem login/isolamento).

## 13. Como uma IA deve trabalhar neste projeto

1. Ler este arquivo, `docs/decisoes.md` (raciocínio de cada decisão), `README.md`; `git status`/`git log`; conferir o banco e **fazer backup** antes de mudar estrutura.
2. Auditar o que existe antes de criar; estender módulos existentes; manter lógica em `processamento/` e UI em `paginas/`.
3. Migrações idempotentes; escrever testes junto (pytest + AppTest); rodar `python -m pytest -q` (esperado: 435+ verdes).
4. Validar no navegador (dev server + JS/DOM para checar texto e cortes; screenshots são instáveis em larguras emuladas; resetar viewport ao final); usar cópia do banco (`IORM_RADAR_DB`) para testar ações que gravam.
5. Relatório final honesto: o que foi testado, o que não foi, o que depende de credencial/serviço pago, limitações reais. Nunca afirmar o que não foi testado.
6. Cuidados de ambiente: PowerShell 5.1 (sem `&&`, cuidado com aspas em `python -c`, BOM em `.ps1`); reiniciar o Streamlit após editar; não imprimir segredos; não dar push.

---

## ATUALIZAÇÃO v8 (23/09/2026) — leia junto com as seções acima (o que mudou)

- **Busca de editais agora é persistente** (`processamento/busca_editais.py::executar_busca`): plano de consultas (município × Prosas, município × gov.br,
  geral por fonte, fontes cadastradas; teto 12) → **cache em `busca_editais_cache`** (7 dias) → filtros → dedupe por URL canônica → salva em `editais`
  → verifica a página → situação efetiva. "Buscar editais" reaproveita o cache (0 chamadas); só **"Atualizar busca"** força a API. Relatório real
  na tela e em `busca_editais_execucoes`. Uso da cota em `uso_api` (provedor "SerpApi"). Antes eram 3 consultas × 5 resultados (máx. 15), só em
  `st.session_state`.
- **Bug de leitura de página corrigido** (`links_editais._buscar_pagina`, `fontes_dados.buscar_http`): só o primeiro bloco da rede era lido. Por isso as
  rodadas v6/v7 concluíram, erradamente, que o Prosas é "JavaScript sem prazo". A página traz um objeto JSON embutido: `extrair_dados_estruturados`
  lê prazo, início, valor total, áreas, público e elegibilidade (`prazo_origem = FONTE_ESTRUTURADA`).
- **Cadastro pelo link** (`cadastrar_por_url`): caminho para editais que a busca não indexa (ex.: **Miguelópolis, Prosas 19173**, R$ 90.000,00, 7
  projetos, inscrições 23/09–09/10/2026 segundo a página; a busca `site:prosas.com.br/editais Miguelópolis 2026` devolveu 0 resultados por
  falta de indexação; o edital exige Pessoas Físicas residentes — o IORM é PJ). Está cadastrado no banco real (id 124, ABERTO, aderência 8,0).
- **Editais vencidos:** `hoje_brasil()` (sem data fixa); edital sem prazo com ano anterior no título/URL → ENCERRADO (motivo explícito); ordenação
  por critérios avaliados. Filtros: outra UF, concurso/licitação, universidades, listagens/portais. `SerpApi "sem resultados"` não é mais erro.
- **Linha Cruzada:** causa real = lista fixa de programas sem "IORM CULTURAL 2026". Fonte única `processamento/programas_iorm.py` (base + programas
  do Cérebro da OSC sem nomes genéricos + sigla/nome da OSC, palavra inteira). `relacionamento.reconciliar_relacionamentos()` roda após toda ingestão
  de incentivos e ao adicionar programa. Banco real: 9 → 11 em relacionamento (prospects 8.302 → 8.300).
- **Pipeline:** o Kanban é remontado quando o conteúdo muda (chave com assinatura) → remover/mover aparece na hora. Removidas = arquivadas (o dono removeu 3
  oportunidades reais em 23/09; continuam restauráveis; hoje 1 ativa).
- **Tema claro/escuro:** `TOKENS_TEMA` + `tema_atual()` em `_shared.py`; `.streamlit/config.toml` com `[theme.light]`/`[theme.dark]`; teste de contraste WCAG,
  de "sem cor fixa no CSS" e de renderização das 9 páginas nos dois temas. Visual mais sóbrio.
- **Testes:** 564 passando (`python -m pytest -q`). Novos: `test_busca_persistente.py`, `test_linha_cruzada_v8.py`, `test_tema.py` e acréscimos.
- **Estado do banco real:** 8.311 empresas, 8.300 prospects, 11 Linha Cruzada, 8.516 incentivos, editais 25 (abertos: Miguelópolis e Funarte;
  vários encerrados/não confirmados vindos da busca de 23/09), `fontes_dados` 6, cota SerpApi 15/100 no mês.
- Pendências: `git push` (v6, v7 e v8 ainda não foram enviados); confirmar elegibilidade do edital de Miguelópolis; `Atualizar busca` só foi testado com
  provedor simulado; documentos na nuvem continuam efêmeros.

---

## ATUALIZAÇÃO v9 (23/09/2026)

Detalhes completos em `docs/decisoes.md` seção 11. Resumo para outra IA:
- **Módulos novos:** `processamento/projetos_editais.py` (projetos × edital, determinístico), `processamento/descoberta_empresas.py` (provedores de
  descoberta, deduplicação, proveniência, cotas), `processamento/rotina_etapas.py` (Descoberta/Enriquecimento/Contatos/Editais com status).
- **Regras invioláveis mantidas:** nunca inventar dado/CNPJ; descoberta nunca marca relacionamento com o IORM; empresa sem CNPJ = `CANDIDATA`
  (fora dos prospects até validação humana); fuzzy só sinaliza duplicata; chaves só no `.env`.
- **Conector MCP ≠ recurso do app.** Apollo/Lusha/Snov.io do Claude Code não são acessíveis pelo Streamlit. Provedores do app só com chave própria
  e só SALIC e SerpApi Maps foram validados contra serviço real; os três pagos foram testados com respostas simuladas.
- **Dashboard:** a regra de alta aderência (ABERTO, nota ≥ 7,0, ≥ 3 critérios) não mudou; o "só 1" vinha de extração incompleta do edital Funarte.
- **Armadilha aprendida:** a URL de incentivo da SALIC muda a cada consulta; nunca deduplicar incentivo só por `url_fonte` ao reler páginas.
- Testes: 634+ (ver `python -m pytest testes`). Nada foi enviado ao GitHub (sem push).