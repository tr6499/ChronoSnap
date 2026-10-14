from datetime import datetime


class SystemMixin:
    """
    Métodos relacionados ao sistema do REP.
    """

    def get_system_information(self):
        """
        Retorna informações gerais do sistema.
        """

        return self.call(
            "get_system_information"
        )

    def get_rep_information(self):
        """
        Retorna informações específicas do REP.
        """

        return self.call(
            "get_about",
            payload={}
        )

    def set_idcloud(self, enable):
        """
        Ativa ou desativa o iDCloud no REP.
        """

        return self.call(
            "set_idcloud",
            payload={
                "enable": bool(enable)
            }
        )

    def get_idcloud(self):
        """
        Retorna o estado atual do iDCloud no REP.
        """

        return self.call(
            "get_idcloud",
            payload={}
        )

    def get_system_network(self):
        """
        Retorna a configuração de rede atual do REP.
        """

        return self.call(
            "get_system_network",
            payload={}
        )

    def set_system_network(self, payload):
        """
        Atualiza a configuração de rede do REP.
        """

        return self.call(
            "set_system_network",
            payload=payload
        )

    def get_about(self):
        """
        Retorna informações do equipamento.
        """

        return self.call(
            "get_about"
        )

    def get_system_date_time(self):
        """
        Retorna data e hora do equipamento.
        """

        return self.call(
            "get_system_date_time"
        )

    def set_system_date_time(
        self,
        day,
        month,
        year,
        hour,
        minute,
        second=0,
        timezone="-0300",
        mode=671
    ):
        """
        Ajusta data e hora do equipamento.
        """

        payload = {
            "day": day,
            "month": month,
            "year": year,
            "hour": hour,
            "minute": minute,
            "second": second
        }

        if mode == 671:
            payload["timezone"] = timezone

        return self.call(
            "set_system_date_time",
            payload,
            params={
                "mode": mode
            }
        )

    def sync_datetime(
        self,
        timezone="-0300",
        mode=671
    ):
        """
        Sincroniza a data e hora do equipamento com o computador.
        """

        agora = datetime.now()

        return self.set_system_date_time(
            day=agora.day,
            month=agora.month,
            year=agora.year,
            hour=agora.hour,
            minute=agora.minute,
            second=agora.second,
            timezone=timezone,
            mode=mode
        )

    def serial_number(self):
        """
        Retorna o número de série.
        """

        return self.get_about()["nSerie"]

    def firmware_version(self):
        """
        Retorna a versão do firmware.
        """

        return self.get_about()["versionFW"]

    def mrp_version(self):
        """
        Retorna a versão da MRP.
        """

        return self.get_about()["versionMRP"]

    def mac_address(self):
        """
        Retorna o MAC Address.
        """

        return self.get_about()["mac"]

    def is_facial(self):
        """
        Verifica se o equipamento é facial.
        """

        return self.get_about().get(
            "isFacial",
            False
        )

    def print_about(self):
        """
        Exibe informações do equipamento.
        """

        about = self.get_about()

        print("-" * 60)

        for chave, valor in about.items():
            print(f"{chave}: {valor}")

        print("-" * 60)

        return about

    def print_system_information(self):
        """
        Exibe informações do sistema.
        """

        info = self.get_system_information()

        print("-" * 60)

        for chave, valor in info.items():
            print(f"{chave}: {valor}")

        print("-" * 60)

        return info

    def print_system_date_time(self):
        """
        Exibe data e hora do equipamento.
        """

        data = self.get_system_date_time()

        print("-" * 60)

        for chave, valor in data.items():
            print(f"{chave}: {valor}")

        print("-" * 60)

        return data