# Decisões técnicas tomadas nesta etapa

Registro das escolhas que não estavam 100% definidas no pedido original,
para você conferir se concorda.

## 1. Tabela `fontes` = catálogo de fontes, não evidência por registro
A tabela `fontes` guarda **uma linha por fonte de dados integrada** ao
projeto (ex: "SALIC"), não uma linha por registro coletado. A evidência
de cada dado individual (de onde veio, quando, com que confiança) fica
direto nas colunas `url_fonte`, `coletado_em` e `nivel_confianca` da
tabela `incentivos` — que já são específicas por registro.

## 2. `projeto` e `ano` ficam NULL nesta etapa
O endpoint `/incentivadores` do SALIC só traz um valor **total agregado**
por incentivador (`total_doado`), sem quebrar por projeto ou por ano.
Para ter isso, existe outro endpoint (`/incentivadores/{id}/doacoes`)
que consultaremos numa próxima etapa. Preencher `projeto`/`ano` agora
seria inventar dado — por isso ficam `NULL` ("não disponível").

## 3. CNPJ só é aceito se passar na validação matemática
O campo `cgccpf` do SALIC às vezes traz números que não correspondem ao
CNPJ oficial mais conhecido de uma empresa (podem ser CNPJs de filiais
legítimas, ou dados incorretos). Por isso, todo CNPJ passa pela
validação do dígito verificador antes de entrar no banco como `cnpj`.
Se não passar, o campo fica `NULL` ("não confirmado") — nunca é
descartado o registro inteiro por causa disso, só o CNPJ daquele
registro específico.

## 4. Deduplicação
- **Empresas com CNPJ válido**: reaproveitadas (mesmo CNPJ = mesma
  linha).
- **Empresas sem CNPJ confirmado**: cada registro vira uma linha nova,
  mesmo que o nome pareça igual a outro já existente — conforme
  combinado, nenhum matching automático por nome nesta versão.
- **Incentivos**: deduplicados pela URL da fonte (cada registro do SALIC
  tem uma URL própria e única), então rodar a coleta de novo atualiza
  valores em vez de duplicar linhas.

## 6. Módulo de Inteligência de Contatos — decisões da v2

### 6.1 Sem API de busca ao vivo neste ambiente
Não existe (nem existirá dentro do Streamlit) uma API de busca paga
(Google/Bing/SerpAPI) configurada aqui. O botão "Pesquisar/Atualizar"
na ficha da empresa **não dispara uma busca em tempo real** — ele
registra a empresa em `dados/fila_pesquisa.json`. A pesquisa de verdade
é feita por um agente (humano ou IA) com ferramentas de busca, que gera
um JSON estruturado e roda `coleta/importar_enriquecimento.py`. Isso é
uma limitação técnica real, documentada também dentro da própria
dashboard (página Configurações), não uma simplificação escondida.

### 6.2 Contatos sem URL, mas com nome e cargo, ainda são gravados
A tabela `contatos` exige um valor não-nulo em `valor` (para poder
deduplicar). Quando um agente encontra um nome + cargo público mas sem
link específico (ex: citado só em texto corrido do site), usamos uma
chave sintética `referencia-publica:<nome normalizado>` em vez de
descartar o achado — isso preserva informação real (como a descoberta de
que a fundadora do IORM é Diretora de Responsabilidade Social de uma das
empresas pesquisadas) sem inventar uma URL que não existe.

### 6.3 Tipos/categorias fora do vocabulário fixo não derrubam a importação
Agentes de pesquisa às vezes usam palavras como "diretorio_empresarial"
em vez de um dos tipos fixos (`site`, `linkedin`, etc.). O importador
mapeia esses casos para o mais próximo (`outro`) em vez de descartar o
registro inteiro ou quebrar a importação — o nível de confiança já
registrado (geralmente BAIXO/MÉDIO nesses casos) comunica a incerteza.

