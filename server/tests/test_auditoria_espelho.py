import unittest
import hashlib
import io
import json
import ssl
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from services.auditoria import (
    converter_para_horario_local,
    descrever_acao_auditoria,
    formatar_detalhes_auditoria,
)
from services.atualizacoes import (
    baixar_instalador,
    obter_ultima_release,
    ler_modo_atualizacao,
    salvar_modo_atualizacao,
)
from services.espelho import EspelhoAFD
from routes.afd import _omitir_loja_sem_resultados


class AuditoriaHorarioTests(unittest.TestCase):
    def test_converte_horario_utc_sem_fuso_para_horario_local(self):
        convertido = converter_para_horario_local(
            datetime(2026, 11, 4, 10, 15, 0)
        )

        self.assertEqual(
            convertido.isoformat(),
            "2026-11-04T07:15:00-03:00",
        )

    def test_descreve_consulta_de_espelho_em_linguagem_clara(self):
        self.assertEqual(
            descrever_acao_auditoria("consultou_espelho", "espelho_ponto"),
            "Consultou o espelho de ponto",
        )

    def test_formata_detalhes_sem_exibir_metodo_http(self):
        detalhes = formatar_detalhes_auditoria(
            json.dumps(
                {
                    "metodo": "POST",
                    "data_inicial": "2026-11-01",
                    "total_marcacoes": 12,
                }
            )
        )

        self.assertEqual(
            detalhes,
            [
                ("Data inicial", "2026-11-01"),
                ("Marcações encontradas", "12"),
            ],
        )


class EspelhoFuncionariosComMarcacoesTests(unittest.TestCase):
    def test_omite_funcionario_sem_marcacoes_no_periodo(self):
        data_hora = "2026-11-03T08:00:00-0300"
        funcionario_com_marcacao = "000000000001"
        funcionario_sem_marcacao = "000000000002"
        registros = [
            f"0000000015{data_hora}0{funcionario_com_marcacao}Funcionario com ponto",
            f"0000000025{data_hora}0{funcionario_sem_marcacao}Funcionario sem ponto",
            f"0000000033{data_hora}{funcionario_com_marcacao}",
        ]

        resultado = EspelhoAFD(layout=671).processar(
            "\r\n".join(registros),
            layout=671,
            data_inicial="2026-11-03",
            data_final="2026-11-03",
        )

        self.assertEqual(
            [funcionario["identificador"] for funcionario in resultado["funcionarios"]],
            [funcionario_com_marcacao],
        )

    def test_omite_loja_sem_resultados_ao_consultar_todas(self):
        self.assertTrue(
            _omitir_loja_sem_resultados(
                funcionarios=[],
                todas_lojas=True,
                busca="",
            )
        )

    def test_omite_loja_sem_funcionario_encontrado_na_busca(self):
        self.assertTrue(
            _omitir_loja_sem_resultados(
                funcionarios=[],
                todas_lojas=False,
                busca="Tetsuo",
            )
        )

    def test_preserva_loja_selecionada_sem_busca(self):
        self.assertFalse(
            _omitir_loja_sem_resultados(
                funcionarios=[],
                todas_lojas=False,
                busca="",
            )
        )

    def test_preserva_loja_com_funcionarios_com_marcacoes(self):
        self.assertFalse(
            _omitir_loja_sem_resultados(
                funcionarios=[{"nome": "Funcionário", "marcacoes": [{}]}],
                todas_lojas=True,
                busca="Tetsuo",
            )
        )


class AtualizacaoTests(unittest.TestCase):
    def test_detecta_release_e_asset_windows(self):
        release = {
            "tag_name": "chronosnap-v1.0.11",
            "name": "ChronoSnap 1.0.11",
            "body": "Correções e melhorias",
            "html_url": "https://github.com/tr6499/ChronoSnap/releases/tag/1.0.11",
            "published_at": "2026-11-05T12:00:00Z",
            "assets": [
                {
                    "name": "ChronoSnap-Setup-1.0.11.exe",
                    "browser_download_url": (
                        "https://github.com/tr6499/ChronoSnap/releases/download/"
                        "1.0.11/ChronoSnap-Setup-1.0.11.exe"
                    ),
                    "digest": "sha256:" + ("a" * 64),
                    "size": 20,
                }
            ],
        }
        with patch(
            "services.atualizacoes.urlopen",
            return_value=io.BytesIO(json.dumps(release).encode("utf-8")),
        ) as abrir_url:
            resultado = obter_ultima_release()

        contexto = abrir_url.call_args.kwargs["context"]
        self.assertIsInstance(contexto, ssl.SSLContext)
        self.assertEqual(contexto.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(contexto.check_hostname)
        self.assertTrue(resultado["atualizacao_disponivel"])
        self.assertEqual(resultado["versao_disponivel"], "1.0.11")
        self.assertIsNotNone(resultado["instalador"])

    def test_baixa_instalador_e_valida_sha256(self):
        conteudo = b"ChronoSnap installer"
        release = {
            "instalador": {
                "url": (
                    "https://github.com/tr6499/ChronoSnap/releases/download/"
                    "1.0.11/ChronoSnap-Setup-1.0.11.exe"
                ),
                "sha256": hashlib.sha256(conteudo).hexdigest(),
            }
        }

        class FakeResponse(io.BytesIO):
            headers = {"Content-Length": str(len(conteudo))}

        with tempfile.TemporaryDirectory() as diretorio:
            destino = Path(diretorio) / "installer.exe"
            with patch(
                "services.atualizacoes.urlopen",
                return_value=FakeResponse(conteudo),
            ):
                resultado = baixar_instalador(release, destino)

            self.assertEqual(resultado.read_bytes(), conteudo)

    def test_modo_de_atualizacao_persiste_em_arquivo_separado(self):
        with tempfile.TemporaryDirectory() as diretorio:
            caminho_original = Path(diretorio) / "atualizacoes.json"
            with patch(
                "services.atualizacoes.ARQUIVO_CONFIG_ATUALIZACAO",
                caminho_original,
            ):
                self.assertEqual(ler_modo_atualizacao(), "manual")
                salvar_modo_atualizacao("automatico")
                self.assertEqual(ler_modo_atualizacao(), "automatico")
