from sqlalchemy import Column, Integer, String, Boolean, DateTime
from datetime import datetime
from database import Base


class UsuarioSistema(Base):
    """Modelo para usuários do sistema de administração"""
    
    __tablename__ = "usuarios_sistema"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    username = Column(
        String(50),
        unique=True,
        nullable=False,
        index=True
    )

    password_hash = Column(
        String(255),
        nullable=False
    )

    email = Column(
        String(100),
        nullable=True
    )

    nome = Column(
        String(150),
        nullable=False
    )

    perfil = Column(
        String(20),
        nullable=False,
        default="Restrito"  # 'Completo' ou 'Restrito'
    )

    ativo = Column(
        Boolean,
        default=True
    )

    criado_em = Column(
        DateTime,
        default=datetime.utcnow
    )

    atualizado_em = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )


class ConfiguracaoSistema(Base):
    """Configurações globais do sistema"""
    
    __tablename__ = "configuracoes_sistema"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    chave = Column(
        String(100),
        unique=True,
        nullable=False,
        index=True
    )

    valor = Column(
        String(500),
        nullable=True
    )

    descricao = Column(
        String(300),
        nullable=True
    )


class LogAuditoria(Base):
    __tablename__ = "logs_auditoria"

    id = Column(Integer, primary_key=True, index=True)
    criado_em = Column(DateTime, default=datetime.utcnow, index=True)
    usuario_id = Column(Integer, nullable=True, index=True)
    username = Column(String(50), nullable=False, index=True)
    acao = Column(String(100), nullable=False, index=True)
    recurso = Column(String(100), nullable=False)
    detalhes = Column(String(2000), nullable=True)
    sucesso = Column(Boolean, nullable=False, default=True)
    status_code = Column(Integer, nullable=True)
