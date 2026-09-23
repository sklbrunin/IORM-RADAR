# IORM Radar — Inteligência para Captação de Recursos

Plataforma para ajudar a equipe de captação de recursos do **Instituto
Oswaldo Ribeiro de Mendonça (IORM)** a encontrar, priorizar, contatar e
acompanhar empresas, editais e outras oportunidades de financiamento —
com histórico comprovado de investimento via leis de incentivo fiscal e
afinidade real com a atuação do IORM (educação através da arte, cultura,
esporte, qualificação profissional, nas cidades de Ipuã, Guaíra,
Miguelópolis e Orlândia/SP).

Regra de ouro do projeto: **nenhum dado é inventado**. Toda informação
guardada no banco vem com fonte, data da coleta e nível de confiança.
Quando uma informação não está disponível, o sistema grava isso
explicitamente ("Não disponível") — nunca um valor chutado, nunca uma
pontuação fabricada, nunca um edital ou contato fictício.

## Status atual (v3 — plataforma de captação)

O sistema tem hoje quatro áreas de navegação:

- **Visão Geral** — Dashboard consolidado: números do radar, prioridades
  de hoje, funil de captação, top oportunidades e atividade recente.
- **Inteligência** — Cérebro da OSC (perfil institucional do IORM, que
  alimenta o resto do sistema), Radar de Empresas, Radar de Editais e
  Contatos.
- **Captação** — Pipeline (CRM em formato Kanban) e Oportunidades
  (ranking gerado pelo radar).
- **Sistema** — Configurações (fórmulas dos scores, status de cada
  mecanismo de incentivo, status da busca automática, fila de pesquisa).

Fontes de dados integradas hoje:

1. **SALIC** (Sistema de Apoio às Leis de Incentivo à Cultura, Ministério
   da Cultura) — API pública oficial, sem chave de acesso:
   https://api.salic.cultura.gov.br/docs. Traz empresas que já doaram via
   **Lei Rouanet**, com detalhamento por projeto/ano para as empresas das
   4 cidades do IORM.
2. **Módulo de Inteligência de Contatos** — presença digital, contatos
   institucionais e evidências de ESG, via um provedor de busca plugável
   (`processamento/busca_providers.py`). Sem uma chave SerpApi
   configurada em `.env`, o sistema usa fila manual (mesmo fluxo da v2);
   com a chave configurada, a busca roda de verdade a partir da ficha da
   empresa. Ver `.env.example`.
3. **Radar de Editais** — cadastro estruturado de editais/chamadas/
   prêmios/patrocínios com um motor de aderência (0–10) explicável
   contra o perfil do IORM. A busca automática usa a SerpApi (com chave) e as
   fontes cadastradas em Configurações → Fontes de Dados; só editais com prazo
   confirmado aparecem como "abertos" — ver `docs/decisoes.md`, item 9.2.

Outras fontes (Lei de Incentivo ao Esporte, FIA municipal, Receita
Federal/BrasilAPI para CNAE/situação cadastral) estão cadastradas como
mecanismos "ainda não disponíveis" na aba Mecanismos de Incentivo de
Configurações — ver `processamento/mecanismos.py`.

## Novidades da v9

- **Projetos do IORM relacionados** (ficha do edital): quais projetos do Cérebro da OSC combinam com o edital, com nível, motivo e "Ver como foi
  calculado". A **elegibilidade** aparece separada e sempre diz que precisa ser conferida no edital.
- **Dashboard:** "Editais com alta aderência" mostra TODOS os que cumprem a regra (aberto + nota ≥ 7,0 + ≥ 3 critérios) e pagina com aviso claro.
  A causa do "só 1" era um edital cujos dados (território/quem pode se inscrever) estavam no texto da página e não eram lidos.
- **Descoberta nacional de empresas:** Configurações → *Descoberta de Empresas* lista os provedores (SALIC, SerpApi Maps, Apollo, Lusha, Snov.io)
  e sua situação real. A **Rotina diária** tem 4 etapas (Descoberta, Enriquecimento, Contatos, Editais) com status. Meta: `EMPRESAS_NOVAS_POR_DIA`
  (50). Empresa achada sem CNPJ vira *candidata* e só entra nos prospects depois de validada pela equipe. Apollo, Lusha e Snov.io só funcionam
  com chave própria no `.env` (os conectores do Claude não são acessíveis pelo aplicativo).
