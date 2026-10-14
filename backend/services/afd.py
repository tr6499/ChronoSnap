import os
from datetime import datetime


class AFDMixin:

    # ============================================================
    # GET AFD
    # ============================================================

    def get_afd(
        self,
        data_inicial=None,
        data_final=None,
        mode=None
    ):

        if not self.session:
            self.login_device()

        payload = {}

        if data_inicial:
            payload["initial_date"] = {
                "day": data_inicial.day,
                "month": data_inicial.month,
                "year": data_inicial.year
            }

        if data_final:
            payload["final_date"] = {
                "day": data_final.day,
                "month": data_final.month,
                "year": data_final.year
            }

        params = {}

        # --------------------------------------------------------
        # MODO 671
        # --------------------------------------------------------

        if mode == 671:
            params["mode"] = 671

        return self.call(
            "get_afd",
            payload=payload,
            params=params,
            timeout=120,
            binary=True
        )

    # ============================================================
    # DOWNLOAD AFD
    # ============================================================

    def download_afd(
        self,
        output_dir="downloads",
        data_inicial=None,
        data_final=None,
        mode=None
    ):

        conteudo = self.get_afd(
            data_inicial=data_inicial,
            data_final=data_final,
            mode=mode
        )

        os.makedirs(
            output_dir,
            exist_ok=True
        )

        # --------------------------------------------------------
        # MONTA NOME DO ARQUIVO
        # --------------------------------------------------------

        if data_inicial:

            nome = (
                f"AFD_"
                f"{data_inicial.strftime('%Y%m%d')}"
            )

            if data_final:
                nome += (
                    f"_"
                    f"{data_final.strftime('%Y%m%d')}"
                )

            if mode == 671:
                nome += "_671"

            nome += ".txt"

        else:

            nome = (
                f"AFD_"
                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            )

            if mode == 671:
                nome += "_671"

            nome += ".txt"

        caminho = os.path.join(
            output_dir,
            nome
        )

        # --------------------------------------------------------
        # SALVA BYTE A BYTE
        # --------------------------------------------------------

        with open(
            caminho,
            "wb"
        ) as f:

            f.write(conteudo)

        return {
            "filename": nome,
            "path": caminho,
            "size": len(conteudo)
        }

    # ============================================================
    # PARSE AFD ORIGINAL
    # ============================================================

    def parse_afd(
        self,
        data
    ):

        if not data:
            raise ValueError(
                "O equipamento retornou um AFD vazio."
            )

        # --------------------------------------------------------
        # O retorno do Control iD possui:
        #
        # REGISTROS\r\n
        # REGISTROS\r\n
        # REGISTROS\r\n
        # AFD00014003750190649.txt
        #
        # Portanto, o último trecho após o último CRLF
        # corresponde ao nome do arquivo.
        # --------------------------------------------------------

        pos = data.rfind(b"\r\n")

        if pos == -1:
            raise ValueError(
                "Não foi possível localizar o final dos registros."
            )

        # --------------------------------------------------------
        # NOME DO ARQUIVO
        # --------------------------------------------------------

        filename = data[
            pos + 2:
        ].decode(
            "latin1",
            errors="replace"
        ).strip()

        if not filename:
            raise ValueError(
                "Não foi possível localizar o nome do arquivo."
            )

        # --------------------------------------------------------
        # REGISTROS
        # --------------------------------------------------------

        registros = data[
            :pos + 2
        ]

        return {
            "filename": filename,
            "header": b"",
            "registros": registros,
            "raw": data
        }

    # ============================================================
    # SALVAR AFD ORIGINAL
    # ============================================================

    def save_afd(
        self,
        output_dir=".",
        data_inicial=None,
        data_final=None,
        mode=None
    ):

        # --------------------------------------------------------
        # BAIXA O AFD
        # --------------------------------------------------------

        data = self.get_afd(
            data_inicial=data_inicial,
            data_final=data_final,
            mode=mode
        )

        # --------------------------------------------------------
        # INTERPRETA O RETORNO
        # --------------------------------------------------------

        afd = self.parse_afd(
            data
        )

        filename = afd[
            "filename"
        ]

        # --------------------------------------------------------
        # CRIA DIRETÓRIO
        # --------------------------------------------------------

        os.makedirs(
            output_dir,
            exist_ok=True
        )

        path = os.path.join(
            output_dir,
            filename
        )

        # --------------------------------------------------------
        # SALVA SOMENTE OS REGISTROS
        #
        # O nome AFDxxxx.txt retornado pelo equipamento
        # NÃO será colocado dentro do arquivo.
        # --------------------------------------------------------

        with open(
            path,
            "wb"
        ) as f:

            f.write(
                afd["registros"]
            )

        return {
            "filename": filename,
            "path": path,
            "size": len(afd["registros"])
        }