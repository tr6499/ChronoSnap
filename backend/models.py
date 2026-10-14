import json

from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, UniqueConstraint
from datetime import datetime
from database import Base


class Loja(Base):
    __tablename__ = "lojas"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    numero = Column(
        Integer,
        unique=True,
        nullable=False
    )

    nome = Column(
        String(100),
        nullable=False
    )

    ip = Column(
        String(100),
        nullable=False
    )

    porta = Column(
        Integer,
        default=443
    )

    usuario = Column(
        String(100),
        nullable=True
    )

    senha = Column(
        String(200),
        nullable=True
    )

    firmware = Column(
        String(100),
        nullable=True
    )

    endpoint_afd = Column(
        String(300),
        nullable=True
    )

    online = Column(
        Boolean,
        default=False
    )

    ultimo_teste = Column(
        String(50),
        nullable=True
    )

    tempo_resposta = Column(
        Integer,
        nullable=True
    )

    mensagem_status = Column(
        String(300),
        nullable=True
    )

    # ========================================================
    # LAYOUT DO AFD
    # ========================================================

    afd_layout = Column(
        String(20),
        nullable=False,
        default="legado"
    )


class Funcionario(Base):
    __tablename__ = "funcionarios"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    matricula = Column(
        String(50),
        nullable=False,
        index=True
    )

    nome = Column(
        String(150),
        nullable=False
    )

    pis = Column(
        String(20),
        nullable=True,
        index=True
    )

    cpf = Column(
        String(20),
        nullable=True,
        index=True
    )

    identificador_afd = Column(
        String(20),
        nullable=True,
        index=True
    )

    ativo = Column(
        Boolean,
        default=True
    )

    administrador = Column(
        Boolean,
        nullable=False,
        default=False
    )

    biometrias = Column(
        Text,
        nullable=True
    )

    codigo = Column(
        Integer,
        nullable=True,
        index=True
    )

    rfid = Column(
        Integer,
        nullable=True,
        index=True
    )

    bars = Column(
        String(100),
        nullable=True,
        index=True
    )

    @property
    def quantidade_biometrias(self):
        if not self.biometrias:
            return 0

        try:
            return len(json.loads(self.biometrias))
        except (TypeError, ValueError):
            return 0

class UsuarioRelogio(Base):
    __tablename__ = "usuarios_relogio"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    loja_id = Column(
        Integer,
        nullable=False,
        index=True
    )

    nome = Column(
        String(150),
        nullable=False
    )

    numero_cracha = Column(
        String(50),
        nullable=False,
        index=True
    )

    pis = Column(
        String(20),
        nullable=True,
        index=True
    )

    codigo = Column(
        Integer,
        nullable=True,
        index=True
    )

    rfid = Column(
        Integer,
        nullable=True
    )

    bars = Column(
        String(100),
        nullable=True
    )

    templates_count = Column(
        Integer,
        default=0
    )

    password = Column(
        String(100),
        nullable=True
    )

    admin = Column(
        Boolean,
        default=False
    )

class FuncionarioLoja(Base):
    __tablename__ = "funcionarios_lojas"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    funcionario_id = Column(
        Integer,
        nullable=False,
        index=True
    )

    loja_id = Column(
        Integer,
        nullable=False,
        index=True
    )


class MarcacaoAFD(Base):
    __tablename__ = "marcacoes_afd"
    __table_args__ = (
        UniqueConstraint("loja_id", "assinatura", name="uq_marcacao_loja_assinatura"),
    )

    id = Column(Integer, primary_key=True, index=True)
    loja_id = Column(Integer, nullable=False, index=True)
    nsr = Column(String(20), nullable=False, index=True)
    tipo = Column(String(5), nullable=True)
    layout = Column(String(20), nullable=False, index=True)
    identificador = Column(String(30), nullable=True, index=True)
    cpf = Column(String(20), nullable=True, index=True)
    pis = Column(String(20), nullable=True, index=True)
    data_hora = Column(DateTime, nullable=False, index=True)
    crc = Column(String(20), nullable=True)
    raw = Column(Text, nullable=True)
    assinatura = Column(String(64), nullable=False, index=True)
    importado_em = Column(DateTime, default=datetime.utcnow, nullable=False)