- Rotina pela linha de comando: `python coleta/enriquecimento_diario.py --novas 50` (`--sem-descoberta`, `--com-editais`).
## Novidades da v8

- **Busca de editais persistente:** o que a busca acha é SALVO e aparece em Abertos / Não confirmados / Encerrados e histórico. Resultados
  ficam em cache (7 dias): "Buscar editais" não gasta a API para reexibir; só "Atualizar busca" refaz as chamadas. Consultas por município
  e por fonte, com paginação e teto configurável (`.env.example`).
- **Cadastrar edital pelo link** (aba Buscar e cadastrar): cole o endereço (ex.: Prosas) e o sistema lê título, prazo e valor da página.
- **Linha Cruzada corrigida:** projetos do IORM (ex.: "IORM CULTURAL 2026") agora vêm do Cérebro da OSC e da sigla da OSC; quem apoiou sai dos prospects.
- **Pipeline:** remover atualiza o quadro na hora. **Tema claro/escuro** legível em todas as páginas; visual mais sóbrio.

## Novidades da v7

- **Dashboard** separa cinco números (empresas na base, prospects, Linha Cruzada, pesquisados, não pesquisados) e traz
  cartões clicáveis de **editais abertos com alta aderência** que abrem a ficha completa.
- **Radar de Editais** mostra por padrão só os editais **abertos**; "Não confirmados" e "Encerrados e histórico" ficam em
  abas próprias. Prazo sugerido pela página é confirmado pela equipe com um clique.
- **Configurações → Fontes de Dados:** cadastre portais/feeds/bases; o sistema avalia como cada um pode ser consultado.
  `python coleta/consultar_fontes.py` consulta as fontes vencidas.
- **Documentos:** excluir com confirmação e baixar o arquivo original. **Pipeline:** remover (arquivar) com confirmação e restaurar.
- **Incentivos por mecanismo:** `python coleta/coleta_incentivos.py --listar`. Só a Lei Rouanet tem fonte pública
  estruturada; os demais estão documentados como "integração ainda não disponível" (ver `docs/decisoes.md`, item 9.6).

## Novidades da v6

- **Radar de Empresas** tem quatro abas: Radar de Prospecção, **Linha Cruzada** (empresas que já têm relacionamento
  com o IORM — não aparecem como prospect), Buscar qualquer empresa e Histórico.
- **Oportunidades → Radar por Região**: polo → cidades da região → empresas → ficha completa. A região de cada polo
  vem do IBGE e é editável em Cérebro da OSC → Território.
- **Radar de Editais**: botões VER EDITAL / INSCREVER-SE só com link verificado; senão "Link direto de inscrição não
  localizado".
- **Cérebro da OSC → Documentos**: upload (PDF, DOCX, TXT, XLSX, XLS), texto extraído, busca por conteúdo.
- **Contatos**: abas "Canais da empresa" e "Pessoas identificadas", com área e prioridade.
- **Sistema → Rotina diária**: enriquecimento de até 30 empresas por dia, com log e fila.

### Rotina diária de enriquecimento (30 empresas/dia)

Rodar agora, uma vez (não gasta a cota da SerpApi com `--sem-web`):

```bash
python coleta/enriquecimento_diario.py --meta 30 --sem-web
```

Agendar no Windows (uma vez; roda todo dia às 07:30 com o seu usuário, sem administrador):

```bash
powershell -ExecutionPolicy Bypass -File coleta\agendar_enriquecimento_windows.ps1
```

Conferir se está agendada e quando foi a última execução:

```bash
powershell -ExecutionPolicy Bypass -File coleta\agendar_enriquecimento_windows.ps1 -Status
```

Remover o agendamento:

```bash
powershell -ExecutionPolicy Bypass -File coleta\agendar_enriquecimento_windows.ps1 -Remover
```

Logs: `dados/logs/enriquecimento_diario.log` e `dados/logs/agendado.out.log`. A página **Rotina diária** mostra última
execução, próxima, processadas hoje, sucesso/parcial/falha e a fila. Limite real da busca web: ver
`docs/decisoes.md`, item 8.7.

## Como instalar

Pré-requisito: Python 3.10 ou mais recente instalado.

