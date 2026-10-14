# Autenticação e usuários

O AFD-IDClass usa contas armazenadas no banco SQLite local `banco\afd.db`.
Senhas são armazenadas como hashes bcrypt; a senha em texto puro não é gravada
no banco. O banco e as contas da empresa não são incluídos na distribuição Git.

## Primeiro acesso

Quando não existe uma conta `admin`, a inicialização cria o usuário
administrador com:

- **Usuário:** `admin`
- **Senha inicial:** `admin`
- **Perfil:** `Completo`

Altere a senha inicial antes de usar o sistema. Em instalações com banco
existente, o sistema preserva a conta e a senha já cadastradas e não recria nem
redefine o administrador.

1. Inicie o sistema seguindo as instruções do [README](./README.md).
2. Acesse <http://127.0.0.1:8000/auth/login>.
3. Entre com uma conta ativa.
4. Acesse **Configuração → Mudar Senha Admin** para trocar a senha do
   administrador.

As senhas novas devem ter pelo menos seis caracteres.

## Perfis e permissões

- **Completo:** pode acessar as configurações e gerenciar usuários.
- **Restrito:** tem acesso às funções operacionais permitidas, mas não às
  configurações administrativas protegidas.

O usuário `admin` é protegido: não pode ser editado, desativado nem excluído
pela tela de gerenciamento. Outros usuários podem ser criados, editados,
desativados ou excluídos por um usuário com perfil completo.

## Sessões

Depois de um login válido, o sistema cria uma sessão e entrega o identificador
em um cookie `HttpOnly` chamado `chronosnap_session`.

- Sem **Lembrar-me**, a sessão expira após 2 horas e o cookie é de sessão.
- Com **Lembrar-me**, a sessão expira após 8 horas e o cookie também expira
  após 8 horas.
- As sessões são mantidas em memória pelo processo do servidor. Reiniciar o
  servidor invalida as sessões existentes; será necessário entrar novamente.
- Use **Sair** para encerrar a sessão atual.

## Modo Admin

O modo admin permite acesso sem login e concede permissões completas. Ele pode
ser ativado ou desativado em **Configuração → Modo Admin**. Use-o somente em
um ambiente controlado e confiável; mantenha-o desativado para a operação
normal. A configuração é mantida em memória e volta ao estado desativado
quando o servidor reinicia.

## Telas e endpoints

| Método | Caminho | Descrição |
| --- | --- | --- |
| `GET` | `/auth/login` | Exibe a página de login |
| `POST` | `/auth/login` | Autentica uma conta |
| `GET` | `/auth/logout` | Encerra a sessão atual |
| `GET` | `/config/usuarios` | Abre o gerenciamento de usuários |
| `GET` | `/config/usuarios/list` | Lista usuários para a interface |
| `POST` | `/config/usuarios` | Cria um usuário |
| `PUT` | `/config/usuarios/{usuario_id}` | Atualiza um usuário |
| `DELETE` | `/config/usuarios/{usuario_id}` | Exclui um usuário |
| `GET` | `/config/senha-admin` | Abre a tela para alterar a senha do admin |
| `POST` | `/config/senha-admin` | Altera a senha do admin |
| `GET` | `/config/modo-admin` | Abre a configuração do modo admin |
| `POST` | `/config/modo-admin` | Ativa ou desativa o modo admin |

As páginas e operações administrativas exigem autenticação e as permissões
correspondentes. As rotas de criação, edição e exclusão de usuários recebem e
retornam dados JSON.

## Recomendações de operação

- Troque a senha inicial `admin` antes de colocar o sistema em uso.
- Crie contas individuais e atribua o perfil **Restrito** quando o acesso
  administrativo não for necessário.
- Não habilite o modo admin em computadores ou redes sem controle de acesso.
- Mantenha cópias de segurança de `banco\afd.db`; ele contém contas, dados e
  configurações do sistema.
- O banco, os arquivos AFD, as exportações e as configurações operacionais
  locais são ignorados pelo Git. Não os adicione manualmente ao repositório.
- Para acesso por HTTPS, configure um proxy TLS e ajuste a opção `secure` do
  cookie de sessão em `backend\routes\auth.py` para `True`. No estado atual,
  essa opção está desativada para permitir acesso local por HTTP.

## Solução de problemas

**A senha inicial não funciona**

Ela só é usada quando o sistema cria uma conta `admin` em um banco novo. Se o
banco já continha essa conta, use a senha cadastrada. O sistema não redefine
senhas automaticamente.

**A sessão parou de funcionar**

As sessões expiram após 2 horas, ou após 8 horas se **Lembrar-me** estiver
marcado, e também são perdidas ao reiniciar o servidor. Entre novamente.

**O servidor não inicia por dependências ausentes**

Ative o ambiente virtual e instale as dependências listadas em
`backend\requirements.txt`, conforme o [README](./README.md).
