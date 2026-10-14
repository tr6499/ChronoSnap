import json

from database import SessionLocal
from models import (
    Funcionario,
    FuncionarioLoja,
    Loja,
    UsuarioRelogio
)
from services.idclass import IDClass


def sincronizar_usuarios(loja_id):

    db = SessionLocal()

    try:

        # ====================================================
        # BUSCAR LOJA
        # ====================================================

        loja = db.query(Loja).filter(
            Loja.id == loja_id
        ).first()

        if loja is None:
            raise Exception(
                f"Loja ID {loja_id} não encontrada"
            )

        # ====================================================
        # CONECTAR AO RELÓGIO
        # ====================================================

        equipamento = IDClass(
            loja.ip,
            username=loja.usuario or "admin",
            password=loja.senha or "7070",
            timeout=30
        )

        equipamento.login_device()

        try:

            layout = (
                loja.afd_layout or "legado"
            ).strip().lower()

            mode = 671 if layout in (
                "671",
                "portaria671",
            ) else 0

            # =================================================
            # BUSCAR USUÁRIOS
            # =================================================

            usuarios = equipamento.load_all_users(
                mode=mode,
                templates=True
            )

        finally:

            equipamento.logout()

        # ====================================================
        # SINCRONIZAÇÃO
        # ====================================================

        inseridos = 0
        atualizados = 0
        funcionarios_criados = 0
        funcionarios_atualizados = 0

        for usuario in usuarios:

            # ------------------------------------------------
            # REGISTRATION = NÚMERO DO CRACHÁ
            # ------------------------------------------------

            numero_cracha = usuario.get("registration")

            if numero_cracha is None:
                continue

            numero_cracha = str(numero_cracha)

            nome = str(
                usuario.get("name") or ""
            ).strip()

            administrador = bool(
                usuario.get("admin", False)
            )

            biometrias = usuario.get("templates") or []

            if mode == 671:

                pis = None
                cpf = (
                    str(usuario["cpf"])
                    if usuario.get("cpf") is not None
                    else None
                )

            else:

                cpf = None
                pis = (
                    str(usuario["pis"])
                    if usuario.get("pis") is not None
                    else None
                )

            funcionario = db.query(
                Funcionario
            ).filter(
                Funcionario.matricula == numero_cracha
            ).first()

            if funcionario:

                if nome:
                    funcionario.nome = nome

                if pis:
                    funcionario.pis = pis

                if cpf:
                    funcionario.cpf = cpf

                funcionario.administrador = administrador

                for atributo, chave in (
                    ("codigo", "code"),
                    ("rfid", "rfid"),
                    ("bars", "bars"),
                ):
                    valor = usuario.get(chave)
                    if valor is not None:
                        setattr(funcionario, atributo, valor)

                funcionario.biometrias = json.dumps(
                    biometrias
                ) if biometrias else funcionario.biometrias

                funcionarios_atualizados += 1

            else:

                funcionario = Funcionario(
                    matricula=numero_cracha,
                    nome=nome or "Funcionário sem nome",
                    pis=pis,
                    cpf=cpf,
                    ativo=True,
                    administrador=administrador,
                    codigo=usuario.get("code"),
                    rfid=usuario.get("rfid"),
                    bars=usuario.get("bars"),
                    biometrias=(
                        json.dumps(biometrias)
                        if biometrias
                        else None
                    )
                )

                db.add(funcionario)
                db.flush()
                funcionarios_criados += 1

            relacionamento = db.query(
                FuncionarioLoja
            ).filter(
                FuncionarioLoja.funcionario_id
                == funcionario.id,
                FuncionarioLoja.loja_id == loja.id
            ).first()

            if not relacionamento:
                db.add(
                    FuncionarioLoja(
                        funcionario_id=funcionario.id,
                        loja_id=loja.id
                    )
                )

            # ------------------------------------------------
            # PROCURAR USUÁRIO JÁ EXISTENTE
            # ------------------------------------------------

            existente = db.query(
                UsuarioRelogio
            ).filter(
                UsuarioRelogio.loja_id == loja.id,
                UsuarioRelogio.numero_cracha == numero_cracha
            ).first()

            # ------------------------------------------------
            # ATUALIZAR
            # ------------------------------------------------

            if existente:

                existente.nome = nome

                existente.pis = pis

                existente.codigo = usuario.get("code")

                existente.rfid = usuario.get("rfid")

                existente.bars = usuario.get("bars")

                existente.templates_count = (
                    usuario.get("templates_count", 0)
                )

                existente.password = usuario.get("password")

                existente.admin = usuario.get(
                    "admin",
                    False
                )

                atualizados += 1

            # ------------------------------------------------
            # INSERIR
            # ------------------------------------------------

            else:

                novo = UsuarioRelogio(

                    loja_id=loja.id,

                    nome=nome,

                    numero_cracha=numero_cracha,

                    pis=pis,

                    codigo=usuario.get("code"),

                    rfid=usuario.get("rfid"),

                    bars=usuario.get("bars"),

                    templates_count=usuario.get(
                        "templates_count",
                        0
                    ),

                    password=usuario.get(
                        "password"
                    ),

                    admin=usuario.get(
                        "admin",
                        False
                    )
                )

                db.add(novo)

                inseridos += 1

        db.commit()

        return {
            "success": True,
            "loja_id": loja.id,
            "loja": loja.numero,
            "total_relogio": len(usuarios),
            "inseridos": inseridos,
            "atualizados": atualizados,
            "funcionarios_criados": funcionarios_criados,
            "funcionarios_atualizados": funcionarios_atualizados
        }

    except Exception:

        db.rollback()

        raise

    finally:

        db.close()