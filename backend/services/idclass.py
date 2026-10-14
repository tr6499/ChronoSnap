import requests
import urllib3

from services.users import UsersMixin
from services.company import CompanyMixin
from services.system import SystemMixin
from services.afd import AFDMixin

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class IDClass(
    UsersMixin,
    CompanyMixin,
    SystemMixin,
    AFDMixin
):

    def __init__(
        self,
        ip,
        port=443,
        username="admin",
        password="7070",
        timeout=30
    ):
        self.ip = ip
        self.port = port or 443
        self.username = username
        self.password = password
        self.timeout = timeout
        host = str(ip)
        if ":" not in host and self.port != 443:
            host = f"{host}:{self.port}"
        self.base_url = f"https://{host}"
        self.session = None

    def _post(
        self,
        endpoint,
        payload=None,
        params=None,
        timeout=None,
        binary=False
    ):
        if not self.session:
            self.login_device()

        if params is None:
            params = {}

        params["session"] = self.session

        response = requests.post(
            f"{self.base_url}/{endpoint}.fcgi",
            json=payload,
            params=params,
            verify=False,
            timeout=timeout or self.timeout,
            stream=binary
        )

        return response

    def call(
        self,
        endpoint,
        payload=None,
        params=None,
        timeout=None,
        binary=False
    ):
        response = self._post(
            endpoint,
            payload,
            params,
            timeout,
            binary
        )

        print("=" * 60)
        print("ENDPOINT:", endpoint)
        print("STATUS:", response.status_code)

        if binary:
            print("BINARY:", len(response.content), "bytes")
        else:
            print("BODY:", response.text[:800])

        print("=" * 60)

        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            detalhe = response.text.strip()
            if detalhe:
                raise requests.HTTPError(
                    f"{error} - resposta do equipamento: {detalhe[:500]}",
                    response=response
                ) from error
            raise

        if binary:
            return response.content

        return response.json()

    def login_device(self):
        resposta = requests.post(
            f"{self.base_url}/login.fcgi",
            json={
                "login": self.username,
                "password": self.password
            },
            verify=False,
            timeout=self.timeout
        )

        resposta.raise_for_status()

        dados = resposta.json()

        self.session = dados["session"]

        return dados

    def logout(self):
        if not self.session:
            return

        try:
            self.call("logout")
        finally:
            self.session = None

    def create_objects(self, payload):
        return self.call(
            "create_objects",
            payload
        )

    def load_objects(self, payload):
        return self.call(
            "load_objects",
            payload
        )