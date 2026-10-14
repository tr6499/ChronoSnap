# ChronoSnap

Sistema web para gestão de ponto e de equipamentos Control iD iDClass. Permite
gerenciar empresas, lojas, funcionários e usuários, importar e consultar
marcações AFD, gerar arquivos RM/TOTVS e configurar tarefas automáticas.

## Licença

Este projeto é distribuído sob a **Licença Proprietária de Software — Todos os
Direitos Reservados**. Consulte o arquivo [LICENSE](./LICENSE). O código não
pode ser copiado, modificado, redistribuído ou utilizado comercialmente sem
autorização escrita do titular.

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

Por padrão, o servidor aceita conexões somente do próprio computador. Para
acesso pela rede local, configure o host e a exposição de rede de acordo com a
política de segurança do ambiente. Não exponha o serviço diretamente à
internet.

## Primeiro acesso

Em um banco novo, o sistema cria automaticamente o usuário `admin` com a senha
inicial `admin`. Altere essa senha imediatamente pela tela de configurações.
Se o banco já existir, as credenciais e os dados existentes são preservados;
o sistema não redefine a senha do administrador.

## Dados e arquivos operacionais

- O banco SQLite é local e fica em `banco\afd.db`. Ele é criado quando o
  sistema inicia e não faz parte desta distribuição.
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
└── README.md
```

## Documentação de autenticação

Consulte [AUTENTICACAO.md](./AUTENTICACAO.md) para informações sobre acesso,
perfis, sessões e gerenciamento de usuários.
