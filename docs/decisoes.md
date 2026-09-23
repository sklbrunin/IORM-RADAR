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

## 8. Rodada v6 — Linha Cruzada, região por polo, links de editais, documentos, contatos e rotina diária

### 8.1 Empresa com relacionamento não é prospect (Linha Cruzada persistida)
`empresas` ganhou `relacionamento_iorm`, `relacionamento_tipo`, `relacionamento_fonte`, `relacionamento_em`,
`reabrir_prospeccao` e `reabrir_justificativa` (migração idempotente em `banco.migrar_empresas`).
`processamento/relacionamento.sincronizar` marca automaticamente: (a) a própria OSC (pelo CNPJ da tabela `osc`);
(b) doadoras com projeto de programa do IORM (`metricas.PROGRAMAS_IORM`); (c) empresas com oportunidade
"Fechado — ganho" no CRM. Marcação manual exige justificativa. Regra de negócio: **prospect e relacionamento são
mutuamente exclusivos**, exceto quando alguém reabre a prospecção com justificativa escrita
(`relacionamento.eh_prospect`). Nada é apagado: a empresa só troca de aba (Radar → Linha Cruzada).

### 8.2 "Região" de um polo vem do IBGE, não de escolha nossa
Fonte: API de Localidades do IBGE, Região Geográfica Imediata (divisão 2017). Região do polo = municípios da mesma
Região Imediata. Ipuã e Orlândia caem na mesma região ("São Joaquim da Barra – Orlândia"), Guaíra em Barretos,
Miguelópolis em Ituverava. Guardado em `regiao_municipios` (UNIQUE polo+município+UF; origem IBGE ou MANUAL;
flag `ativo`). A sincronização usa INSERT OR IGNORE e **nunca reativa** o que o usuário desativou. Ajustes manuais
exigem motivo. Esses municípios entram como `regiao_proxima` no score e nos filtros.

### 8.3 Links de editais: página do edital ≠ link de inscrição
`processamento/links_editais.py` classifica cada URL como PAGINA_ESPECIFICA_CONFIRMADA, RESPONDE_SEM_CORRESPONDENCIA,
PORTAL_GENERICO, NAO_RESPONDE ou NAO_VERIFICADO (resposta HTTP + correspondência de palavras do título na página +
heurística de portal genérico). O link de inscrição só é exibido como tal se a própria URL indicar inscrição ou se
foi extraído da página verificada; caso contrário a tela diz "Link direto de inscrição não localizado". Portal
genérico aparece como "Abrir portal (página genérica)", nunca como INSCREVER-SE. Limite conhecido: a heurística não
lê PDFs nem páginas que exigem JavaScript.
O edital #1 ("Edital Municipal de Cultura e Dança 2026") foi um registro de TESTE que criei durante o desenvolvimento;
não é um edital real. Está marcado `origem_descoberta='TESTE_NAO_REAL'`, aparece com aviso e fica fora do Dashboard.
Não foi apagado (regra: não apagar histórico) — o usuário pode excluí-lo se quiser.

### 8.4 Documentos da OSC (repositório real)
`processamento/documentos.py`: upload PDF/DOCX/TXT/XLSX/XLS (25 MB), original preservado em `dados/documentos_osc/`
(fora do Git), texto extraído (pypdf, python-docx, openpyxl, xlrd) e guardado em `osc_documentos.texto_extraido`,
deduplicação por SHA-256, status de processamento explícito (inclusive "sem texto extraído", ex.: PDF escaneado —
não há OCR). A busca devolve trechos literais com "Fonte: documento X"; nenhuma IA interpreta o conteúdo.
Atenção de privacidade: o texto extraído fica no banco `dados/iorm_radar.db`, que é versionado no Git (ver 7.6).
Antes de publicar o repositório, considere isso.

### 8.5 Contatos: empresa ≠ pessoa
E-mail genérico (financeiro@, contato@) é sempre canal **institucional** com "área do e-mail"; nunca vira pessoa.
Pessoa exige nome + cargo/área + fonte + data. Sócios/administradores do quadro societário da Receita
(BrasilAPI) entram como pessoa com origem "quadro societário — Receita Federal" e confiança ALTA quanto ao vínculo
societário — mas **não são necessariamente responsáveis por ESG/marketing**; a tela avisa isso. De cada sócio só
guardamos nome e qualificação (CPF mascarado e faixa etária da API são descartados — LGPD). O Contactability Score
só conta contato profissional que tenha `prioridade` (áreas-alvo), para que sócio genérico não infle a nota.
Não há scraping de LinkedIn: só perfis que apareçam em resultados de busca oficiais/legais.

