import requests


class UsersMixin:

    def count_users(self):

        resposta = self.call("count_users")

        return resposta["count"]

    def load_users(
        self,
        offset=0,
        limit=100,
        mode=671,
        templates=False
    ):

        payload = {
            "limit": limit,
            "offset": offset
        }

        if templates:
            payload["templates"] = True

        return self.call(
            "load_users",
            payload,
            params={
                "mode": mode
            }
        )

    def load_all_users(
        self,
        mode=671,
        templates=False
    ):

        usuarios = []
        offset = 0

        while True:

            resposta = self.load_users(
                offset=offset,
                limit=100,
                mode=mode,
                templates=templates
            )

            lote = resposta.get("users", [])

            if not lote:
                break

            usuarios.extend(lote)

            if len(usuarios) >= resposta.get("count", len(usuarios)):
                break

            offset += len(lote)

        return usuarios

    def get_user_by_registration(
        self,
        registration,
        mode=671
    ):

        registration = str(registration)

        for usuario in self.load_all_users(mode=mode):

            if str(usuario.get("registration")) == registration:
                return usuario

        return None

    def get_user_by_code(
        self,
        code
    ):

        code = int(code)

        for usuario in self.load_all_users():

            if usuario.get("code") == code:
                return usuario

        return None

    def get_user_by_cpf(
        self,
        cpf,
        mode=671
    ):

        resposta = self.call(
            "load_users",
            {
                "users_cpf": [int(cpf)],
                "limit": 1,
                "offset": 0
            },
            params={
                "mode": mode
            }
        )

        usuarios = resposta.get("users", [])

        return usuarios[0] if usuarios else None

    def get_user_by_pis(
        self,
        pis
    ):

        resposta = self.call(
            "load_users",
            {
                "users_pis": [int(pis)],
                "limit": 1,
                "offset": 0
            }
        )

        usuarios = resposta.get("users", [])

        return usuarios[0] if usuarios else None

    def search_users(
        self,
        texto
    ):

        texto = texto.upper()

        return [
            usuario
            for usuario in self.load_all_users()
            if texto in usuario.get("name", "").upper()
        ]

    def user_exists(
        self,
        registration
    ):

        return (
            self.get_user_by_registration(registration)
            is not None
        )

    def add_users(
        self,
        users,
        mode=671,
        do_match=False
    ):

        payload = {
            "users": users,
            "do_match": do_match
        }

        return self.call(
            "add_users",
            payload,
            params={
                "mode": mode
            }
        )

    def update_users(
        self,
        users,
        mode=671
    ):

        return self.call(
            "update_users",
            {
                "users": users
            },
            params={
                "mode": mode
            }
        )

    def delete_users(
        self,
        users,
        mode=671
    ):

        return self.call(
            "remove_users",
            {
                "users": users
            },
            params={
                "mode": mode
            }
        )

        def destroy_all_users(self):

            return self.call(
                "destroy_all_users"
            )

    def cadastrar_usuario(
        self,
        nome,
        matricula,
        senha="",
        cpf=None,
        pis=None,
        codigo=None,
        rfid=None,
        bars=None,
        admin=False,
        templates=None,
        mode=671
    ):

        usuario = {
            "name": str(nome).strip(),
            "registration": int(str(matricula).strip()),
            "password": senha or "",
            "admin": admin
        }

        if templates:
            usuario["templates"] = templates

        if codigo is not None:
            usuario["code"] = codigo

        if rfid is not None:
            usuario["rfid"] = rfid

        if bars is not None:
            usuario["bars"] = bars

        # ====================================================
        # PORTARIA 671
        # ====================================================

        if mode == 671:

            if not cpf:
                raise ValueError(
                    "CPF é obrigatório no modo Portaria 671."
                )

            # Remove pontos, traços, espaços etc.
            cpf_limpo = "".join(
                c for c in str(cpf).strip()
                if c.isdigit()
            )

            if len(cpf_limpo) != 11:
                raise ValueError(
                    "CPF inválido para Portaria 671: "
                    "informe 11 dígitos."
                )

            usuario["cpf"] = int(cpf_limpo)

        # ====================================================
        # LAYOUT LEGADO
        # ====================================================

        else:

            if not pis:
                raise ValueError(
                    "PIS é obrigatório no modo Legado."
                )

            pis_limpo = "".join(
                c for c in str(pis)
                if c.isdigit()
            )

            if not pis_limpo:
                raise ValueError(
                    f"PIS inválido: {pis}"
                )

            usuario["pis"] = int(pis_limpo)

        return self.add_users(
            users=[usuario],
            mode=mode
        )
    
    def atualizar_usuario(
        self,
        nome,
        matricula,
        senha="",
        cpf=None,
        pis=None,
        codigo=None,
        rfid=None,
        bars=None,
        admin=False,
        templates=None,
        mode=671
    ):

        usuario = {
            "name": str(nome).strip(),
            "registration": int(str(matricula).strip()),
            "admin": admin
        }

        if templates:
            usuario["templates"] = templates

        if senha:
            usuario["password"] = senha

        if codigo is not None:
            usuario["code"] = codigo

        if rfid is not None:
            usuario["rfid"] = rfid

        if bars is not None:
            usuario["bars"] = bars

        # ========================================================
        # PORTARIA 671
        # ========================================================

        if mode == 671:

            if not cpf:
                raise ValueError(
                    "CPF é obrigatório no modo Portaria 671."
                )

            cpf_limpo = "".join(
                c for c in str(cpf).strip()
                if c.isdigit()
            )

            if len(cpf_limpo) != 11:
                raise ValueError(
                    "CPF inválido para Portaria 671: "
                    "informe 11 dígitos."
                )

            # CPF identifica o usuário EXISTENTE
            usuario["cpf"] = int(cpf_limpo)

        # ========================================================
        # LAYOUT LEGADO
        # ========================================================

        else:

            if not pis:
                raise ValueError(
                    "PIS é obrigatório no modo Legado."
                )

            pis_limpo = "".join(
                c for c in str(pis)
                if c.isdigit()
            )

            if not pis_limpo:
                raise ValueError(
                    f"PIS inválido: {pis}"
                )

            # PIS identifica o usuário EXISTENTE
            usuario["pis"] = int(pis_limpo)

        # ========================================================
        # UPDATE
        # ========================================================

        return self.update_users(
            users=[usuario],
            mode=mode
        )

    def sincronizar_usuario(
        self,
        nome,
        matricula,
        senha="",
        cpf=None,
        pis=None,
        codigo=None,
        rfid=None,
        bars=None,
        admin=False,
        templates=None,
        mode=671
    ):

        usuario_existente = self.get_user_by_registration(
            matricula,
            mode=mode
        )

        if usuario_existente:

            print(
                f"Usuário {matricula} encontrado no relógio. "
                "Atualizando..."
            )

            return self.atualizar_usuario(
                nome=nome,
                matricula=matricula,
                senha=senha,
                cpf=cpf,
                pis=pis,
                codigo=codigo,
                rfid=rfid,
                bars=bars,
                admin=admin,
                templates=templates,
                mode=mode
            )

        print(
            f"Usuário {matricula} não encontrado no relógio. "
            "Cadastrando..."
        )

        return self.cadastrar_usuario(
            nome=nome,
            matricula=matricula,
            senha=senha,
            cpf=cpf,
            pis=pis,
            codigo=codigo,
            rfid=rfid,
            bars=bars,
            admin=admin,
            templates=templates,
            mode=mode
        )
    
    def excluir_usuario(
        self,
        matricula,
        cpf=None,
        pis=None,
        mode=671
    ):

        # ========================================================
        # LOCALIZAR USUÁRIO NO RELÓGIO
        # ========================================================

        usuario = self.get_user_by_registration(
            matricula
        )

        if not usuario:

            return {
                "success": False,
                "encontrado": False,
                "mensagem": (
                    f"Usuário {matricula} "
                    "não encontrado no relógio."
                )
            }

        # ========================================================
        # DEFINIR CPF / PIS
        # ========================================================

        if mode == 671:

            if not cpf:
                raise ValueError(
                    "CPF é obrigatório no modo Portaria 671."
                )

            cpf_limpo = "".join(
                c for c in str(cpf)
                if c.isdigit()
            )

            if len(cpf_limpo) != 11:
                raise ValueError(
                    f"CPF inválido para Portaria 671: {cpf}"
                )

            identificador = int(cpf_limpo)

        else:

            if not pis:
                raise ValueError(
                    "PIS é obrigatório no modo Legado."
                )

            pis_limpo = "".join(
                c for c in str(pis)
                if c.isdigit()
            )

            if not pis_limpo:
                raise ValueError(
                    f"PIS inválido: {pis}"
                )

            identificador = int(pis_limpo)

        # ========================================================
        # REMOVER DO RELÓGIO
        # ========================================================

        resposta = self.delete_users(
            users=[
                identificador
            ],
            mode=mode
        )

        return {
            "success": True,
            "encontrado": True,
            "mensagem": "Usuário excluído do relógio.",
            "resposta": resposta
        }