```bash
pip install -r requirements.txt
```

Copie `.env.example` para `.env` se quiser ativar a busca automática de
contatos (opcional — o sistema funciona sem isso, só com a fila manual):

```bash
copy .env.example .env
```

## Como executar a coleta

```bash
python coleta/coleta_salic.py --uf SP
```

Para um teste rápido (só as 3 primeiras páginas, ~300 registros, em vez
de todos os milhares de SP):

```bash
python coleta/coleta_salic.py --uf SP --max-paginas 3
```

Rodar de novo não duplica dados — o script atualiza os registros já
existentes em vez de criar cópias (ver `docs/decisoes.md`, item 4).

## Descoberta diária de novas empresas (opcional)

```bash
python coleta/coleta_diaria.py
```

Percorre estados além de SP (MG, PR, RJ, MT, GO, nessa ordem), com meta
de ~30 empresas novas por execução, lembrando entre execuções de onde
parou em cada estado (`dados/estado_coleta_diaria.json`). Não roda
sozinho 24/7 — precisa ser agendado (ex: Windows Task Scheduler; o passo
a passo completo está comentado no fim de `coleta/coleta_diaria.py`).
Log de cada execução em `dados/logs/coleta_diaria.log`.

## Como ver o relatório sem coletar de novo

```bash
python processamento/relatorio.py
```

## Como abrir a plataforma (IORM Radar)

```bash
streamlit run app.py
```

Abre automaticamente em `http://localhost:8501`. A plataforma **lê e
escreve** o banco (`dados/iorm_radar.db`) — leitura para os radares e
scores, escrita para o Cérebro da OSC, Pipeline/CRM e Radar de Editais
(tudo com trilha de auditoria: origem, data, status). Nunca sobrescreve
dado coletado automaticamente com edição manual sem deixar isso
registrado.

Se a porta 8501 já estiver em uso, descubra o processo e encerre-o, ou
use outra porta:

```bash
streamlit run app.py --server.port 8502
```

## Como rodar os testes automáticos

```bash
pytest
```

Mais de 400 testes cobrindo validação de dados, banco, filtros, scores, motor de
aderência e situação de editais, fontes de dados, provedores de contato e de
incentivo, documentos, CRM/Pipeline, Linha Cruzada, formatação brasileira e
renderização de todas as páginas (teste de fumaça com o Streamlit AppTest).

---

## COMO USAR O IORM RADAR (para quem não programa)

**1. Iniciar**: abra um terminal na pasta do projeto e rode
`streamlit run app.py`. Espere aparecer "You can now view your Streamlit
app in your browser" com um endereço `http://localhost:8501`.

**2. Abrir a plataforma**: cole esse endereço no navegador (ou ele às
vezes abre sozinho).

**3. Navegar**: use o menu na barra lateral esquerda, organizado em
Visão Geral, Inteligência, Captação e Sistema (ver "Status atual" acima).

**4. Ver o resumo do dia**: a página **Dashboard** mostra, sem precisar
navegar em mais nada, quantas empresas estão no radar, quais são
prioritárias hoje, quais follow-ups estão atrasados e como está o funil
de captação.

**5. Conferir/editar o perfil do IORM**: a página **Cérebro da OSC**
guarda missão, territórios, programas, temas e palavras-chave do IORM.
Isso não é só uma ficha — o território cadastrado aqui é o que define
quais empresas contam como "prioritárias por cidade" no Radar de
Empresas, e os temas/território cadastrados aqui são usados para
calcular a aderência de cada edital no Radar de Editais. Cada campo
mostra se veio de uma fonte externa verificada ou foi preenchido
manualmente.

**6. Usar os filtros do Radar de Empresas**: escolha os valores que
quiser na barra lateral (Estado, Cidade, Score mínimo, CNPJ, Tipo de
informação, Ordenar por) e só então clique em **Aplicar Filtros** — a
tabela não muda antes disso, de propósito, pra você poder ajustar vários
filtros sem a tela recarregar toda hora. Use **Limpar Filtros** para
voltar ao ponto inicial.