### 8.6 Provedores de enriquecimento de contatos (avaliação)
Arquitetura em `processamento/contact_providers.py`: provider → enriquecer → normalizar/validar → `persistir()`
(único ponto de escrita) → evidência. Avaliados:
- **BrasilAPI / Receita Federal** — gratuito, sem chave, testado ao vivo (30 empresas reais). Cobre situação cadastral,
  nome fantasia, CNAE, telefone e QSA. Não traz e-mail de pessoa.
- **Busca web via SerpApi** — já integrada; plano gratuito pequeno (fontes divergem entre ~100 e ~250 buscas/mês).
  Não sustenta 30 empresas/dia com busca web (ver 8.7).
- **Hunter.io** — e-mail profissional por domínio, com cargo/departamento. O plano gratuito (≈50 créditos/mês) não
  dá acesso à API; API exige plano pago. Implementado e testado só com resposta simulada — **nunca contra a API real**.
- **Apollo** — plano gratuito sem API; cobertura de PMEs brasileiras incerta. Não implementado.
Nenhum dado de terceiros é raspado; credenciais só por variável de ambiente (`.env.example`).

### 8.7 Rotina diária de 30 empresas — o que ela realmente garante
`coleta/enriquecimento_diario.py` (fila em `processamento/fila_enriquecimento.py`): seleciona até 30 prospects
elegíveis com CNPJ (exclui Linha Cruzada), prioriza os nunca pesquisados e a Região IORM, consulta a Receita Federal
para as 30 e usa busca web só dentro do orçamento mensal da SerpApi (`SERPAPI_LIMITE_MENSAL`, `SERPAPI_RESERVA_MANUAL`).
Resultado por empresa: SUCESSO / PARCIAL / FALHA, com tentativa e evidência. Falha volta à fila em 1 dia, parcial em
3 dias, máximo 3 tentativas. É idempotente por dia (rodar duas vezes no mesmo dia não reprocessa) e faz backup do
banco antes de cada execução. Se houver menos de 30 elegíveis, registra isso no log. **Realidade da cota:** com o
plano gratuito, ~80 buscas/mês para a rotina ≈ 26 empresas/mês com busca web; as 30/dia são enriquecidas via
Receita Federal (QSA, situação, telefone) e a camada web fica em "PARCIAL" quando a cota acaba. Para 30/dia com busca
web completa é preciso plano pago da SerpApi (ou de outro provedor).
Agendamento: `coleta\agendar_enriquecimento_windows.ps1` (Agendador de Tarefas do Windows, usuário atual, sem
administrador, `StartWhenAvailable`). Testado: instalar → Start-ScheduledTask → resultado 0 → remover. A tarefa NÃO
fica instalada por padrão porque é uma configuração persistente na máquina e consome cota de API.
Para nuvem: o mesmo comando (`python coleta/enriquecimento_diario.py --agendada`) roda em cron/GitHub Actions/
Streamlit Cloud + agendador externo; o SQLite local precisaria ser trocado por banco compartilhado.

## 9. Rodada v7 — números separados, editais abertos, fontes configuráveis, documentos, Pipeline e mecanismos

### 9.1 Cinco números, cada um com um significado (`metricas.contadores_empresas`)
Empresas na base (todas; nada é apagado) · Prospects (`eh_prospect`) · Linha Cruzada (`linha_cruzada`) ·
Prospects pesquisados · Prospects não pesquisados. Mostrados no Dashboard e no topo do Radar de Empresas, calculados
na hora (hoje: 8.311 / 8.302 / 9). Só há sobreposição quando a equipe reabre a prospecção de uma empresa da Linha
Cruzada com justificativa — o Dashboard avisa quando isso acontece. Listas de prioridade e "melhores prospects" do
Dashboard usam só prospects.