### 6.4 Contactability Score e Prioridade de Prospecção são métricas novas, separadas do IORM Score
IORM Score mede afinidade histórica; Contactability Score mede
facilidade de abordagem; Prioridade de Prospecção combina os dois com
uma fórmula fixa e documentada (0,5×IORM + 0,5×Contactability + bônus de
10 se houver evidência de ESG/responsabilidade social/instituto). Nenhum
machine learning é usado — a fórmula está sempre visível para o usuário
na página Configurações.

### 6.5 Filtros da dashboard exigem clique em "Aplicar Filtros"
Para uma tabela de 8.211 linhas, recalcular a cada mudança de filtro
deixaria a navegação lenta e confusa. Os widgets de filtro ficam dentro
de um `st.form`, e só a tabela principal (página Empresas) respeita o
filtro aplicado — as demais páginas (Oportunidades, Contatos) usam seus
próprios filtros simples e imediatos, por trabalharem com tabelas bem
menores.

## 5. `razao_social` ainda não é 100% confirmada
O campo `nome` do SALIC é autodeclarado pela própria empresa no sistema
do Ministério da Cultura — pode ter variações de grafia em relação à
razão social oficial na Receita Federal. Por isso o README chama isso
de limitação conhecida: confirmar a razão social oficial é trabalho da
próxima etapa (BrasilAPI/Receita Federal).

## 7. Evolução v3 — plataforma de inteligência de captação

Decisões tomadas na virada de "dashboard de dados" para um produto tipo
CRM/SaaS de captação: Cérebro da OSC, Radar de Editais, Pipeline (CRM),
mecanismos de incentivo e o novo sistema visual.

### 7.1 Cérebro da OSC alimenta o resto do sistema, não é uma tela isolada
`metricas.estatisticas_gerais`, `metricas.carregar_empresas` e
`metricas.resumo_cidades_iorm` passaram a aceitar um parâmetro opcional
`cidades_estrategicas` (com um default hardcoded só como fallback de
compatibilidade). `paginas/_shared.carregar_dados_salic` lê o território
cadastrado no Cérebro da OSC (tabela `osc_territorios`) e injeta essas
cidades nas funções de métrica — então editar o território na tela
Cérebro da OSC muda de verdade quais empresas contam como
"cidade estratégica" no Radar de Empresas e no IORM Score, sem precisar
mexer em código. Escolhido em vez de duplicar a lista de cidades em cada
módulo, que inevitavelmente ficaria dessincronizada.

### 7.2 Seed idempotente da OSC, nunca sobrescreve edição manual
`processamento/osc.semear_organizacao_padrao()` só grava os dados
iniciais do IORM (missão, 4 territórios, programas, temas etc.) se a
tabela `osc` estiver vazia. Depois da primeira vez, edições feitas pela
equipe na tela Cérebro da OSC nunca são sobrescritas por uma nova
execução do app — critério igual ao já usado para não duplicar
incentivos na coleta SALIC.

### 7.3 Inteligência de Contatos: pesquisa de mercado de APIs de busca (2026)
Antes de escolher um provedor, pesquisei o estado real do mercado:
- **Google Custom Search JSON API**: fechada para novos cadastros,
  anunciado descontinuamento em 2027 — descartada.
- **Bing Web Search API**: aposentada pela Microsoft em agosto de 2025 —
  descartada.
- **Brave Search API**: perdeu o tier gratuito em fevereiro de 2026,
  agora exige cartão de crédito mesmo para o crédito inicial (~US$5/mês,
  ≈1000 buscas) — descartada para não depender de cartão cadastrado sem
  necessidade.
- **SerpApi**: mantém tier gratuito real (100–250 buscas/mês) sem exigir
  cartão para começar — **escolhida**.

Arquitetura: `processamento/busca_providers.py` define uma classe
abstrata `SearchProvider` (`disponivel()` + `buscar()`), implementada por
`SerpApiProvider` (lê `SERPAPI_API_KEY` do `.env`) e por
`FilaManualProvider` (fallback sempre disponível, que não busca nada —
só existe para que `obter_provider_ativo()` sempre retorne algo
utilizável). Isso significa trocar de provedor de busca no futuro é
implementar uma nova subclasse, não reescrever a orquestração. A chamada
HTTP real (`SerpApiProvider.buscar`) nunca foi testada contra a API de
verdade nesta sessão, por não haver uma chave configurada — o parsing da
resposta (`_parse_resposta`) foi testado separadamente contra um exemplo
fiel ao formato documentado da SerpApi.