**7. Abrir a ficha de uma empresa**: no Radar de Empresas, busque pelo
nome e selecione. Você verá identificação, os três scores explicados,
histórico de incentivo, relação com o IORM (se já apoiou algum projeto
do próprio IORM ou é de cidade estratégica), presença digital, contatos,
evidências de ESG e ações rápidas (pesquisar/atualizar, adicionar ao
Pipeline, abrir a fonte oficial).

**8. Pesquisar contatos de uma empresa**: na ficha, clique em
**Pesquisar/Atualizar**. Se houver uma chave SerpApi configurada em
`.env`, a busca roda na hora. Sem chave configurada, a empresa entra
numa fila visível em Configurações → Fila de Pesquisa, para um agente
processar depois.

**9. Cadastrar e avaliar um edital**: no **Radar de Editais**, use
"Cadastrar oportunidade manualmente" com os dados reais do edital (nunca
invente um). O sistema calcula a aderência (0–10) automaticamente contra
o perfil do IORM, mostrando o motivo de cada nota e os pontos de
atenção.

**10. Acompanhar uma negociação**: no **Pipeline**, crie uma
oportunidade (ligada ou não a uma empresa do radar e a um
programa/projeto do IORM), mova pelo Kanban conforme o estágio avança,
registre a próxima ação e o histórico de interações (ligação, e-mail,
reunião etc.) na timeline.

**11. Interpretar os scores**:
- **IORM Score** (0–100): afinidade histórica com o IORM (já doou via
  Lei Rouanet? é de uma cidade estratégica cadastrada no Cérebro da OSC?
  já apoiou um projeto do IORM?).
- **Contactability Score** (0–100): facilidade de abordagem (achamos
  site? e-mail? telefone? LinkedIn?).
- **Prioridade de Prospecção** (0–100): combina os dois acima — o número
  mais útil para decidir "quem eu procuro primeiro".
- **Aderência de edital** (0–10): o quanto um edital combina com o perfil
  do IORM, por 6 critérios (área, território, público, elegibilidade,
  valor, prazo).
- Todas as fórmulas estão sempre visíveis na página Configurações.

**12. Exportar**: botões **Baixar (CSV)** nas páginas Radar de Empresas,
Oportunidades e Contatos.

### Como atualizar os dados

- **Coleta SALIC** (histórico de incentivo): `python coleta/coleta_salic.py --uf SP`
  — chama a API oficial do governo diretamente, sem depender de IA.
- **Enriquecimento de contatos**: com `SERPAPI_API_KEY` configurada em
  `.env`, roda ao vivo pelo botão Pesquisar/Atualizar. Sem chave, um
  agente (humano ou IA) usa ferramentas de busca, gera um JSON com os
  achados e roda `python coleta/importar_enriquecimento.py caminho/do/arquivo.json`.
- **Editais**: cadastro manual (formulário no Radar de Editais) — não há
  fonte automática conectada nesta etapa (ver Limitações abaixo).

### O que cada fonte significa

- **SALIC / Lei Rouanet**: API oficial do Ministério da Cultura. Mostra
  quem já doou dinheiro (via desconto no Imposto de Renda) para projetos
  culturais — inclusive projetos do próprio IORM.
- **Pesquisa de enriquecimento**: informações públicas encontradas em
  sites oficiais das empresas, redes sociais institucionais e fontes
  jornalísticas/cadastrais, cada uma com nível de confiança
  (ALTO/MÉDIO/BAIXO/NÃO CONFIRMADO).
- **Editais cadastrados manualmente**: qualquer edital, chamada, prêmio,
  fundo ou patrocínio que a equipe encontrou e cadastrou à mão, sempre
  com a fonte de onde veio.

## Deploy (colocar no ar)

**Não foi publicado nesta etapa** — o que segue é o caminho recomendado
e por quê, para quando a equipe decidir publicar.

**Alvo recomendado: Streamlit Community Cloud** (gratuito, baseado em
repositório GitHub — é o caminho compatível com Streamlit que exige
menos infraestrutura nova):

1. Criar um repositório no GitHub (este projeto ainda não é um
   repositório Git — ver abaixo) e dar push do código.
2. Em https://share.streamlit.io, conectar a conta GitHub e apontar para
   o repositório, arquivo principal `app.py`.
3. Configurar `SERPAPI_API_KEY` (se for usar) em **Settings → Secrets**
   do Streamlit Cloud — nunca commitar a chave no repositório.