### 9.2 Editais: só é "aberto" o que dá para provar
`editais.situacao_efetiva` (calculada na leitura, não gravada — uma data que passa depois não fica "aberta" para sempre)
devolve ABERTO / ENCERRADO / NÃO CONFIRMADO. ABERTO exige, ao mesmo tempo: data de encerramento real e futura + link da
fonte + nenhum sinal contrário (página que diz "encerradas", status interno "Encerrado", abertura em data futura,
registro de teste). Sem data ou sem link → NÃO CONFIRMADO, nunca "aberto". Encerrados e registros de teste ficam numa
aba de histórico (guardados). A página de Editais tem abas Abertos / Não confirmados / Encerrados e histórico / Buscar
e cadastrar; o Dashboard só mostra cartões de editais ABERTOS com aderência ≥ 7,0 calculada com ≥ 3 dos 6 critérios,
e o clique abre a ficha (`st.session_state["edital_em_foco"]` + `st.switch_page`).
**Prazo sugerido × confirmado:** a página verificada (ou o trecho da busca) pode mencionar "inscrições até dd/mm/aaaa"
(`links_editais.extrair_prazo`). Isso vira apenas uma SUGESTÃO com o trecho literal; a equipe confirma com um clique
(`editais.confirmar_prazo`, origem gravada como CONFIRMADO_PELA_EQUIPE) — só então o edital passa a "Aberto". Motivo:
(CORRIGIDO na v8: a conclusão original de que o Prosas seria "uma página montada por JavaScript, sem prazo legível" estava errada — era um bug de leitura que analisava só o primeiro pedaço da página. Ver item 10.2.)
**Erro corrigido:** a busca automática preenchia o território de cada edital com as cidades da própria OSC, o que
fabricava 10/10 em aderência territorial. Agora fica vazio ("Não identificado na fonte"). O edital #2 do banco real
teve esse campo limpo (backup `iorm_radar_20260918_*_pre_v7.db` guarda o valor anterior). Também: uma data solta no
trecho da busca deixou de ser tratada como "encerramento" (podia ser data de publicação).
**Aderência:** cada critério mostra nota + explicação exata; sem dado → "Não identificado na fonte"; a ficha diz com
quantos dos 6 critérios a nota foi calculada (uma nota 10 baseada em 1 critério não é "alta aderência").

### 9.3 Central de Fontes de Dados (`processamento/fontes_dados.py`)
Tabela `fontes_dados` (nome, tipo, URL, categoria, descrição, ativo, frequência, método de acesso detectado, última/
próxima consulta, último resultado, observações, datas). Fluxo: FONTE → `avaliar_acesso` (olha a resposta real: FEED,
API_JSON, PÁGINA_PÚBLICA ou INACESSÍVEL) → só FEED (RSS/Atom) de tipo Editais é coletado automaticamente → filtro de
relevância por palavras inteiras (edital, chamamento, fomento…) → `editais` como NÃO CONFIRMADO, com fonte e data.
API/HTML ficam apenas registradas (consulta manual ou integração dedicada futura): não há raspagem frágil. Parser de
feed recusa XML com entidades. Linha de comando: `python coleta/consultar_fontes.py [--todas]`. Seis fontes reais já
usadas pelo sistema foram cadastradas (SALIC, IBGE, Mapa das OSC, Prosas, Dados Abertos SP, BrasilAPI), cada uma com
o método de acesso medido em 21/09/2026.

### 9.4 Documentos
Exclusão só depois de confirmação (janela "Excluir documento?"); remove registro, texto e arquivo. Botão para baixar
o original. O caminho é guardado RELATIVO à pasta do projeto (`dados/documentos_osc/...`), então funciona igual local
e na nuvem. **Streamlit Cloud:** o disco é temporário — arquivos enviados pela tela se perdem quando o app reinicia/
faz novo deploy (o texto extraído, que está no banco, também segue o banco). Para persistência real na nuvem seria
preciso um armazenamento externo (bucket) — não implementado; documentado como limitação.

### 9.5 Pipeline: remover = arquivar
`crm.remover_oportunidade` marca `removida_em`/`motivo_remocao` (a oportunidade e as interações continuam no banco; a
empresa nunca é tocada) e há "Restaurar". A remoção passa por janela de confirmação; oportunidade removida não conta em
valor potencial, follow-ups, atividade recente nem em "relacionamento" (Fechado — ganho removido não marca a empresa).

### 9.6 Mecanismos de incentivo: provedores (`processamento/incentivos_providers.py`)
`IncentivoProvider → RegistroIncentivo (normalizado) → ingerir() → empresas + incentivos`, com coluna nova
`incentivos.mecanismo` (backfill idempotente: 8.516 linhas = LEI_ROUANET). Investigação de fontes em 18/09/2026:
- **Lei Rouanet (SALIC)** — integrada e testada ao vivo (empresa, CNPJ, UF, município, valor, projeto, data).
- **LPIE-SP** — dataset com 1 PDF de PROJETOS em execução; não lista incentivadores.
- **Lei de Incentivo ao Esporte (federal)** — dados.gov.br responde 401 (exige token); painel oficial é interativo.
  Se a equipe obtiver um token, dá para reavaliar.
