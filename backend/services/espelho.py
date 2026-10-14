from collections import defaultdict
from datetime import datetime, date


class EspelhoAFD:
    """
    Processador de AFD do Control iD / iDClass.

    Suporta:

    - LEGADO / Portaria 595
    - Portaria 671

    O processamento trabalha com registros:

    Tipo 5 = funcionário
    Tipo 3 = marcação

    IMPORTANTE:
    - O período é filtrado por data.
    - Datas com timezone e sem timezone são aceitas.
    - Funcionários sem marcações não entram no espelho.
    - Caso exista uma marcação sem cadastro Tipo 5,
      o funcionário é criado pelo identificador.
    """

    LAYOUT_LEGADO = "legado"
    LAYOUT_671 = 671

    # ============================================================
    # INICIALIZAÇÃO
    # ============================================================

    def __init__(self, layout=None):

        if layout is not None:
            layout = self._normalizar_layout(layout)

        self.layout = layout

    # ============================================================
    # NORMALIZA LAYOUT
    # ============================================================

    def _normalizar_layout(self, layout):

        if isinstance(layout, str):

            valor = layout.strip().lower()

            if valor in (
                "legado",
                "595",
                "portaria595",
            ):
                return self.LAYOUT_LEGADO

            if valor in (
                "671",
                "portaria671",
            ):
                return self.LAYOUT_671

        elif isinstance(layout, int):

            if layout == 671:
                return self.LAYOUT_671

        raise ValueError(
            "Layout inválido. Use 'legado' ou 671."
        )

    # ============================================================
    # PROCESSAMENTO PRINCIPAL
    # ============================================================

    def processar(
        self,
        afd,
        layout=None,
        data_inicial=None,
        data_final=None
    ):

        if not afd:
            raise ValueError(
                "O AFD recebido está vazio."
            )

        # --------------------------------------------------------
        # Aceita bytes ou string
        # --------------------------------------------------------

        if isinstance(afd, str):

            afd = afd.encode(
                "iso-8859-1",
                errors="replace"
            )

        if not isinstance(afd, bytes):

            raise TypeError(
                "O AFD deve ser bytes ou string."
            )

        linhas = afd.splitlines()

        if not linhas:

            raise ValueError(
                "O AFD não possui registros."
            )

        # --------------------------------------------------------
        # Datas
        # --------------------------------------------------------

        data_ini = self._normalizar_data_limite(
            data_inicial
        )

        data_fim = self._normalizar_data_limite(
            data_final
        )

        if data_ini and data_fim:

            if data_ini > data_fim:

                raise ValueError(
                    "A data inicial não pode ser maior "
                    "que a data final."
                )

        # --------------------------------------------------------
        # Layout
        # --------------------------------------------------------

        layout = self._detectar_layout(
            linhas,
            layout
        )

        # ========================================================
        # FUNCIONÁRIOS
        # ========================================================

        funcionarios = {}

        registros_funcionarios = defaultdict(list)

        # ========================================================
        # PRIMEIRA PASSAGEM
        # REGISTROS TIPO 5
        # ========================================================

        for linha in linhas:

            tipo = self._tipo_registro(linha)

            if tipo != "5":
                continue

            funcionario = self._ler_funcionario(
                linha,
                layout
            )

            if not funcionario:
                continue

            identificador = funcionario.get(
                "identificador"
            )

            if not identificador:
                continue

            registros_funcionarios[
                identificador
            ].append(
                funcionario
            )

        # --------------------------------------------------------
        # Consolida cadastros
        # --------------------------------------------------------

        for identificador, registros in (
            registros_funcionarios.items()
        ):

            funcionario = (
                self._consolidar_funcionario(
                    registros
                )
            )

            if funcionario:

                funcionarios[
                    identificador
                ] = funcionario

        # ========================================================
        # MARCAÇÕES
        # ========================================================

        marcacoes = []

        marcacoes_por_funcionario = defaultdict(list)

        # ========================================================
        # SEGUNDA PASSAGEM
        # REGISTROS TIPO 3
        # ========================================================

        for linha in linhas:

            tipo = self._tipo_registro(linha)

            if tipo != "3":
                continue

            marcacao = self._ler_marcacao(
                linha,
                layout
            )

            if not marcacao:
                continue

            data_marcacao = (
                marcacao.get("data_hora")
            )

            # ----------------------------------------------------
            # Filtra período
            # ----------------------------------------------------

            if not self._dentro_periodo(
                data_marcacao,
                data_ini,
                data_fim
            ):
                continue

            identificador = marcacao.get(
                "identificador"
            )

            if not identificador:
                continue

            marcacoes.append(
                marcacao
            )

            marcacoes_por_funcionario[
                identificador
            ].append(
                marcacao
            )

        # ========================================================
        # CRIA FUNCIONÁRIOS QUE NÃO POSSUEM TIPO 5
        # ========================================================

        for identificador, lista_marcacoes in (
            marcacoes_por_funcionario.items()
        ):

            if identificador in funcionarios:
                continue

            if not lista_marcacoes:
                continue

            primeira = lista_marcacoes[0]

            if layout == self.LAYOUT_671:

                funcionario = {
                    "nsr": None,
                    "tipo": "5",
                    "data_hora_cadastro": None,
                    "data_hora_texto": None,
                    "tipo_identificador": None,

                    "identificador":
                        identificador,

                    "pis":
                        None,

                    "cpf":
                        identificador,

                    "nome":
                        "Funcionário não cadastrado",

                    "layout":
                        self.LAYOUT_671,

                    "raw":
                        None,

                    "registros_tipo_5":
                        0,

                    "historico":
                        []
                }

            else:

                funcionario = {
                    "nsr": None,
                    "tipo": "5",
                    "data_hora_cadastro": None,
                    "data_hora_texto": None,
                    "tipo_identificador": None,

                    "identificador":
                        identificador,

                    "pis":
                        identificador,

                    "cpf":
                        None,

                    "nome":
                        "Funcionário não cadastrado",

                    "layout":
                        self.LAYOUT_LEGADO,

                    "raw":
                        None,

                    "registros_tipo_5":
                        0,

                    "historico":
                        []
                }

            funcionarios[
                identificador
            ] = funcionario

        # ========================================================
        # MONTA FUNCIONÁRIOS
        # ========================================================

        resultado_funcionarios = []

        for identificador, funcionario in (
            funcionarios.items()
        ):

            lista_marcacoes = (
                marcacoes_por_funcionario.get(
                    identificador,
                    []
                )
            )

            # ----------------------------------------------------
            # NÃO EXIBE FUNCIONÁRIO SEM MARCAÇÃO
            # ----------------------------------------------------

            if not lista_marcacoes:
                continue

            # ----------------------------------------------------
            # Ordenação
            # ----------------------------------------------------

            lista_marcacoes.sort(
                key=lambda item: (
                    self._data_ordenacao(
                        item.get("data_hora")
                    )
                )
            )

            funcionario_final = dict(
                funcionario
            )

            funcionario_final[
                "marcacoes"
            ] = lista_marcacoes

            funcionario_final[
                "total_marcacoes"
            ] = len(
                lista_marcacoes
            )

            # ----------------------------------------------------
            # Para Portaria 671, o espelho apresenta CPF.
            # ----------------------------------------------------

            if layout == self.LAYOUT_671:

                funcionario_final[
                    "cpf"
                ] = funcionario_final.get(
                    "identificador"
                )

                funcionario_final[
                    "pis"
                ] = None

            resultado_funcionarios.append(
                funcionario_final
            )

        # ========================================================
        # ORDENA FUNCIONÁRIOS
        # ========================================================

        resultado_funcionarios.sort(
            key=lambda item: (
                item.get("nome") or ""
            ).upper()
        )

        # ========================================================
        # RESULTADO
        # ========================================================

        return {

            "layout":
                layout,

            "funcionarios":
                resultado_funcionarios,

            "marcacoes":
                marcacoes,

            "total_funcionarios":
                len(
                    resultado_funcionarios
                ),

            "total_marcacoes":
                len(
                    marcacoes
                ),

            "data_inicial":
                data_ini,

            "data_final":
                data_fim,
        }

    # ============================================================
    # DETECÇÃO AUTOMÁTICA
    # ============================================================

    def _detectar_layout(
        self,
        linhas,
        layout=None
    ):

        if layout is not None:

            return self._normalizar_layout(
                layout
            )

        if self.layout is not None:

            return self.layout

        # --------------------------------------------------------
        # Procura registro Tipo 3 com data ISO
        # --------------------------------------------------------

        for linha in linhas:

            if self._tipo_registro(linha) != "3":
                continue

            texto = self._texto(linha)

            if len(texto) < 34:
                continue

            data_hora = texto[
                10:34
            ]

            if self._is_data_iso(
                data_hora
            ):
                return self.LAYOUT_671

        return self.LAYOUT_LEGADO

    # ============================================================
    # TIPO DO REGISTRO
    # ============================================================

    def _tipo_registro(
        self,
        linha
    ):

        if not linha:
            return None

        if len(linha) < 10:
            return None

        if isinstance(linha, bytes):

            try:

                return chr(
                    linha[9]
                )

            except Exception:

                return None

        return linha[9]

    # ============================================================
    # TEXTO
    # ============================================================

    def _texto(
        self,
        linha
    ):

        if isinstance(linha, str):

            return linha.rstrip(
                "\r\n"
            )

        return linha.decode(
            "iso-8859-1",
            errors="replace"
        ).rstrip(
            "\r\n"
        )

    # ============================================================
    # FUNCIONÁRIO
    # ============================================================

    def _ler_funcionario(
        self,
        linha,
        layout
    ):

        texto = self._texto(
            linha
        )

        if layout == self.LAYOUT_671:

            return self._ler_funcionario_671(
                texto
            )

        return self._ler_funcionario_legado(
            texto
        )

    # ============================================================
    # FUNCIONÁRIO 671
    # ============================================================

    def _ler_funcionario_671(
        self,
        texto
    ):

        try:

            if len(texto) < 47:
                return None

            nsr = texto[
                0:9
            ]

            tipo = texto[
                9:10
            ]

            data_hora_texto = texto[
                10:34
            ]

            tipo_identificador = texto[
                34:35
            ]

            identificador = texto[
                35:47
            ].strip()

            # ----------------------------------------------------
            # Nome ocupa o restante do registro.
            # ----------------------------------------------------

            nome = texto[
                47:
            ].strip()

            if not identificador:
                return None

            if not self._somente_digitos(
                identificador
            ):
                return None

            return {

                "nsr":
                    nsr,

                "tipo":
                    tipo,

                "data_hora_cadastro":
                    self._parse_data(
                        data_hora_texto
                    ),

                "data_hora_texto":
                    data_hora_texto,

                "tipo_identificador":
                    tipo_identificador,

                "identificador":
                    identificador,

                # ------------------------------------------------
                # 671 será apresentado como CPF.
                # ------------------------------------------------

                "cpf":
                    identificador,

                "pis":
                    None,

                "nome":
                    nome,

                "layout":
                    self.LAYOUT_671,

                "raw":
                    texto
            }

        except Exception:

            return None

    # ============================================================
    # FUNCIONÁRIO LEGADO
    # ============================================================

    def _ler_funcionario_legado(
        self,
        texto
    ):

        try:

            if len(texto) < 35:
                return None

            nsr = texto[
                0:9
            ]

            tipo = texto[
                9:10
            ]

            data_hora_texto = texto[
                10:22
            ]

            tipo_identificador = texto[
                22:23
            ]

            identificador = texto[
                23:35
            ].strip()

            nome = texto[
                35:87
            ].strip()

            if not identificador:
                return None

            if not self._somente_digitos(
                identificador
            ):
                return None

            return {

                "nsr":
                    nsr,

                "tipo":
                    tipo,

                "data_hora_cadastro":
                    self._parse_data_legado(
                        data_hora_texto
                    ),

                "data_hora_texto":
                    data_hora_texto,

                "tipo_identificador":
                    tipo_identificador,

                "identificador":
                    identificador,

                "pis":
                    identificador,

                "cpf":
                    None,

                "nome":
                    nome,

                "layout":
                    self.LAYOUT_LEGADO,

                "raw":
                    texto
            }

        except Exception:

            return None

    # ============================================================
    # MARCAÇÃO
    # ============================================================

    def _ler_marcacao(
        self,
        linha,
        layout
    ):

        texto = self._texto(
            linha
        )

        if layout == self.LAYOUT_671:

            return self._ler_marcacao_671(
                texto
            )

        return self._ler_marcacao_legado(
            texto
        )

    # ============================================================
    # MARCAÇÃO 671
    # ============================================================

    def _ler_marcacao_671(
        self,
        texto
    ):

        try:

            if len(texto) < 46:
                return None

            nsr = texto[
                0:9
            ]

            tipo = texto[
                9:10
            ]

            data_hora_texto = texto[
                10:34
            ]

            identificador = texto[
                34:46
            ].strip()

            crc = ""

            if len(texto) >= 50:

                crc = texto[
                    46:50
                ].strip()

            if not self._is_data_iso(
                data_hora_texto
            ):
                return None

            if not self._somente_digitos(
                identificador
            ):
                return None

            data_hora = self._parse_data(
                data_hora_texto
            )

            if not data_hora:
                return None

            return {

                "nsr":
                    nsr,

                "tipo":
                    tipo,

                "data_hora":
                    data_hora,

                "data_hora_texto":
                    data_hora_texto,

                "identificador":
                    identificador,

                "cpf":
                    identificador,

                "pis":
                    None,

                "crc":
                    crc,

                "layout":
                    self.LAYOUT_671,

                "raw":
                    texto
            }

        except Exception:

            return None

    # ============================================================
    # MARCAÇÃO LEGADO
    # ============================================================

    def _ler_marcacao_legado(
        self,
        texto
    ):

        try:

            if len(texto) < 38:
                return None

            nsr = texto[
                0:9
            ]

            tipo = texto[
                9:10
            ]

            data_hora_texto = texto[
                10:22
            ]

            identificador = texto[
                22:34
            ].strip()

            crc = texto[
                34:38
            ].strip()

            data_hora = (
                self._parse_data_legado(
                    data_hora_texto
                )
            )

            if not data_hora:
                return None

            if not self._somente_digitos(
                identificador
            ):
                return None

            return {

                "nsr":
                    nsr,

                "tipo":
                    tipo,

                "data_hora":
                    data_hora,

                "data_hora_texto":
                    data_hora_texto,

                "identificador":
                    identificador,

                "pis":
                    identificador,

                "cpf":
                    None,

                "crc":
                    crc,

                "layout":
                    self.LAYOUT_LEGADO,

                "raw":
                    texto
            }

        except Exception:

            return None

    # ============================================================
    # CONSOLIDA FUNCIONÁRIO
    # ============================================================

    def _consolidar_funcionario(
        self,
        registros
    ):

        if not registros:
            return None

        registros_ordenados = sorted(
            registros,
            key=lambda item: (
                self._data_ordenacao(
                    item.get(
                        "data_hora_cadastro"
                    )
                )
            )
        )

        funcionario = dict(
            registros_ordenados[-1]
        )

        funcionario[
            "registros_tipo_5"
        ] = len(
            registros
        )

        funcionario[
            "historico"
        ] = registros_ordenados

        return funcionario

    # ============================================================
    # DATA 671
    # ============================================================

    def _parse_data(
        self,
        valor
    ):

        if not valor:
            return None

        valor = valor.strip()

        formatos = (

            "%Y-%m-%dT%H:%M:%S%z",

            "%Y-%m-%dT%H:%M:%S",

            "%Y-%m-%d %H:%M:%S",

        )

        for formato in formatos:

            try:

                return datetime.strptime(
                    valor,
                    formato
                )

            except ValueError:

                continue

        return None

    # ============================================================
    # DATA LEGADO
    # ============================================================

    def _parse_data_legado(
        self,
        valor
    ):

        if not valor:
            return None

        valor = valor.strip()

        formatos = (

            "%d%m%Y%H%M",

            "%d%m%Y%H%M%S",

        )

        for formato in formatos:

            try:

                return datetime.strptime(
                    valor,
                    formato
                )

            except ValueError:

                continue

        return None

    # ============================================================
    # NORMALIZA DATA LIMITE
    # ============================================================

    def _normalizar_data_limite(
        self,
        valor
    ):

        if valor is None:
            return None

        if isinstance(
            valor,
            datetime
        ):

            return valor.date()

        if isinstance(
            valor,
            date
        ):

            return valor

        if isinstance(
            valor,
            str
        ):

            valor = valor.strip()

            if not valor:
                return None

            formatos = (

                "%Y-%m-%d",

                "%d/%m/%Y",

                "%Y-%m-%dT%H:%M:%S",

                "%Y-%m-%dT%H:%M:%S%z",

            )

            for formato in formatos:

                try:

                    resultado = datetime.strptime(
                        valor,
                        formato
                    )

                    return resultado.date()

                except ValueError:

                    continue

        return None

    # ============================================================
    # VERIFICA PERÍODO
    # ============================================================

    def _dentro_periodo(
        self,
        data_hora,
        data_inicial=None,
        data_final=None
    ):

        if not data_hora:
            return False

        if isinstance(
            data_hora,
            datetime
        ):

            data_registro = (
                data_hora.date()
            )

        elif isinstance(
            data_hora,
            date
        ):

            data_registro = data_hora

        else:

            return False

        if (
            data_inicial
            and
            data_registro < data_inicial
        ):

            return False

        if (
            data_final
            and
            data_registro > data_final
        ):

            return False

        return True

    # ============================================================
    # ORDENAÇÃO SEGURA
    # ============================================================

    def _data_ordenacao(
        self,
        valor
    ):

        if isinstance(
            valor,
            datetime
        ):

            # Remove timezone apenas para ordenação.
            return valor.replace(
                tzinfo=None
            )

        if isinstance(
            valor,
            date
        ):

            return datetime.combine(
                valor,
                datetime.min.time()
            )

        return datetime.min

    # ============================================================
    # DATA ISO
    # ============================================================

    def _is_data_iso(
        self,
        valor
    ):

        if not valor:
            return False

        texto = valor.strip()

        # Aceita:
        #
        # 2026-08-17T15:00:00-0300
        #
        # e
        #
        # 2026-08-17T15:00:00

        if len(texto) == 19:

            try:

                datetime.strptime(
                    texto,
                    "%Y-%m-%dT%H:%M:%S"
                )

                return True

            except ValueError:

                return False

        if len(texto) == 24:

            try:

                datetime.strptime(
                    texto,
                    "%Y-%m-%dT%H:%M:%S%z"
                )

                return True

            except ValueError:

                return False

        return False

    # ============================================================
    # SOMENTE DÍGITOS
    # ============================================================

    def _somente_digitos(
        self,
        valor
    ):

        return bool(
            valor
            and
            valor.isdigit()
        )

    # ============================================================
    # COMPATIBILIDADE
    # ============================================================

    def gerar_espelho(
        self,
        afd,
        layout=None,
        data_inicial=None,
        data_final=None
    ):

        return self.processar(
            afd,
            layout=layout,
            data_inicial=data_inicial,
            data_final=data_final
        )