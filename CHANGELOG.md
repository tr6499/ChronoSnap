# Histórico de versões

## 1.0.6 — 31/10/2026

### Corrigido

- Exportação RM TOTVS: uso do horário local preservado no AFD original,
  evitando acréscimos de fuso ao exportar marcações armazenadas no banco.
- Exportação RM TOTVS baseada nas marcações carregadas no banco, sem consultar
  o relógio quando não há dados para o período; a leitura direta do AFD também
  respeita o leiaute configurado para a empresa.

## 1.0.5 — 29/10/2026

### Adicionado

- Manual ilustrado de operação para o perfil Usuário, disponível em PDF e
  incluído no instalador Windows.

### Corrigido

- Gráfico de status do dashboard: a contagem de empresas para verificar agora
  inclui estados desatualizados e timeouts; o gráfico também se ajusta melhor a
  telas intermediárias e exibe corretamente o estado sem empresas.
- Ícone do ChronoSnap exibido na lista de aplicativos do Windows e na tela de
  desinstalação, agora usando `chronosnap-program.ico`.

## 1.0.4 — 28/10/2026

### Adicionado

- Importação manual de marcações AFD com seleção explícita da empresa e
  detecção automática dos leiautes Legado/595 e Portaria 671.
- Deduplicação das marcações importadas por empresa.

### Corrigido

- Layout da página de configuração de banco de dados no instalador Windows,
  com posicionamento dos campos ajustado para evitar cortes em diferentes
  escalas de tela.
- Status dos relógios verificado pela API Control iD, em vez de uma resposta
  genérica a ping/HTTPS. Falhas de autenticação ou da API não são confundidas
  com relógios offline; timeout ou estado antigo aparecem como
  “Sem verificação recente”. O horário da última verificação também fica
  visível no gerenciamento de empresas.

## 1.0.3 — 28/10/2026

### Adicionado

- Página “Sobre o ChronoSnap” com nome do autor, versão, texto integral da
  GNU GPL v3 e link para a página oficial da GNU.
- Menu “Sobre” no Manager, com acesso ao texto da licença incluído na
  instalação e à página oficial da GNU.

### Melhorado

- Cartões de seleção de empresas na geração do AFD reorganizados para facilitar
  a leitura; os números das empresas deixaram de aparecer nos cartões.
- Alinhamento e espaçamento dos botões e do checkbox na configuração do banco
  de dados.
- Documentação da instalação pelo instalador e da execução manual para
  desenvolvimento.