### 7.4 Radar de Editais: nenhuma fonte automática real foi encontrada e integrada
Pesquisei fontes públicas brasileiras de editais antes de decidir o que
construir:
- **Mapa das OSC (IPEA) + parceria Prosas**: é um portal de indicação
  (referral), não expõe API — descartado para automação.
- **LPIE (Lei Paulista de Incentivo ao Esporte)**: o "Dados Abertos SP"
  só publica o conjunto de dados em **PDF**, sem REST/CSV — descartado
  para automação.

Nenhuma fonte automática foi conectada nesta etapa. Em vez de simular uma
integração ou inventar editais de exemplo, o módulo foi construído
completo (banco, motor de aderência 0–10 explicável, UI de cadastro e
busca manual) com um aviso permanente e visível na tela ("Busca
automática indisponível") — igual ao princípio já usado no módulo de
Contatos antes de existir busca automática nenhuma.

### 7.5 Registro formal de status de integração por mecanismo de incentivo
`processamento/mecanismos.py` cadastra cada mecanismo (Lei Rouanet, LPIE,
Lei de Incentivo ao Esporte federal, FIA municipal, editais agregadores,
doações diretas) com um status de uma taxonomia fixa: 🟢 Integrada e
funcionando / 🟡 Fonte encontrada, integração parcial / 🔵
Cadastro/consulta manual / 🔴 Ainda não disponível. Existe para que a
equipe nunca confunda "o menu existe" com "o dado é coletado de verdade"
— mesma taxonomia reaproveitada na aba "Mecanismos de Incentivo" de
Configurações.

### 7.6 Banco de dados (`dados/iorm_radar.db`) versionado no Git, não ignorado
Decisão deliberada: `dados/backups/` e `dados/fila_pesquisa.json` estão
no `.gitignore`, mas o banco principal **não está** — para que um deploy
futuro (Streamlit Community Cloud) suba já com os dados reais coletados,
sem precisar rodar a coleta inteira de novo no ambiente de produção.
Reavaliar essa decisão se o projeto migrar para múltiplas OSCs ou para
Postgres (ver 7.8).

### 7.7 Identidade visual extraída da logo real do IORM
Os tokens de cor (`--iorm-azul`, `--iorm-laranja`, `--iorm-verde` etc. em
`paginas/_shared.py`) foram extraídos da logo real
(`assets/logo-iorm.png.jpeg`), não inventados. A logo é embutida em
base64 tanto no bloco de marca da barra lateral quanto no banner de
cabeçalho de cada página — decisão para evitar depender de um caminho de
arquivo estático servido separadamente pelo Streamlit.

### 7.9 Priorização geográfica em camadas (Região IORM)
O critério geográfico binário ("cidade estratégica sim/não") virou uma
classificação em 4 camadas (`processamento/regiao.py`): Cidade de atuação
(25 pts, igual ao peso binário anterior) → Região próxima (15) →
Interesse estratégico (8) → Fora da região (0). Reaproveita a tabela
`osc_territorios` já existente (coluna `tipo`), sem migração de schema —
só passou a aceitar `tipo='regiao_proxima'` e `tipo='interesse_estrategico'`
além de `'cidade'`/`'estado'`. Nenhuma cidade de "região próxima" foi
inventada: a lista nasce vazia e só cresce quando a equipe do IORM cadastra
em Cérebro da OSC → Território — por isso, com o cadastro atual (só as 4
cidades originais), o comportamento observável do score é idêntico ao de
antes até alguém popular as novas camadas.

### 7.10 Busca automática de editais — fontes e por que nunca afirma "aberto" sem prova
`processamento/busca_editais.py` reaproveita o `SearchProvider` já
validado para contatos, restringindo cada consulta com `site:` a três
fontes específicas: `gov.br` (federal/estadual/municipal), `mapaosc.ipea.gov.br`
e `prosas.com.br` — as duas últimas já eram conhecidas deste projeto como
fontes reais de editais para OSCs (ver item 7.4), mesmo sem API própria;
usar `site:` como proxy de busca dentro delas via um provedor de busca
genérico é uma forma honesta de aproveitá-las sem depender de um scraper
dedicado a cada uma. Testado ao vivo: uma busca real trouxe 15 candidatos,
incluindo um edital real e vigente da Secretaria Municipal de Cultura de
São Paulo (Fomento à Dança), com aderência 8.9/10 calculada corretamente.
Todo candidato nasce com `situacao_inscricao='NAO_CONFIRMADO'` — só vira
`ABERTO`/`ENCERRADO`/`PROXIMO` quando uma data real aparece literalmente
no snippet da busca (regex para dd/mm/aaaa e aaaa-mm-dd, nunca inferência).
Nenhum candidato é salvo sozinho: aparece como preview com aderência já
calculada, e só vira registro em `editais` quando alguém clica "Importar"
— evita poluir a base com resultados de busca de baixa relevância (a
própria busca de teste trouxe candidatos claramente não relacionados,
como "Edital ENADE 2026", corretamente pontuados com aderência baixa
pelo motor já existente, não por um filtro novo).

### 7.11 Drag-and-drop real no Pipeline via componente de terceiros
Avaliado e adotado `streamlit-sortables` (componente Streamlit de
terceiros, bidirecional de verdade — não um efeito visual) para o
Kanban do Pipeline. Achado durante a implementação: o componente herda
um `color: white` de estilo padrão (Bootstrap) nos itens, deixando o
texto do card invisível sobre fundo branco — corrigido fixando `color`
explicitamente no `custom_style`. Testado ao vivo arrastando um card
entre colunas nos dois sentidos e confirmando a persistência direto no
SQLite (não só na tela) antes de considerar a funcionalidade pronta.

### 7.12 Descoberta diária de novas empresas — por que Minas Gerais e não mais São Paulo
`coleta/coleta_diaria.py` usa a mesma API do SALIC já integrada, mas
percorre estado por estado (`SP, MG, PR, RJ, MT, GO` por padrão) com
memória de progresso em `dados/estado_coleta_diaria.json` — nunca refaz
uma página já lida. Decisão importante: SP já foi coletado por completo
nesta base (8.211 empresas), então rodar a rotina de novo nele traria
quase só empresas "já existentes" e, pior, criaria linhas duplicadas
para os poucos registros sem CNPJ confirmado (a regra antiga de "sem
CNPJ, sempre cria linha nova" se aplicaria de novo). Por isso o estado
inicial já marca SP como concluído, e a rotina avança naturalmente para
o próximo estado da lista. Testado ao vivo com uma execução real
(`--meta 5 --max-paginas-por-uf 1`): trouxe 100 empresas novas e reais de
Minas Gerais (CNPJs validados, cidades reais) — a única razão de terem
sido 100 em vez de ~5 é que a API devolve 100 registros por página e a
rotina não descarta o restante de uma página só pra bater uma meta exata
(isso gastaria a mesma chamada de API sem ganhar nada). Sem execução
automática 24/7 neste ambiente — precisa ser agendada (Windows Task
Scheduler; passo a passo no fim do próprio arquivo do script).

### 7.8 Arquitetura pronta para múltiplas OSCs, mas sem multi-tenant implementado agora
A tabela `osc` já é desenhada para múltiplas linhas (não existe premissa
de "OSC única" no schema), e `osc.obter_osc_principal()` é a única função
que hoje assume "a primeira/única OSC cadastrada". Login, isolamento de
dados por organização e seleção de OSC ativa **não foram implementados**
nesta etapa — ficaria sobre-engenharia para um produto com um único
cliente piloto (IORM) agora. Quando houver uma segunda OSC real, o
próximo passo é trocar `obter_osc_principal()` por uma OSC vinculada à
sessão do usuário logado.
