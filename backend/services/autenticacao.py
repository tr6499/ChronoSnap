import bcrypt
from datetime import datetime, timedelta
from typing import Optional
import secrets


def hash_password(password: str) -> str:
    """Hash uma senha usando bcrypt"""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica se a senha corresponde ao hash"""
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except (ValueError, TypeError):
        return False


def gerar_token() -> str:
    """Gera um token seguro"""
    return secrets.token_urlsafe(32)


class UsuarioAutenticado:
    """Classe para representar um usuário autenticado"""
    
    def __init__(self, id: int, username: str, nome: str, perfil: str):
        self.id = id
        self.username = username
        self.nome = nome
        self.perfil = perfil  # 'Completo' ou 'Restrito'
    
    def tem_permissao_ajustes(self) -> bool:
        """Verifica se pode acessar ajustes"""
        return self.perfil == "Completo"
    
    def tem_permissao_configuracoes(self) -> bool:
        """Verifica se pode acessar configurações"""
        return self.perfil == "Completo"
    
    def tem_permissao_usuarios(self) -> bool:
        """Verifica se pode gerenciar usuários"""
        return self.perfil == "Completo"


class SessaoUsuario:
    """Gerenciador de sessão de usuário"""
    
    def __init__(self):
        self.sessoes = {}  # token -> {usuario_id, username, perfil, expires_at}
    
    def criar_sessao(self, usuario_id: int, username: str, nome: str, perfil: str, duracao_minutos: int = 480) -> str:
        """Cria uma nova sessão e retorna o token"""
        token = gerar_token()
        expires_at = datetime.utcnow() + timedelta(minutes=duracao_minutos)
        
        self.sessoes[token] = {
            "usuario_id": usuario_id,
            "username": username,
            "nome": nome,
            "perfil": perfil,
            "expires_at": expires_at
        }
        
        return token
    
    def validar_sessao(self, token: str) -> Optional[dict]:
        """Valida uma sessão e retorna os dados se válida"""
        if token not in self.sessoes:
            return None
        
        sessao = self.sessoes[token]
        
        # Verificar se expirou
        if datetime.utcnow() > sessao["expires_at"]:
            del self.sessoes[token]
            return None
        
        return sessao
    
    def remover_sessao(self, token: str) -> bool:
        """Remove uma sessão (logout)"""
        if token in self.sessoes:
            del self.sessoes[token]
            return True
        return False
    
    def limpar_expiradas(self):
        """Remove todas as sessões expiradas"""
        agora = datetime.utcnow()
        tokens_expirados = [
            token for token, sessao in self.sessoes.items()
            if agora > sessao["expires_at"]
        ]
        for token in tokens_expirados:
            del self.sessoes[token]


# Instância global de gerenciador de sessão
sessao_manager = SessaoUsuario()


class ConfiguracaoAutenticacao:
    """Configurações de autenticação do sistema"""
    
    def __init__(self):
        self.admin_mode_livre = False  # Se True, entra sem login
        self.sessoes_ativas = {}
    
    def ativar_modo_admin_livre(self):
        """Ativa o modo admin sem login"""
        self.admin_mode_livre = True
    
    def desativar_modo_admin_livre(self):
        """Desativa o modo admin sem login"""
        self.admin_mode_livre = False


# Instância global de configuração
config_auth = ConfiguracaoAutenticacao()
