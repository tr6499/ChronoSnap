class CompanyMixin:
    """
    Métodos relacionados aos dados da empresa (empregador).
    """

    def get_company(self):
        """
        Retorna os dados da empresa cadastrada.
        """

        return self.call("load_company")

    def edit_company(
        self,
        company
    ):
        """
        Atualiza os dados da empresa.

        Exemplo:

        company = {
            "tipo_doc": 1,
            "cpf_cnpj": 12345678000199,
            "cei": 123456789012,
            "cpf": 12345678901,
            "name": "Empresa Ltda",
            "address": "Rua A, 100"
        }
        """

        return self.call(
            "edit_company",
            {
                "company": company
            }
        )

    def get_employer(self):
        """
        Alias para get_company().
        """

        return self.get_company()

    def edit_employer(
        self,
        employer
    ):
        """
        Alias para edit_company().
        """

        return self.edit_company(employer)

    def company_name(self):
        """
        Retorna o nome da empresa.
        """

        empresa = self.get_company()

        return empresa.get(
            "company",
            {}
        ).get("name")

    def company_address(self):
        """
        Retorna o endereço da empresa.
        """

        empresa = self.get_company()

        return empresa.get(
            "company",
            {}
        ).get("address")

    def company_document(self):
        """
        Retorna o CPF/CNPJ da empresa.
        """

        empresa = self.get_company()

        return empresa.get(
            "company",
            {}
        ).get("cpf_cnpj")

    def company_tipo_doc(self):
        """
        Retorna o tipo do documento.

        1 = CNPJ
        2 = CPF
        """

        empresa = self.get_company()

        return empresa.get(
            "company",
            {}
        ).get("tipo_doc")

    def company_cei(self):
        """
        Retorna CEI/CAEPF/CNO.
        """

        empresa = self.get_company()

        return empresa.get(
            "company",
            {}
        ).get("cei")

    def company_responsavel_cpf(self):
        """
        Retorna o CPF do responsável.
        """

        empresa = self.get_company()

        return empresa.get(
            "company",
            {}
        ).get("cpf")

    def company_exists(self):
        """
        Verifica se existe empresa cadastrada.
        """

        empresa = self.get_company()

        return "company" in empresa

    def print_company(self):
        """
        Exibe os dados da empresa formatados.
        """

        empresa = self.get_company()

        dados = empresa.get("company", {})

        print("-" * 60)

        for chave, valor in dados.items():
            print(f"{chave}: {valor}")

        print("-" * 60)

        return dados

    def update_company(
        self,
        name=None,
        address=None,
        tipo_doc=None,
        cpf_cnpj=None,
        cei=None,
        cpf=None
    ):
        """
        Atualiza apenas os campos informados.
        """

        empresa = self.get_company()["company"].copy()

        if name is not None:
            empresa["name"] = name

        if address is not None:
            empresa["address"] = address

        if tipo_doc is not None:
            empresa["tipo_doc"] = tipo_doc

        if cpf_cnpj is not None:
            empresa["cpf_cnpj"] = int(cpf_cnpj)

        if cei is not None:
            empresa["cei"] = int(cei)

        if cpf is not None:
            empresa["cpf"] = int(cpf)

        return self.edit_company(empresa)