4. O banco `dados/iorm_radar.db` está versionado no Git (decisão
   registrada em `docs/decisoes.md`, item 7.6), então o deploy já sobe
   com os dados reais já coletados.

**Limitações importantes a entender antes de publicar:**

- **Persistência do SQLite no Streamlit Cloud é limitada**: escritas
  feitas por usuários da versão publicada (novas oportunidades no
  Pipeline, edições no Cérebro da OSC, editais cadastrados) **podem ser
  perdidas quando o app reinicia** (redeploys, hibernação por
  inatividade). Para uso real em produção por múltiplas pessoas ao mesmo
  tempo, o caminho correto é migrar para um banco Postgres gerenciado
  (ex: Supabase, Neon) — o schema atual não tem nada específico do
  SQLite que impeça essa migração, mas ela não foi feita nesta etapa.
- **Nunca expor o SQLite diretamente pela internet** — hoje ele só é
  acessado localmente pelo processo Streamlit, o que é seguro; isso
  precisa continuar valendo em qualquer forma de deploy.
- **Autenticação**: o Streamlit Community Cloud tem controle de acesso
  por e-mail (`share.streamlit.io` → app settings → viewers), útil para
  restringir a um público interno da equipe do IORM antes de pensar em
  login multiempresa.
- **Multi-OSC**: o schema já comporta múltiplas organizações (ver
  `docs/decisoes.md`, item 7.8), mas hoje só existe uma tela sem seleção
  de OSC ativa — adequado para o piloto (só o IORM), não para múltiplos
  clientes simultâneos.

## Limitações conhecidas desta etapa

- **Radar de Editais sem fonte automática**: nenhuma API/portal de
  editais foi integrado (pesquisa de mercado documentada em
  `docs/decisoes.md`, item 7.4). Cadastro é manual.
- **Busca de contatos ao vivo depende de uma chave SerpApi própria**: sem
  ela, o fluxo é o mesmo da v2 (fila manual + importação por agente).
- **Sem detalhamento por projeto/ano para a maioria das empresas de SP**:
  só as empresas das 4 cidades do IORM têm detalhamento; as demais ainda
  têm só o valor agregado do SALIC.
- **CNPJ nem sempre disponível**: quando o SALIC não fornece um CNPJ
  matematicamente válido, o campo fica "não confirmado".
- **CNAE e situação cadastral**: ainda não integrados.
- **Enriquecimento de contatos cobre um subconjunto das empresas** — as
  demais ainda não foram pesquisadas.
- **Só Lei Rouanet integrada de fato**; os demais mecanismos aparecem
  cadastrados com status 🔴/🟡/🔵 (ver Configurações → Mecanismos de
  Incentivo), nunca como se já funcionassem.
- **Sem autenticação/multi-usuário**: qualquer pessoa com acesso à URL
  local (ou ao deploy, se publicado sem restrição) pode editar Pipeline,
  Cérebro da OSC e Radar de Editais.
- **Não publicado publicamente**: ver seção Deploy acima.

## Próximo passo recomendado

1. Expandir o enriquecimento de contatos para mais empresas.
2. Avaliar contratar uma chave SerpApi (ou provedor equivalente) para
   tornar a busca de contatos ao vivo por padrão.
3. Adicionar a ação "Registrar contato manualmente" na ficha da empresa
   (hoje só existe registrar contato indiretamente via pesquisa
   automática/importação).
4. Decidir se/quando publicar no Streamlit Community Cloud, considerando
   as limitações de persistência descritas acima.
5. Se e quando surgir uma segunda OSC cliente, planejar a migração para
   Postgres e a seleção de OSC ativa por login.

---

## COMO ESTOU APRENDENDO

Esta seção existe porque quem está construindo este projeto está
começando em programação agora. Aqui vai o que cada pasta/arquivo faz,
em linguagem simples:

```
iorm-radar/
├── dados/
│   ├── brutos/          → "provas" originais, exatamente como a API respondeu.
│   │                       Nunca são editadas. Servem pra auditoria.
│   └── iorm_radar.db     → o banco de dados de verdade, já organizado em tabelas.
├── coleta/
│   ├── coleta_salic.py         → o "robô" que liga pra API do SALIC e traz os dados
│   │                              agregados.
│   ├── coleta_salic_doacoes.py → detalha por projeto/ano as empresas que já têm CNPJ.
│   └── importar_enriquecimento.py → grava no banco os achados de pesquisa de
│                                      contatos (vindos de um arquivo JSON).
├── app.py                 → monta a navegação (Visão Geral/Inteligência/Captação/
│                              Sistema) e carrega as variáveis do .env.
├── paginas/                → uma tela por arquivo, cada uma só chama funções de
│   │                          processamento/ — não faz cálculo nem grava no banco
│   │                          diretamente.
│   ├── _shared.py         → sistema visual (cores, cabeçalho, cartões, badges),
│   │                          conexão com o banco e cache dos dados carregados.
│   ├── dashboard.py       → visão geral consolidada.
│   ├── cerebro_osc.py     → perfil institucional do IORM.
│   ├── radar_empresas.py  → lista e ficha de empresas.
│   ├── radar_editais.py   → cadastro e aderência de editais.
│   ├── crm.py             → Pipeline (Kanban + timeline de interações).
│   ├── oportunidades.py   → ranking gerado pelo radar (não confundir com Pipeline).
│   ├── contatos.py        → visão consolidada de contatos encontrados.
│   └── configuracoes.py   → fórmulas dos scores, status dos mecanismos, fontes.
├── processamento/
│   ├── validadores.py     → checa se um dado faz sentido (CNPJ válido? UF existe?).
│   ├── transformacao.py   → organiza o dado cru da API do SALIC pro banco.
│   ├── enriquecimento.py  → validação equivalente para contatos/presença digital.
│   ├── banco.py           → cria tabelas e salva sem duplicar.
│   ├── metricas.py        → calcula os scores e monta as tabelas da dashboard.
│   ├── osc.py              → perfil da OSC (Cérebro da OSC) e semeadura inicial.
│   ├── editais.py          → cadastro de editais e motor de aderência explicável.
│   ├── crm.py               → oportunidades, estágios, interações, follow-ups.
│   ├── mecanismos.py       → catálogo de mecanismos de incentivo e status real
│   │                          de integração de cada um.
│   ├── busca_providers.py  → abstração de provedor de busca (SerpApi hoje,
│   │                          plugável para trocar depois).
│   ├── pesquisa_empresa.py → liga um provedor de busca aos dados de contato
│   │                          salvos no banco.
│   ├── formatacao.py       → formata moeda, CNPJ, data e percentual em português.
│   ├── filtros.py          → aplica os filtros da tabela de Empresas.
│   └── relatorio.py        → só lê o banco e imprime um resumo.
├── testes/                 → checam automaticamente se o código continua
│                              funcionando. Rode `pytest` sempre que mudar algo.
├── docs/
│   └── decisoes.md         → registro de escolhas tomadas onde havia mais de um
│                              jeito razoável de fazer, explicando o porquê.
├── .env.example             → modelo de configuração (chave da SerpApi). Copie
│                              para `.env` e preencha — o `.env` nunca vai pro Git.
├── conftest.py              → arquivo técnico que ajuda o pytest a encontrar os
│                              outros arquivos do projeto. Não precisa mexer nele.
├── requirements.txt         → lista das bibliotecas Python que o projeto usa.
└── README.md                 → este arquivo.
```

**Por que Python?** É uma linguagem fácil de ler (quase parece inglês
simples) e tem tudo pronto pra "buscar dado na internet, guardar num
banco de dados" sem precisar escrever muita coisa do zero.

**Por que SQLite?** É um banco de dados que é só **um arquivo único** no
seu computador — sem precisar instalar nenhum programa servidor. Ótimo
pra aprender e pra projetos pequenos/médios. Quando o projeto crescer
bastante (múltiplas OSCs, múltiplos usuários simultâneos gravando ao
mesmo tempo em produção), dá pra trocar por um banco mais robusto
(PostgreSQL) sem precisar redesenhar as tabelas.

**Por que separar `paginas/` de `processamento/`?** Cada `paginas/*.py`
só sabe "desenhar a tela e chamar uma função" — todo cálculo, validação
e acesso ao banco fica em `processamento/`. Isso permite testar toda a
lógica (`processamento/`) sem precisar abrir o navegador nem o
Streamlit, e faz o `pytest` rodar em menos de 2 segundos mesmo com 147
testes.