- **ProAC ICMS (SP)** — portais de consulta, sem arquivo/API de empresas localizado; dataset FOMENTOS sem URL de arquivo.
- **PRONON/PRONAS-PCD** — lista projetos aprovados (DOU/Transferegov), não doadores.
- **FIA / Fundo do Idoso** — doações declaradas à Receita por cada fundo; sem base pública por empresa.
Onde não há fonte confiável, o provedor existe só para registrar o motivo e levanta `IntegracaoIndisponivel`
("Integração ainda não disponível"). CLI: `python coleta/coleta_incentivos.py --listar | --mecanismo LEI_ROUANET --uf MG`.

### 9.7 Streamlit Cloud e ambiente
Sem caminhos absolutos nem chaves no código; `SERPAPI_API_KEY` vem de variável de ambiente (Secrets do Streamlit Cloud
viram variáveis de ambiente). `.streamlit/config.toml` limita o upload a 25 MB. `IORM_RADAR_DB` (opcional) aponta o app
para outro arquivo de banco — usado só para validar a interface numa cópia. As abas das páginas usam `key` para não
voltar à primeira aba a cada ação. Só rodam localmente: o agendador do Windows e o `.env`.

## 10. Rodada v8 — busca de editais persistente, Linha Cruzada reconciliada, Pipeline, tema claro/escuro

### 10.1 Busca de editais: o que estava errado e como funciona agora
Auditoria do fluxo antigo (`busca_editais.buscar_editais` + `radar_editais`): 3 consultas × 5 resultados = **no máximo 15
resultados**, sem paginação; o resultado ficava só em `st.session_state` (trocar de aba perdia a lista) e cada clique refazia
as 3 chamadas à SerpApi; importar era manual, um a um. Agora (`busca_editais.executar_busca`):
`plano de consultas → cache persistente → normalização → filtros → deduplicação por URL canônica → persistência em editais
→ verificação da página → situação efetiva`.
- **Plano** (`montar_plano_de_busca`): por município do Cérebro da OSC × Prosas (`site:prosas.com.br/editais <município> <ano>`) e ×
  gov.br; uma consulta geral por fonte (Prosas, gov.br, Mapa das OSC) com temas + estado; e as fontes cadastradas em
  Configurações. Teto `BUSCA_EDITAIS_MAX_CONSULTAS` (12). Sem nenhum município fixo no código.
- **Cache** (`busca_editais_cache`): cada (consulta, página, parâmetros) guarda resultados por `BUSCA_EDITAIS_CACHE_DIAS` (7) dias. "Buscar
  editais" só chama a API para consultas SEM resultado válido salvo; **só "Atualizar busca" força novas chamadas**. Cada chamada real
  é registrada em `uso_api` (limite `SERPAPI_LIMITE_MENSAL`; a reserva manual não é descontada porque a ação é manual) e cada execução
  em `busca_editais_execucoes` (relatório mostrado na tela: consultas, chamadas, cache, brutos, únicos, novos, descartados por motivo,
  por município/fonte/situação).
- **Paginação/recência:** `SerpApiProvider.buscar(inicio=, recencia=)` → `start` e `tbs=qdr:y` (só resultados do último ano).
- **Filtros de qualidade:** portal/lista genérica, perfil de outra OSC (Mapa das OSC), domínio de outro estado (`guaira.pr.gov.br`),
  concurso/licitação/seleção de alunos, universidades. O que passa é salvo; **encerrados são salvos** (histórico), não descartados.
- **Consulta sem resultado não é erro:** a SerpApi responde `error: "Google hasn't returned any results…"`; isso derrubava a busca inteira.
- **Cadastro pelo link** (`cadastrar_por_url`): a equipe cola o endereço; o sistema abre a página, lê título/prazo/valor e salva. É o caminho
  para editais recebidos por e-mail/WhatsApp ou muito recentes.

