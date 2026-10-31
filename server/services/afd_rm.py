from datetime import datetime, date, timedelta

from services.idclass import IDClass
from services.espelho import EspelhoAFD
from database import SessionLocal
from models import Loja, MarcacaoAFD
from models_usuarios import ConfiguracaoSistema
import json


class AFDRM:

    def __init__(self):

        # Lista final de linhas RM TOTVS
        self.registros = []
        self.layout = {
            "nsr_largura": 10,
            "data_formato": "%d%m%Y",
            "hora_formato": "%H%M",
            "identificador_largura": 12,
            "preenchimento": "0",
            "separador": ""
        }
        db = SessionLocal()
        try:
            configuracao = db.query(ConfiguracaoSistema).filter(
                ConfiguracaoSistema.chave == "layout_rm_totvs"
            ).first()
            if configuracao:
                self.layout.update(json.loads(configuracao.valor or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        finally:
            db.close()

    def adicionar_marcacoes_banco(self, marcacoes):
        quantidade = 0
        for marcacao in marcacoes:
            registro = self.formatar_marcacao({
                "nsr": marcacao.nsr,
                "tipo": marcacao.tipo,
                "data_hora": self._data_hora_marcacao(marcacao),
                "identificador": marcacao.identificador,
            }, marcacao.layout)
            if registro:
                self.registros.append(registro)
                quantidade += 1
        return quantidade

    @staticmethod
    def _data_hora_marcacao(marcacao):
        if marcacao.raw:
            processador = EspelhoAFD(layout=marcacao.layout)
            registro_original = processador._ler_marcacao(
                marcacao.raw,
                processador.layout
            )
            if registro_original:
                return registro_original["data_hora"]

        return marcacao.data_hora

    @staticmethod
    def _cpf_valido(cpf):
        if len(cpf) != 11 or len(set(cpf)) == 1:
            return False

        primeiro = sum(
            int(digito) * peso
            for digito, peso in zip(cpf[:9], range(10, 1, -1))
        )
        digito_1 = (primeiro * 10) % 11
        if digito_1 == 10:
            digito_1 = 0

        if digito_1 != int(cpf[9]):
            return False

        segundo = sum(
            int(digito) * peso
            for digito, peso in zip(cpf[:10], range(11, 1, -1))
        )
        digito_2 = (segundo * 10) % 11
        if digito_2 == 10:
            digito_2 = 0

        return digito_2 == int(cpf[10])

    @staticmethod
    def _pis_valido(pis):
        if len(pis) != 11:
            return False

        pesos = (3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
        soma = sum(
            int(digito) * peso
            for digito, peso in zip(pis[:10], pesos)
        )
        resto = 11 - (soma % 11)
        digito = 0 if resto in (10, 11) else resto
        return digito == int(pis[10])

    @classmethod
    def _identificador_rm(cls, identificador):
        numeros = "".join(
            caractere
            for caractere in str(identificador or "")
            if caractere.isdigit()
        )

        if not numeros or len(numeros) > 12:
            return None

        numeros = numeros.zfill(12)

        # O REP legado pode enviar 0 + CPF bruto. O RM adaptado
        # exige 9 + CPF; PIS continua como 0 + PIS.
        if numeros[0] == "0":
            documento = numeros[1:]
            if cls._cpf_valido(documento):
                return "9" + documento
            if cls._pis_valido(documento):
                return numeros

        # Prefixos 8 e 9 são convenções próprias do REP/RM e
        # devem ser preservados exatamente como vieram do relógio.
        return numeros

    # ============================================================
    # GERAR UMA MARCAÇÃO NO FORMATO RM TOTVS
    # ============================================================

    def formatar_marcacao(
        self,
        marcacao,
        layout
    ):

        # --------------------------------------------------------
        # NSR
        # --------------------------------------------------------

        nsr = str(
            marcacao.get("nsr") or ""
        ).strip()

        if not nsr:
            return None

        # Alguns AFDs fornecem o tipo de registro separadamente
        # (campo `tipo`). O layout RM espera 10 posições que
        # normalmente correspondem a NSR (9) + tipo (1). Quando o
        # `tipo` estiver presente, concatena-se para formar as 10
        # posições; caso contrário, preenche à esquerda para 10.
        tipo = str(
            marcacao.get("tipo") or ""
        ).strip()

        if tipo:
            nsr = (nsr + tipo)

        # Garantir exatamente 10 posições (completando à esquerda
        # quando menor ou truncando quando maior).
        nsr_largura = int(self.layout.get("nsr_largura", 10))
        if len(nsr) < nsr_largura:
            nsr = nsr.zfill(nsr_largura)
        else:
            nsr = nsr[:nsr_largura]

        # --------------------------------------------------------
        # DATA / HORA
        # --------------------------------------------------------

        data_hora = (
            marcacao.get("data_hora")
        )

        if not data_hora:
            return None

        data = data_hora.strftime(self.layout.get("data_formato", "%d%m%Y"))

        hora = data_hora.strftime(self.layout.get("hora_formato", "%H%M"))

        # --------------------------------------------------------
        # IDENTIFICADOR RM (PIS ou CPF adaptado)
        # --------------------------------------------------------

        identificador = str(
            marcacao.get("identificador")
            or ""
        ).strip()

        if not identificador:
            return None

        identificador = self._identificador_rm(identificador)

        if not identificador:
            return None

        # --------------------------------------------------------
        # MONTA REGISTRO
        # --------------------------------------------------------

        largura_identificador = int(self.layout.get("identificador_largura", 12))
        preenchimento = self.layout.get("preenchimento", "0") or "0"
        identificador = identificador[:largura_identificador].rjust(largura_identificador, preenchimento[0])
        separador = self.layout.get("separador", "")
        registro = (
            nsr
            + separador
            + data
            + separador
            + hora
            + separador
            + identificador
        )

        return registro

    def _chave_ordenacao_rm(
        self,
        registro
    ):

        try:

            data_hora = datetime.strptime(
                registro[10:22],
                "%d%m%Y%H%M"
            )

        except (TypeError, ValueError):

            data_hora = datetime.max

        return (
            data_hora,
            registro[:10]
        )

    # ============================================================
    # ADICIONAR UMA LOJA
    # ============================================================

    def adicionar_loja(
        self,
        ip,
        usuario,
        senha,
        data_inicial=None,
        data_final=None,
        afd_layout="legado",
        loja_id=None
    ):

        equipamento = IDClass(
            ip,
            username=usuario or "admin",
            password=senha or "7070"
        )

        print(
            f"Conectando no equipamento "
            f"{ip}..."
        )

        equipamento.login_device()

        try:
            # Define a captura e a leitura pelo layout configurado da loja.
            layout_configurado = str(afd_layout or "legado").strip().lower()
            if layout_configurado in ("671", "portaria671"):
                mode = 671
                layout = EspelhoAFD.LAYOUT_671
            else:
                mode = None
                layout = EspelhoAFD.LAYOUT_LEGADO

            # --------------------------------------------------------
            # BAIXA O AFD
            # --------------------------------------------------------

            afd = equipamento.get_afd(

                data_inicial=data_inicial,

                data_final=data_final,

                mode=mode

            )

            if not afd:

                raise Exception(
                    "O relógio não retornou "
                    "dados de AFD."
                )

            # --------------------------------------------------------
            # PROCESSA O AFD
            # --------------------------------------------------------

            espelho = EspelhoAFD(
                layout=layout
            )

            resultado = espelho.processar(

                afd,

                layout=layout,

                data_inicial=data_inicial,

                data_final=data_final

            )

            # MARCAÇÕES
            # --------------------------------------------------------

            marcacoes = resultado.get(
                "marcacoes",
                []
            )

            print(
                f"Loja processada: "
                f"{len(marcacoes)} marcações"
            )

            # --------------------------------------------------------
            # CONVERTE PARA RM TOTVS
            # --------------------------------------------------------

            quantidade = 0

            for marcacao in marcacoes:

                registro = self.formatar_marcacao(

                    marcacao,

                    layout

                )

                if not registro:
                    continue

                self.registros.append(
                    registro
                )

                quantidade += 1

            print(
                f"RM TOTVS: "
                f"{quantidade} registros adicionados."
            )
        finally:
            equipamento.logout()

    # ============================================================
    # SALVAR
    # ============================================================

    def salvar(
        self,
        arquivo
    ):

        with open(
            arquivo,
            "w",
            encoding="ascii",
            newline=""
        ) as f:

            for registro in self.registros:

                f.write(
                    registro
                    + "\r\n"
                )

        return arquivo

    # ============================================================
    # AFD PORTARIA 671 CONSOLIDADO
    # ============================================================

    def _formatar_data_671(
        self,
        data_hora
    ):

        return data_hora.strftime(
            "%Y-%m-%dT%H:%M:%S"
        ).ljust(24)

    def _formatar_identificador_671(
        self,
        identificador
    ):

        identificador = "".join(
            caractere
            for caractere in str(
                identificador or ""
            )
            if caractere.isdigit()
        )

        if not identificador:
            return None

        return identificador[-12:].zfill(12)

    def _formatar_registro_671(
        self,
        nsr,
        tipo,
        data_hora,
        identificador,
        tipo_identificador="1",
        nome=""
    ):

        if not data_hora:
            return None

        identificador = self._formatar_identificador_671(
            identificador
        )

        if not identificador:
            return None

        registro = (
            f"{nsr:09d}"
            f"{tipo}"
            f"{self._formatar_data_671(data_hora)}"
        )

        if tipo == "5":
            return (
                registro
                + tipo_identificador
                + identificador
                + str(nome or "").strip()
            )

        return (
            registro
            + identificador
            + "0000"
        )

    def gerar_671_por_lojas(
        self,
        numeros_lojas,
        data_inicial,
        data_final
    ):

        registros = []
        db = SessionLocal()

        try:

            lojas = (
                db.query(Loja)
                .filter(
                    Loja.numero.in_(
                        numeros_lojas
                    )
                )
                .order_by(
                    Loja.numero
                )
                .all()
            )

            for loja in lojas:

                equipamento = IDClass(
                    loja.ip,
                    username=loja.usuario or "admin",
                    password=loja.senha or "7070"
                )

                equipamento.login_device()

                try:
                    # A conversão sempre parte da extração legada,
                    # independentemente do layout registrado na loja.
                    afd = equipamento.get_afd(
                        data_inicial=data_inicial,
                        data_final=data_final,
                        mode=None
                    )

                    resultado = EspelhoAFD(
                        layout="legado"
                    ).processar(
                        afd,
                        layout="legado",
                        data_inicial=data_inicial,
                        data_final=data_final
                    )

                    for funcionario in resultado.get(
                        "funcionarios",
                        []
                    ):

                        data_cadastro = funcionario.get(
                            "data_hora_cadastro"
                        )

                        if not data_cadastro:
                            marcacoes = funcionario.get(
                                "marcacoes",
                                []
                            )
                            data_cadastro = (
                                marcacoes[0].get("data_hora")
                                if marcacoes else None
                            )

                        registros.append({
                            "tipo": "5",
                            "data_hora": data_cadastro,
                            "identificador": funcionario.get(
                                "identificador"
                            ),
                            "nome": funcionario.get("nome")
                        })

                    for marcacao in resultado.get(
                        "marcacoes",
                        []
                    ):

                        registros.append({
                            "tipo": "3",
                            "data_hora": marcacao.get("data_hora"),
                            "identificador": marcacao.get(
                                "identificador"
                            ),
                            "nome": ""
                        })
                finally:
                    equipamento.logout()

        finally:

            db.close()

        registros.sort(
            key=lambda registro: (
                registro.get("data_hora"),
                registro.get("tipo")
            )
        )

        self.registros = []

        for nsr, registro in enumerate(
            registros,
            start=1
        ):

            linha = self._formatar_registro_671(
                nsr=nsr,
                tipo=registro["tipo"],
                data_hora=registro["data_hora"],
                identificador=registro["identificador"],
                nome=registro["nome"]
            )

            if linha:
                self.registros.append(linha)

        return len(self.registros)

    # ============================================================
    # GERAR POR LOJAS
    # ============================================================

    def gerar_por_lojas(
        self,
        numeros_lojas,
        data_inicial,
        data_final
    ):

        data_inicial = (
            data_inicial.date()
            if isinstance(data_inicial, datetime)
            else data_inicial
        )
        data_final = (
            data_final.date()
            if isinstance(data_final, datetime)
            else data_final
        )

        db = SessionLocal()

        try:

            lojas = (
                db.query(Loja)
                .filter(
                    Loja.numero.in_(
                        numeros_lojas
                    )
                )
                .order_by(
                    Loja.numero
                )
                .all()
            )

            for loja in lojas:

                print(
                    "================================================"
                )

                print(
                    f"Baixando Loja "
                    f"{loja.numero} - "
                    f"{loja.nome} - "
                    f"Layout: {loja.afd_layout or 'legado'}"
                )

                try:
                    data_ini = datetime.combine(
                        data_inicial - timedelta(days=1),
                        datetime.min.time()
                    )
                    data_fim = datetime.combine(
                        data_final + timedelta(days=2),
                        datetime.min.time()
                    )
                    marcacoes_candidatas = (
                        db.query(MarcacaoAFD)
                        .filter(
                            MarcacaoAFD.loja_id == loja.id,
                            MarcacaoAFD.data_hora >= data_ini,
                            MarcacaoAFD.data_hora < data_fim
                        )
                        .order_by(MarcacaoAFD.data_hora, MarcacaoAFD.id)
                        .all()
                    )
                    marcacoes = [
                        marcacao
                        for marcacao in marcacoes_candidatas
                        if data_inicial
                        <= self._data_hora_marcacao(marcacao).date()
                        <= data_final
                    ]

                    if marcacoes:
                        quantidade = self.adicionar_marcacoes_banco(marcacoes)
                        print(f"RM banco: {quantidade} registros adicionados.")
                    else:
                        print(
                            f"RM banco: nenhuma marcação carregada para "
                            f"a loja {loja.numero} no período."
                        )

                except Exception as erro:

                    print(
                        f"ERRO Loja "
                        f"{loja.numero}: "
                        f"{erro}"
                    )

                    # Continua para a próxima loja
                    continue

            self.registros.sort(
                key=self._chave_ordenacao_rm
            )

        finally:

            db.close()