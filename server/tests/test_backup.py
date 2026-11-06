import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import models_usuarios
import services.backup as backup
from database import Base


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data_dir = self.root / "data"
        self.backup_dir = self.data_dir / "backups"
        self.settings_file = self.data_dir / "backup_settings.json"
        self.database_config_file = self.data_dir / "database.json"
        (self.data_dir / "downloads").mkdir(parents=True)
        (self.data_dir / "banco").mkdir()
        (self.backup_dir / "nested").mkdir(parents=True)
        (self.data_dir / "downloads" / "operacao.txt").write_text(
            "dados operacionais", encoding="utf-8"
        )
        (self.data_dir / "banco" / "afd.db").write_bytes(b"arquivo-db-live")
        (self.backup_dir / "nested" / "antigo.zip").write_bytes(b"nao incluir")
        self.database_config_file.write_text(
            '{"password":"segredo"}', encoding="utf-8"
        )
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.patches = [
            patch.object(backup, "DATA_DIR", self.data_dir),
            patch.object(backup, "BACKUP_DIR", self.backup_dir),
            patch.object(backup, "BACKUP_SETTINGS_FILE", self.settings_file),
            patch.object(backup, "DATABASE_CONFIG_FILE", self.database_config_file),
            patch.object(backup, "engine", self.engine),
            patch.object(backup, "DATABASE_CONFIG", {"backend": "sqlite"}),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.engine.dispose()
        self.temp.cleanup()

    def test_backup_zip_restaura_tabelas_e_arquivos_sem_incluir_sqlite_ativo(self):
        with self.Session() as db:
            db.add(
                models.Loja(
                    numero=12,
                    nome="Empresa original",
                    ip="127.0.0.1",
                    afd_layout="legado",
                )
            )
            db.add(
                models.MarcacaoAFD(
                    loja_id=12,
                    nsr="1",
                    tipo="3",
                    layout="legado",
                    identificador="123",
                    data_hora=datetime(2026, 11, 6, 8, 0),
                    assinatura="assinatura",
                )
            )
            db.add(
                models_usuarios.ConfiguracaoSistema(
                    chave="teste", valor="original"
                )
            )
            db.commit()

        arquivo = backup.criar_backup()
        with zipfile.ZipFile(arquivo) as conteudo:
            self.assertIn("database.json", conteudo.namelist())
            self.assertIn("files/database.json", conteudo.namelist())
            self.assertIn("files/downloads/operacao.txt", conteudo.namelist())
            self.assertFalse(any(nome.startswith("files/banco/") for nome in conteudo.namelist()))
            self.assertFalse(any("antigo.zip" in nome for nome in conteudo.namelist()))

        with self.Session() as db:
            db.query(models.Loja).filter_by(numero=12).delete()
            db.add(
                models.Loja(
                    numero=13,
                    nome="Empresa nova",
                    ip="127.0.0.2",
                    afd_layout="671",
                )
            )
            db.commit()
        (self.data_dir / "downloads" / "operacao.txt").write_text(
            "alterado", encoding="utf-8"
        )
        self.database_config_file.write_text(
            '{"password":"conexao atual"}', encoding="utf-8"
        )

        with arquivo.open("rb") as origem:
            backup.restaurar_backup(origem)

        with self.Session() as db:
            empresa = db.query(models.Loja).one()
            marcacao = db.query(models.MarcacaoAFD).one()
            configuracao = db.query(models_usuarios.ConfiguracaoSistema).one()
            self.assertEqual(empresa.nome, "Empresa original")
            self.assertEqual(marcacao.data_hora, datetime(2026, 11, 6, 8, 0))
            self.assertEqual(configuracao.valor, "original")

        self.assertEqual(
            (self.data_dir / "downloads" / "operacao.txt").read_text(
                encoding="utf-8"
            ),
            "dados operacionais",
        )
        self.assertEqual(
            self.database_config_file.read_text(encoding="utf-8"),
            '{"password":"conexao atual"}',
        )
        self.assertEqual(backup.obter_configuracao()["enabled"], False)

    def test_rejeita_caminho_de_zip_inseguro_sem_alterar_o_banco(self):
        with self.Session() as db:
            db.add(
                models.Loja(
                    numero=1,
                    nome="Preservar",
                    ip="127.0.0.1",
                    afd_layout="legado",
                )
            )
            db.commit()
        arquivo = backup.criar_backup()
        arquivo_malicioso = self.root / "inseguro.zip"
        with zipfile.ZipFile(arquivo) as original, zipfile.ZipFile(
            arquivo_malicioso, "w"
        ) as adulterado:
            for nome in original.namelist():
                adulterado.writestr(nome, original.read(nome))
            adulterado.writestr("files/../../fora.txt", "nao extrair")

        with arquivo_malicioso.open("rb") as origem:
            with self.assertRaisesRegex(ValueError, "caminho ou arquivo inseguro"):
                backup.restaurar_backup(origem)

        with self.Session() as db:
            self.assertEqual(
                [loja.nome for loja in db.query(models.Loja).all()],
                ["Preservar"],
            )

    def test_backup_automatico_fica_desligado_por_padrao(self):
        self.assertFalse(backup.obter_configuracao()["enabled"])
