# ChronoSnap

Sistema web para gestão de ponto e de equipamentos Control iD iDClass. Permite
gerenciar empresas, lojas, funcionários e usuários, importar e consultar
marcações AFD, gerar arquivos RM/TOTVS e configurar tarefas automáticas.

## Licença

O ChronoSnap é distribuído sob a **GNU General Public License, versão 3
(GPL-3.0-only)**. Consulte [LICENSE](./LICENSE) e o texto integral em
[COPYING](./COPYING). As contribuições de terceiros continuam sujeitas aos
avisos e licenças indicados junto aos respectivos componentes.

Contribuições enviadas por pull request também exigem a assinatura do
[Contributor License Agreement](./CLA.md) por meio do CLA Assistant.

## Funcionalidades

- Autenticação de usuários e controle de acesso por perfil;
- cadastro de empresas, lojas e funcionários;
- consulta e sincronização de usuários com relógios iDClass;
- download e processamento de arquivos AFD;
- consulta de espelhos de ponto e geração de arquivos RM/TOTVS;
- dashboard, auditoria e configurações de retenção do banco;
- agendamento de capturas automáticas de AFD e marcações.

## Requisitos

- Windows;
- Python 3.11 ou superior;
- acesso à rede dos relógios para as operações com equipamentos.

As dependências Python estão listadas em `server\requirements.txt`.

## Instalação

No PowerShell, a partir da pasta do projeto:

```powershell
cd C:\ChronoSnap
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r .\server\requirements.txt
```

Se o PowerShell bloquear a ativação do ambiente virtual, execute o Python e o
Uvicorn diretamente:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\server\requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app:app --app-dir .\server --host 127.0.0.1 --port 8000
```

## Iniciar o sistema

Com o ambiente virtual ativado:

```powershell
cd C:\ChronoSnap\server
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Abra <http://127.0.0.1:8000/auth/login>. Para encerrar o servidor, pressione
`Ctrl+C` no terminal em que ele está sendo executado.

No ChronoSnap Manager, escolha **Somente neste computador** para acesso local
ou **Rede local** para permitir conexões de outros computadores. Na opção de
rede, os usuários acessam `http://IP-DO-SERVIDOR:8000/auth/login`; obtenha o
IPv4 do computador que executa o ChronoSnap com `ipconfig` e permita a porta
TCP configurada no Firewall do Windows para a rede privada. Não exponha o
serviço diretamente à internet.

No Manager para Windows, marque **Minimizar para a bandeja** para que a janela
seja ocultada da barra de tarefas ao minimizá-la, permanecendo disponível na
área de notificação. O menu do ícone permite exibir o painel, iniciar ou parar
o servidor e **Parar e sair**. A opção vem desmarcada por padrão; sem ela,
minimizar e fechar mantêm o comportamento normal.

## Configurar o banco de dados (PostgreSQL e outros)

O sistema usa SQLite por padrão. Em **Configurações → Banco de dados**, escolha
SQLite, PostgreSQL, MySQL, MariaDB, SQL Server ou Oracle, preencha os dados de
conexão e use **Testar conexão** e **Aplicar**. O usuário do banco precisa ter
permissão para criar tabelas. A troca vale a partir do próximo início do
servidor, reiniciado pelo Manager.

O botão **Aplicar** faz a ação completa. Se existir um arquivo SQLite, a opção
**Copiar os dados do SQLite para este banco** vem marcada e o botão passa a
migrar; desmarcada, ele só salva a conexão e cria as tabelas. A migração vale
para todos os bancos, confere as contagens de cada tabela e exige um banco de
destino vazio (os dados padrão da primeira inicialização são substituídos).
Durante a cópia, as gravações no SQLite ficam bloqueadas; por isso, faça a
migração em um período de baixa atividade. O arquivo SQLite original é mantido.
O espelho de ponto e a pré-visualização do AFD consultam as marcações já
carregadas no banco de dados e não acessam os relógios. Faça uma carga manual
ou configure a captura automática para manter esses dados atualizados. O botão
de gerar/baixar o AFD original continua lendo diretamente do relógio.
Na página AFD, **Importar marcações** carrega do relógio as marcações das
empresas selecionadas no período informado e grava os registros no banco para
consulta posterior.
Em todos os bancos também é possível **Criar automaticamente** o usuário (e o
banco) informando uma conta administradora (`postgres`, `root`, `sa` ou
`system`), que não é gravada. No Oracle só o usuário é criado: o service name
informado deve existir, de preferência um PDB (ex.: `XEPDB1`), e o usuário é
criado em maiúsculas. Usuário ou banco já existentes são recusados.