### 10.2 Caso Miguelópolis (Prosas 19173): o que a busca NÃO acha e por quê
A consulta `site:prosas.com.br/editais Miguelópolis 2026` devolveu **0 resultados** na SerpApi em 23/09/2026 (a página é do dia; o Google
ainda não a indexara). Nenhum ajuste de consulta resolve isso — por isso existe o cadastro pelo link, que abre a página diretamente.
**Bug de leitura corrigido:** `links_editais._buscar_pagina` (e `fontes_dados.buscar_http`) liam só o PRIMEIRO bloco recebido da rede
(`next(iter_content(N))`), ~2 KB de uma página de ~160 KB. Daí a conclusão errada, nas rodadas v6/v7, de que o Prosas "é montado por
JavaScript". Na verdade a página traz o objeto JSON da oportunidade dentro do HTML (`&quot;encerramento_das_inscricoes&quot;…`):
`links_editais.extrair_dados_estruturados` lê nome, início/fim das inscrições (23/09 e 09/10/2026), indicadores de situação,
áreas, público-alvo, "valor total do edital" (R$ 90.000,00) e a frase de elegibilidade ("Pessoas Físicas… residentes no município…").
Esses dados entram como `prazo_origem = FONTE_ESTRUTURADA` (prazo prorrogado vira só sugestão). Observação: a página informa início em
23/09, não 21/09 como no aviso recebido; vale a página.
Elegibilidade a conferir pela equipe: o edital pede **Pessoas Físicas** residentes; o IORM é pessoa jurídica.

### 10.3 Situação dos editais (`editais.situacao_efetiva`) — mudanças
Data de hoje vem de `editais.hoje_brasil()` (São Paulo; sem valor fixo). Edital **sem prazo mas com ano anterior no título/URL**
(ex.: "Edital 001/2025") → ENCERRADO com o motivo explícito (inferência declarada; a equipe pode confirmar um prazo e reverter).
Prazo confirmado pela equipe prevalece sobre a marca "encerrado" da página. Lista de abertos ordena primeiro os avaliados com ≥ 3 critérios.

### 10.4 Linha Cruzada: a causa real do doador que continuava prospect
`metricas.PROGRAMAS_IORM` era uma constante fixa e **não continha o projeto "IORM CULTURAL 2026"** (apoiado em 2025 e 2026). Empresas
como "Produtos Alimentícios Orlândia S/A" (doação em 2026) e "ORLASOLDA…" (2025) apareciam como prospects (a primeira, inclusive, entre
os "prospects prioritários" do Dashboard). Agora a fonte única é `processamento/programas_iorm.py`: lista-base + programas do Cérebro da OSC
(exceto nomes genéricos como "Artes e Cultura") + sigla/nome da OSC, com comparação por palavra inteira. `reconciliar_relacionamentos()` é
chamada após cada ingestão de incentivos (provedores e scripts de coleta) e ao adicionar programa no Cérebro; além disso `carregar_empresas`
usa os termos atuais, então a tela não depende de marca antiga. Reconciliação no banco real: 9 → 11 empresas em relacionamento (prospects
8.302 → 8.300); nenhum registro apagado. Classificação manual e reabertura explícita sobrevivem.

### 10.5 Pipeline: remover atualiza o quadro na hora
O Kanban (`streamlit-sortables`) guarda estado no navegador; com chave fixa, o cartão removido só sumia após F5. A chave agora inclui uma
assinatura do conteúdo (`assinatura_do_quadro`): mudou o conteúdo → o componente é remontado (≈ 3 s). Validado no navegador. A remoção
continua sendo arquivamento com restauração.

### 10.6 Tema claro/escuro e visual
`paginas/_shared.py`: `TOKENS_TEMA` (mesmo conjunto de tokens semânticos nos dois temas), `tema_atual()` (`st.context.theme.type`),
`tokens_do_tema()`; o CSS só usa `var(--iorm-*)` (teste garante que não há cor fixa fora do bloco de tokens, exceto a faixa do cabeçalho).
`.streamlit/config.toml` define `[theme.light]` e `[theme.dark]` alinhados aos tokens para os componentes nativos. O Kanban (iframe) recebe as
cores do tema como valores. Contraste WCAG dos pares texto/fundo testado nos dois temas. Visual: cabeçalho mais sóbrio, ícones de seção em
"chip", métricas planas, sem hover animado, botões com texto legível.

### 10.7 Limites reais desta rodada
- A busca por API depende do índice do buscador (página nova pode não aparecer) e da cota gratuita; cobertura efetiva medida = 11 consultas /
  70 resultados brutos / 66 únicos / 22 editais novos salvos (execução real de 23/09/2026); não se afirma cobertura total.
- "Atualizar busca" só foi testado com provedor simulado (contagem de chamadas), para não gastar cota real.
- Teste de contraste no navegador usa análise do DOM (fundo por elementos ancestrais); a faixa do cabeçalho (gradiente) e o rótulo do controle
  deslizante são falsos positivos conhecidos. Tabelas (canvas do Streamlit) seguem o tema nativo e não foram medidas.
