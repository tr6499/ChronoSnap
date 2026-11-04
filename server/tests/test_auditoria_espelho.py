import unittest
from datetime import datetime

from services.auditoria import converter_para_horario_local
from services.espelho import EspelhoAFD


class AuditoriaHorarioTests(unittest.TestCase):
    def test_converte_horario_utc_sem_fuso_para_horario_local(self):
        convertido = converter_para_horario_local(
            datetime(2026, 11, 4, 10, 15, 0)
        )

        self.assertEqual(
            convertido.isoformat(),
            "2026-11-04T07:15:00-03:00",
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