No instalador do Windows, a página **Banco de dados** mantém SQLite como opção
padrão (sem download) e permite baixar e instalar PostgreSQL, MariaDB ou MySQL
localmente. As opções de servidor requerem internet e privilégios
administrativos. Para uma instalação nova, o instalador cria um banco e um
usuário exclusivos do ChronoSnap e configura a conexão; se já houver serviço
do banco escolhido ou uma configuração de banco existente, ela é preservada.
Os instaladores ficam registrados em `data\logs\install_postgresql.log`,
`data\logs\install_mariadb.log` e `data\logs\install_mysql.log`. As senhas
administrativas geradas para os servidores locais não são guardadas. O
instalador também permite informar a conexão com um banco existente (MySQL,
MariaDB, SQL Server, Oracle ou PostgreSQL); nesse caso o banco e o usuário
precisam existir previamente.

O instalador do Linux pode instalar PostgreSQL localmente, com `pkexec` ou
execução como root; SQLite continua sendo o padrão.

A dashboard e a seleção de banco usam logos Devicon armazenados em
`server/static/devicons`, sem carregar recursos de terceiros em tempo de
execução. O ícone de processador é um símbolo genérico inline, pois o Devicon
não fornece ícones de Intel ou AMD. A dashboard exibe o fabricante detectado
(Intel, AMD, Apple, ARM ou outro) junto da arquitetura, além do logo do sistema
operacional quando disponível. Os assets Devicon e sua licença estão na pasta
dedicada, permitindo reverter a apresentação sem alterar os dados ou a
configuração do banco.

A senha da conexão é mantida em `database.json` na pasta de dados, com acesso
restrito ao usuário que executa o Manager. Não compartilhe esse arquivo. As
ferramentas específicas de arquivo SQLite, como compactação, ficam
indisponíveis quando outro banco está em uso.

Se o PostgreSQL já estiver instalado, use os dados da conexão nessa página. A
instalação do servidor não modifica uma configuração existente.
Desinstalar o ChronoSnap não remove o serviço PostgreSQL nem seus bancos; a
remoção deles deve ser feita separadamente para evitar apagar outros dados.

## Primeiro acesso

Em um banco novo, o sistema cria automaticamente o usuário `admin` com a senha
inicial `admin`. Altere essa senha imediatamente pela tela de configurações.
Se o banco já existir, as credenciais e os dados existentes são preservados;
o sistema não redefine a senha do administrador.

## Dados e arquivos operacionais

- O banco SQLite é local e fica em `banco\afd.db`. Ele é criado quando o
  sistema inicia e não faz parte desta distribuição.
- A configuração de conexão selecionada fica em `database.json`, na pasta de
  dados; ela pode conter a senha do PostgreSQL e não deve ser compartilhada.
- Configurações operacionais de automação ficam em
  `server\logs\automacoes.json`; o sistema cria esse arquivo quando
  necessário. Ele não faz parte desta distribuição.
- `server\downloads\` é o destino padrão de arquivos gerados e baixados.
  Arquivos dessa pasta não fazem parte desta distribuição.

Os dados locais, o banco, as configurações de automação e os arquivos baixados
são ignorados pelo Git para evitar publicar dados de empresas ou equipamentos.

## Estrutura

```text
ChronoSnap/
├── server/
│   ├── app.py
│   ├── database.py
│   ├── models.py
│   ├── models_usuarios.py
│   ├── requirements.txt
│   ├── routes/
│   ├── services/
│   ├── static/
│   ├── templates/
│   ├── downloads/       # criado em tempo de execução
│   └── logs/            # criado em tempo de execução
├── AUTENTICACAO.md
├── LICENSE
├── COPYING
├── CLA.md
├── CONTRIBUTING.md
└── README.md
```

## Documentação de autenticação

Consulte [AUTENTICACAO.md](./AUTENTICACAO.md) para informações sobre acesso,
perfis, sessões e gerenciamento de usuários.

## Distribuição e builds

O projeto é software livre sob GPL-3.0-only. Os instaladores compilam os
componentes Python com Nuitka; a licença GPL e os avisos aplicáveis acompanham
os pacotes.

### Gerar os instaladores

- **Windows** (Python 3.12 e Inno Setup 6 instalados):
  `powershell -File build\build_windows.ps1` → `build\out\ChronoSnap-Setup-<versão>.exe`
  (assistente com a GPL, escolha da pasta de instalação e atalhos).
- **Linux** (x86_64, com gcc e patchelf): `sh build/build_linux.sh` →
  `build/out/ChronoSnap-linux-x64-<versão>.tar.gz`. O cliente extrai e executa
  `instalar.sh` (instalador visual).

Cada sistema operacional deve ser compilado no próprio sistema. Os dados
(banco, logs e downloads) ficam em `<instalação>\data` e são preservados em
atualizações.

## Contribuições

Leia o [Contributor License Agreement](./CLA.md) antes de enviar um pull
request. O CLA Assistant solicitará a assinatura no próprio pull request.
Para ativar o fluxo, os mantenedores devem instalar e configurar o aplicativo
[CLA Assistant](https://cla-assistant.io/) para este repositório, usando o
conteúdo de `CLA.md`.
