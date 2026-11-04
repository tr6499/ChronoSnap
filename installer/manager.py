"""Painel Manager do ChronoSnap para iniciar e parar o servidor."""
import json
import os
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk

IS_WIN = os.name == "nt"
FROZEN = "__compiled__" in globals()
EXE_DIR = Path(sys.argv[0]).resolve().parent
ROOT = EXE_DIR.parent


def _report_crash(exc_type, exc, tb):
    temp_dir = os.environ.get("TEMP") or os.environ.get("TMP") or "."
    log = Path(temp_dir) / "chronosnap-manager-error.log"
    error = f"{getattr(exc_type, '__name__', str(exc_type))}: {exc}"
    try:
        log.write_text(error + "\n", encoding="utf-8")
    except OSError:
        pass
    try:
        import traceback

        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.write_text(text, encoding="utf-8")
    except Exception as format_error:
        text = f"{error}\nCould not format traceback: {format_error}"
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None, f"O Manager não pôde iniciar.\n\n{text[-1200:]}\n\nLog: {log}",
                "ChronoSnap Manager", 0x10,
            )
        except Exception:
            pass


sys.excepthook = _report_crash

if FROZEN:
    SERVER_EXE = ROOT / "server" / ("ChronoSnapServer.exe" if IS_WIN else "ChronoSnapServer")
else:
    sys.path.insert(0, str(ROOT / "server"))

os.environ.setdefault("CHRONOSNAP_DATA", str(ROOT / "data"))

from app_paths import DATA_DIR  # noqa: E402
from services.atualizacoes import (  # noqa: E402
    ErroAtualizacao,
    VERSAO_ATUAL,
    baixar_instalador,
    ler_modo_atualizacao,
    obter_ultima_release,
)

CONFIG_FILE = DATA_DIR / "manager.json"
LOG_FILE = DATA_DIR / "logs" / "server.log"
BLUE, BLUE_DEEP, INK, SOFT, BG = "#0d6efd", "#0756a6", "#102a43", "#607486", "#f4f8fc"
APP_VERSION = VERSAO_ATUAL
GNU_LICENSE_URL = "https://www.gnu.org/licenses/gpl-3.0.html"


def load_config():
    cfg = {
        "mode": "local",
        "port": 8000,
        "minimize_to_tray": False,
        "start_server_on_open": False,
        "restart_after_update": False,
    }
    try:
        saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cfg
    if isinstance(saved, dict):
        cfg["port"] = saved.get("port", cfg["port"])
        mode = saved.get("mode")
        if mode in ("local", "network"):
            cfg["mode"] = mode
        elif saved.get("host") == "0.0.0.0":
            cfg["mode"] = "network"
        cfg["minimize_to_tray"] = bool(saved.get("minimize_to_tray", False))
        cfg["start_server_on_open"] = bool(saved.get("start_server_on_open", False))
        cfg["restart_after_update"] = bool(saved.get("restart_after_update", False))
    return cfg


def server_host(mode):
    return "0.0.0.0" if mode == "network" else "127.0.0.1"


def definir_geometria_centralizada(window, width, height, min_width=None, min_height=None):
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    width = min(width, max(320, screen_width - 80))
    height = min(height, max(320, screen_height - 100))
    if min_width is not None or min_height is not None:
        window.minsize(
            min(min_width or width, width),
            min(min_height or height, height),
        )
    x = max(0, (screen_width - width) // 2)
    y = max(0, (screen_height - height) // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")


class Manager(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ChronoSnap - Manager")
        self.icon_path = (
            Path(__file__).resolve().parent / "chronosnap-program.ico"
            if FROZEN else ROOT / "assets" / "chronosnap-program.ico"
        )
        try:
            self.iconbitmap(str(self.icon_path))
        except tk.TclError:
            pass
        definir_geometria_centralizada(self, 680, 500)
        self.configure(bg=BG)
        self.proc = None
        self.cfg = load_config()
        self.restart_server_after_update = self.cfg.pop("restart_after_update", False)
        if self.restart_server_after_update:
            self.cfg["restart_after_update"] = False
            try:
                CONFIG_FILE.write_text(
                    json.dumps(self.cfg, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError as exc:
                messagebox.showerror(
                    "ChronoSnap",
                    f"Não foi possível atualizar a configuração do Manager:\n{exc}",
                )
        self.access_var = tk.StringVar(value=self.cfg["mode"])
        self.minimize_to_tray_var = tk.BooleanVar(
            value=self.cfg["minimize_to_tray"] and IS_WIN
        )
        self.start_server_on_open_var = tk.BooleanVar(
            value=self.cfg["start_server_on_open"]
        )
        self.tray_icon = None
        self.update_window = None
        self.update_notes = None
        self.update_status = None
        self.update_install_button = None
        self.latest_release = None
        self.update_check_running = False
        self._style()
        self._build()
        self.update_idletasks()
        definir_geometria_centralizada(self, 680, 500)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Unmap>", self.on_minimize)
        if self.minimize_to_tray_var.get():
            self.after_idle(self._restore_tray_icon)
        if self.restart_server_after_update or self.start_server_on_open_var.get():
            self.after(1500, self.start)
        if IS_WIN and FROZEN:
            self.after(3000, self._check_for_updates_automatically)
        self.after(1000, self.refresh)

    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame", background=BG)
        s.configure("TLabelframe", background=BG)
        s.configure("TLabelframe.Label", background=BG, foreground=BLUE_DEEP, font=("Segoe UI", 10, "bold"))
        s.configure("TLabel", background=BG, foreground=INK, font=("Segoe UI", 10))
        s.configure("Title.TLabel", font=("Segoe UI", 16, "bold"), foreground=BLUE_DEEP)
        s.configure("Sub.TLabel", foreground=SOFT)
        s.configure("TButton", font=("Segoe UI", 10), padding=8)
        s.configure("Accent.TButton", background=BLUE, foreground="white")
        s.map("Accent.TButton", background=[("active", BLUE_DEEP), ("disabled", "#9ec5fe")])

    def _build(self):
        menu = tk.Menu(self)
        license_menu = tk.Menu(menu, tearoff=False)
        license_menu.add_command(
            label="Sobre o ChronoSnap e licença...",
            command=self.show_license,
        )
        license_menu.add_command(
            label="Abrir página da GNU...",
            command=lambda: webbrowser.open(GNU_LICENSE_URL),
        )
        menu.add_cascade(label="Sobre", menu=license_menu)
        update_menu = tk.Menu(menu, tearoff=False)
        update_menu.add_command(
            label="Verificar atualizações...",
            command=self.open_update_window,
        )
        menu.add_cascade(label="Atualizações", menu=update_menu)
        self.configure(menu=menu)

        f = ttk.Frame(self, padding=20)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="ChronoSnap", style="Title.TLabel").pack(anchor="w")
        ttk.Label(f, text="Painel de controle do servidor", style="Sub.TLabel").pack(anchor="w", pady=(0, 12))

        row = ttk.Frame(f)
        row.pack(fill="x")
        ttk.Label(row, text="Status:").pack(side="left")
        self.status = tk.Label(row, text="Parado", bg=BG, fg="#b42318", font=("Segoe UI", 10, "bold"))
        self.status.pack(side="left", padx=6)
        ttk.Label(row, text="Porta:").pack(side="left", padx=(20, 4))
        self.port_var = tk.StringVar(value=str(self.cfg["port"]))
        self.port_entry = ttk.Entry(row, textvariable=self.port_var, width=7)
        self.port_entry.pack(side="left")

        access = ttk.LabelFrame(f, text="Acesso ao servidor", padding=8)
        access.pack(fill="x", pady=(10, 0))
        self.local_radio = ttk.Radiobutton(
            access, text="Somente neste computador", variable=self.access_var,
            value="local", command=self.save_access_mode,
        )
        self.local_radio.pack(anchor="w")
        self.network_radio = ttk.Radiobutton(
            access, text="Rede local (outros computadores)", variable=self.access_var,
            value="network", command=self.save_access_mode,
        )
        self.network_radio.pack(anchor="w")
        ttk.Label(
            access,
            text="Na rede, os usuários acessam pelo IPv4 deste computador. "
                 "Libere a porta no Firewall do Windows para a rede privada.",
            style="Sub.TLabel", wraplength=600, justify="left",
        ).pack(anchor="w", padx=(22, 0), pady=(2, 0))

        btns = ttk.Frame(f)
        btns.pack(fill="x", pady=12)
        self.btn_start = ttk.Button(btns, text="Iniciar", style="Accent.TButton", command=self.start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(btns, text="Parar", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=8)
        ttk.Button(btns, text="Abrir no navegador", command=self.open_browser).pack(side="left")

        tray_option = ttk.Checkbutton(
            f,
            text="Minimizar para a bandeja (remover da barra de tarefas)",
            variable=self.minimize_to_tray_var,
            command=self.toggle_tray_option,
            state="normal" if IS_WIN else "disabled",
        )
        tray_option.pack(anchor="w", pady=(0, 8))
        ttk.Checkbutton(
            f,
            text="Iniciar o servidor automaticamente ao abrir o Manager",
            variable=self.start_server_on_open_var,
            command=self.toggle_start_server_on_open,
        ).pack(anchor="w", pady=(0, 8))
        if not IS_WIN:
            ttk.Label(
                f,
                text="A bandeja do sistema está disponível no Manager para Windows.",
                style="Sub.TLabel",
            ).pack(anchor="w", pady=(0, 8))

        ttk.Label(f, text="Log do servidor:").pack(anchor="w")
        box = ttk.Frame(f)
        box.pack(fill="both", expand=True)
        self.log = tk.Text(box, height=10, state="disabled", font=("Consolas", 9), bg="white", fg=INK, relief="solid", bd=1)
        sb = ttk.Scrollbar(box, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

    def show_license(self):
        license_window = tk.Toplevel(self)
        license_window.title("Sobre o ChronoSnap")
        definir_geometria_centralizada(license_window, 760, 680, 600, 480)
        license_window.transient(self)
        license_window.configure(bg=BG)

        content = ttk.Frame(license_window, padding=20)
        content.pack(fill="both", expand=True)
        ttk.Label(content, text="ChronoSnap", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            content,
            text=f"Versão {APP_VERSION}  ·  Licença GNU General Public License v3",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(2, 4))
        ttk.Label(
            content,
            text="Autor: Tetsuo Rodolfo Okubo",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", pady=(0, 12))

        license_frame = ttk.Frame(content)
        license_frame.pack(fill="both", expand=True)
        license_text = tk.Text(
            license_frame,
            wrap="word",
            font=("Segoe UI", 9),
            state="normal",
            bg="white",
            fg=INK,
            relief="solid",
            bd=1,
            padx=12,
            pady=10,
        )
        scrollbar = ttk.Scrollbar(license_frame, command=license_text.yview)
        license_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        license_text.pack(side="left", fill="both", expand=True)

        license_path = ROOT / ("LICENSE.txt" if FROZEN else "COPYING")
        try:
            terms = license_path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            license_window.destroy()
            messagebox.showerror(
                "ChronoSnap",
                f"Não foi possível carregar o texto da GNU GPL v3:\n{exc}",
            )
            return

        license_text.insert("1.0", terms)
        license_text.configure(state="disabled")

        actions = ttk.Frame(content)
        actions.pack(fill="x", pady=(12, 0))
        ttk.Button(
            actions,
            text="Texto oficial da GNU GPL v3",
            command=lambda: webbrowser.open(GNU_LICENSE_URL),
        ).pack(side="left")
        ttk.Button(actions, text="Fechar", command=license_window.destroy).pack(side="right")
        license_window.update_idletasks()
        definir_geometria_centralizada(license_window, 760, 680, 600, 480)

    def open_update_window(self):
        if not IS_WIN:
            messagebox.showinfo(
                "Atualizações",
                "A atualização automática está disponível somente para a instalação Windows.",
            )
            return
        if self.update_window is not None and self.update_window.winfo_exists():
            self.update_window.lift()
            return

        window = tk.Toplevel(self)
        window.title("Atualizações do ChronoSnap")
        definir_geometria_centralizada(window, 900, 720, 680, 560)
        window.transient(self)
        window.configure(bg=BG)
        self.update_window = window
        self.update_status = tk.StringVar(
            value=f"Versão instalada: {APP_VERSION}. Verificando releases do GitHub..."
        )
        content = ttk.Frame(window, padding=18)
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(3, weight=1)
        ttk.Label(content, text="Atualizações do ChronoSnap", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        status_label = ttk.Label(content, textvariable=self.update_status, wraplength=640)
        status_label.grid(
            row=1, column=0, sticky="w", pady=(8, 12)
        )
        try:
            modo_atualizacao = ler_modo_atualizacao()
        except ErroAtualizacao as exc:
            modo_atualizacao = "indisponível"
            self.append(f"Falha ao carregar o modo de atualização: {exc}\n")
        descricao_modo = (
            "Automático: verifica periodicamente e baixa a atualização; "
            "a instalação ainda exige confirmação local."
            if modo_atualizacao == "automatico"
            else "Manual: use Verificar atualizações e Baixar e instalar para escolher "
            "quando atualizar."
        )
        mode_label = ttk.Label(
            content,
            text=(
                f"Modo {modo_atualizacao}. {descricao_modo}\n"
                "A atualização substitui os arquivos na pasta atual e preserva os dados. "
                "O Manager para o servidor antes de instalar; o Windows solicitará "
                "permissão de administrador."
            ),
            wraplength=640,
            justify="left",
        )
        mode_label.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        def ajustar_largura(event):
            if event.widget is window:
                wraplength = max(240, event.width - 56)
                status_label.configure(wraplength=wraplength)
                mode_label.configure(wraplength=wraplength)

        window.bind("<Configure>", ajustar_largura)
        notes_frame = ttk.Frame(content)
        notes_frame.grid(row=3, column=0, sticky="nsew")
        self.update_notes = tk.Text(
            notes_frame,
            wrap="word",
            state="disabled",
            font=("Segoe UI", 9),
            bg="white",
            fg=INK,
            relief="solid",
            bd=1,
            padx=10,
            pady=8,
        )
        scrollbar = ttk.Scrollbar(notes_frame, command=self.update_notes.yview)
        self.update_notes.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.update_notes.pack(side="left", fill="both", expand=True)

        actions = ttk.Frame(content)
        actions.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        for column in range(3):
            actions.columnconfigure(column, weight=1, uniform="update-actions")
        ttk.Button(
            actions,
            text="Verificar novamente",
            command=lambda: self._check_for_updates(show_result=True),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.update_install_button = ttk.Button(
            actions,
            text="Baixar e instalar",
            style="Accent.TButton",
            command=self._download_latest_installer,
            state="disabled",
        )
        self.update_install_button.grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(
            actions,
            text="Fechar",
            command=window.destroy,
        ).grid(row=0, column=2, sticky="ew", padx=(6, 0))
        window.protocol("WM_DELETE_WINDOW", self._close_update_window)
        window.update_idletasks()
        definir_geometria_centralizada(window, 900, 720, 680, 560)
        self._check_for_updates(show_result=True)

    def _close_update_window(self):
        if self.update_window is not None:
            self.update_window.destroy()
        self.update_window = None
        self.update_notes = None
        self.update_status = None
        self.update_install_button = None

    def _check_for_updates_automatically(self):
        try:
            if ler_modo_atualizacao() == "automatico":
                self._check_for_updates(show_result=False, automatico=True)
        except ErroAtualizacao as exc:
            self.append(f"Falha ao carregar o modo de atualização: {exc}\n")
        self.after(6 * 60 * 60 * 1000, self._check_for_updates_automatically)

    def _check_for_updates(self, show_result=True, automatico=False):
        if self.update_check_running:
            return
        self.update_check_running = True

        def consultar():
            try:
                release = obter_ultima_release()
                erro = None
            except ErroAtualizacao as exc:
                release = None
                erro = str(exc)
            self.after(
                0,
                self._concluir_verificacao_atualizacao,
                release,
                erro,
                show_result,
                automatico,
            )

        threading.Thread(target=consultar, daemon=True).start()

    def _concluir_verificacao_atualizacao(
        self, release, erro, mostrar_resultado, automatico
    ):
        self.update_check_running = False
        if erro:
            self.append(f"Falha ao verificar atualizações: {erro}\n")
            if self.update_status is not None:
                self.update_status.set(erro)
            if mostrar_resultado:
                messagebox.showerror("Atualizações", erro)
            return

        self.latest_release = release
        atualizacao_disponivel = release["atualizacao_disponivel"]
        instalador_disponivel = release["instalador_verificado"]
        if self.update_notes is not None:
            self.update_notes.configure(state="normal")
            self.update_notes.delete("1.0", "end")
            self.update_notes.insert("1.0", release["notas"])
            self.update_notes.configure(state="disabled")
        if self.update_status is not None:
            if atualizacao_disponivel:
                texto = f"Nova versão disponível: {release['versao_disponivel']}."
                if not instalador_disponivel:
                    texto += " A release não contém um instalador Windows válido."
            else:
                texto = f"ChronoSnap {APP_VERSION} está atualizado."
            self.update_status.set(texto)
        if self.update_install_button is not None:
            self.update_install_button.configure(
                state="normal" if atualizacao_disponivel and instalador_disponivel else "disabled"
            )

        if atualizacao_disponivel and instalador_disponivel and automatico:
            self._iniciar_download_instalador(release)
        elif mostrar_resultado and not atualizacao_disponivel:
            messagebox.showinfo(
                "Atualizações",
                f"Esta instalação já está atualizada (versão {APP_VERSION}).",
            )

    def _download_latest_installer(self):
        if self.latest_release:
            self._iniciar_download_instalador(self.latest_release)

    def _iniciar_download_instalador(self, release):
        if self.update_install_button is not None:
            self.update_install_button.configure(state="disabled")
        destino = DATA_DIR / "downloads" / release["instalador"]["nome"]
        if self.update_status is not None:
            self.update_status.set("Baixando e verificando o instalador...")

        def baixar():
            try:
                caminho = baixar_instalador(release, destino)
                erro = None
            except ErroAtualizacao as exc:
                caminho = None
                erro = str(exc)
            self.after(0, self._download_concluido, release, caminho, erro)

        threading.Thread(target=baixar, daemon=True).start()

    def _download_concluido(self, release, caminho, erro):
        if erro:
            if self.update_status is not None:
                self.update_status.set(erro)
            if self.update_install_button is not None:
                self.update_install_button.configure(state="normal")
            messagebox.showerror("Atualizações", erro)
            return
        if self.update_status is not None:
            self.update_status.set(f"Instalador verificado: {caminho}")
        if messagebox.askyesno(
            "Instalar atualização",
            f"O instalador da versão {release['versao_disponivel']} foi baixado "
            "e verificado.\n\nO servidor será parado e o Manager fechado para "
            "atualizar os arquivos. O instalador solicitará permissão de administrador. "
            "Deseja continuar?",
        ):
            self._iniciar_instalacao(caminho)
        elif self.update_install_button is not None:
            self.update_install_button.configure(state="normal")

    def _iniciar_instalacao(self, caminho_instalador):
        if not FROZEN:
            messagebox.showerror(
                "Atualizações",
                "A instalação automática só pode ser iniciada pelo Manager compilado.",
            )
            return

        try:
            reiniciar_servidor = self.servidor_em_execucao()
        except OSError as exc:
            messagebox.showerror(
                "Atualizações",
                f"Não foi possível verificar se o servidor está em execução:\n{exc}",
            )
            return
        self.cfg["restart_after_update"] = reiniciar_servidor
        try:
            CONFIG_FILE.write_text(
                json.dumps(self.cfg, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            messagebox.showerror(
                "Atualizações",
                f"Não foi possível preparar a atualização: {exc}",
            )
            return

        if reiniciar_servidor:
            if not self.stop():
                self.cfg["restart_after_update"] = False
                try:
                    CONFIG_FILE.write_text(
                        json.dumps(self.cfg, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except OSError as exc:
                    self.append(
                        f"Não foi possível cancelar a reinicialização do servidor: {exc}\n"
                    )
                messagebox.showerror(
                    "Atualizações",
                    "O servidor não parou. A atualização foi cancelada; "
                    "pare o servidor e tente novamente.",
                )
                return

        manager = Path(sys.argv[0]).resolve()
        install_dir = manager.parent.parent
        script = DATA_DIR / "downloads" / "aplicar_atualizacao.ps1"
        quote_ps = lambda valor: "'" + str(valor).replace("'", "''") + "'"
        conteudo = (
            "$ErrorActionPreference = 'Stop'\n"
            f"$installer = {quote_ps(caminho_instalador)}\n"
            f"$manager = {quote_ps(manager)}\n"
            f"$installDir = {quote_ps(install_dir)}\n"
            f"$parentPid = {os.getpid()}\n"
            "try {\n"
            "    while (Get-Process -Id $parentPid -ErrorAction SilentlyContinue) { Start-Sleep -Seconds 1 }\n"
            "    $arguments = '/DIR=\"' + $installDir + '\" /CLOSEAPPLICATIONS'\n"
            "    $process = Start-Process -FilePath $installer -ArgumentList $arguments -Verb RunAs -Wait -PassThru\n"
            "    if ($process.ExitCode -ne 0) { Start-Process -FilePath $manager }\n"
            "} catch {\n"
            "    Start-Process -FilePath $manager\n"
            "    exit 1\n"
            "}\n"
        )
        powershell = Path(os.environ.get("WINDIR", r"C:\Windows")) / (
            "System32\\WindowsPowerShell\\v1.0\\powershell.exe"
        )
        try:
            script.write_text(conteudo, encoding="utf-8")
            subprocess.Popen(
                [
                    str(powershell),
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-WindowStyle",
                    "Hidden",
                    "-File",
                    str(script),
                ],
                cwd=DATA_DIR,
                creationflags=subprocess.CREATE_NO_WINDOW if IS_WIN else 0,
            )
        except OSError as exc:
            self.cfg["restart_after_update"] = False
            try:
                CONFIG_FILE.write_text(
                    json.dumps(self.cfg, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError as erro_config:
                self.append(
                    f"Não foi possível restaurar a configuração do Manager: {erro_config}\n"
                )
            if reiniciar_servidor:
                self.start()
            messagebox.showerror(
                "Atualizações",
                f"Não foi possível iniciar o instalador: {exc}",
            )
            return

        self._stop_tray_icon()
        self.destroy()

    def save_access_mode(self):
        self.cfg["mode"] = self.access_var.get()
        self.cfg["host"] = server_host(self.access_var.get())
        try:
            CONFIG_FILE.write_text(
                json.dumps(self.cfg, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            messagebox.showerror("ChronoSnap", f"Não foi possível salvar a configuração:\n{exc}")

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def servidor_em_execucao(self):
        if self.running():
            return True
        if not IS_WIN or not FROZEN:
            return False
        resultado = subprocess.run(
            ["tasklist.exe", "/FI", "IMAGENAME eq ChronoSnapServer.exe", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
        if resultado.returncode != 0:
            raise OSError(
                resultado.stderr.strip()
                or f"tasklist.exe encerrou com código {resultado.returncode}."
            )
        return any(
            linha.lstrip().lower().startswith("chronosnapserver.exe")
            for linha in resultado.stdout.splitlines()
        )

    def append(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def start(self):
        if self.running():
            return
        try:
            port = int(self.port_var.get())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            messagebox.showerror("ChronoSnap", "Porta inválida.")
            return
        host = server_host(self.access_var.get())
        if FROZEN:
            cmd = [str(SERVER_EXE)]
        else:
            cmd = [sys.executable, str(ROOT / "server" / "run_server.py")]
        if not Path(cmd[-1]).exists():
            messagebox.showerror("ChronoSnap", "Servidor não encontrado. Reinstale o sistema.")
            return
        cmd += ["--host", host, "--port", str(port)]
        self.cfg.update(mode=self.access_var.get(), host=host, port=port)
        try:
            CONFIG_FILE.write_text(
                json.dumps(self.cfg, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            messagebox.showerror("ChronoSnap", f"Não foi possível salvar a configuração:\n{exc}")
            return
        flags = subprocess.CREATE_NO_WINDOW if IS_WIN else 0
        self.proc = subprocess.Popen(
            cmd, cwd=DATA_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", creationflags=flags,
            env={**os.environ, "CHRONOSNAP_DATA": str(DATA_DIR)},
        )
        threading.Thread(target=self._pump, args=(self.proc,), daemon=True).start()
        if self.access_var.get() == "network":
            self.append(
                f"Servidor iniciado na rede local, porta {port}. "
                "Acesse pelos outros computadores usando o IPv4 deste computador.\n"
            )
        else:
            self.append(f"Servidor iniciado em http://127.0.0.1:{port}\n")

    def _pump(self, proc):
        with open(LOG_FILE, "a", encoding="utf-8") as lf:
            for line in proc.stdout:
                lf.write(line)
                lf.flush()
                self.after(0, self.append, line)

    def stop(self):
        if not self.running():
            return True
        self.proc.terminate()
        try:
            self.proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                return False
        self.append("Servidor parado.\n")
        return True

    def toggle_start_server_on_open(self):
        anterior = self.cfg.get("start_server_on_open", False)
        self.cfg["start_server_on_open"] = self.start_server_on_open_var.get()
        try:
            CONFIG_FILE.write_text(
                json.dumps(self.cfg, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            self.cfg["start_server_on_open"] = anterior
            self.start_server_on_open_var.set(anterior)
            messagebox.showerror(
                "ChronoSnap",
                f"Não foi possível salvar a inicialização automática:\n{exc}",
            )

    def toggle_tray_option(self):
        habilitado = self.minimize_to_tray_var.get()
        anterior = self.cfg.get("minimize_to_tray", False)
        self.cfg["minimize_to_tray"] = habilitado
        try:
            CONFIG_FILE.write_text(
                json.dumps(self.cfg, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            self.cfg["minimize_to_tray"] = anterior
            self.minimize_to_tray_var.set(anterior)
            messagebox.showerror(
                "ChronoSnap", f"Não foi possível salvar a configuração:\n{exc}"
            )
            return

        if habilitado:
            if not self._start_tray_icon():
                self.cfg["minimize_to_tray"] = False
                self.minimize_to_tray_var.set(False)
                try:
                    CONFIG_FILE.write_text(
                        json.dumps(self.cfg, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except OSError as exc:
                    messagebox.showerror(
                        "ChronoSnap",
                        f"Não foi possível restaurar a configuração anterior:\n{exc}",
                    )
        else:
            self._stop_tray_icon()

    def _start_tray_icon(self):
        if not IS_WIN or self.tray_icon is not None:
            return IS_WIN

        try:
            import pystray
            from PIL import Image

            with Image.open(self.icon_path) as imagem:
                imagem_tray = imagem.copy()

            menu = pystray.Menu(
                pystray.MenuItem(
                    "Exibir painel",
                    lambda *_: self.after(0, self.show_panel),
                    default=True,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "Iniciar",
                    lambda *_: self.after(0, self.start),
                    enabled=lambda _: not self.running(),
                ),
                pystray.MenuItem(
                    "Parar",
                    lambda *_: self.after(0, self.stop),
                    enabled=lambda _: self.running(),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "Parar e sair",
                    lambda *_: self.after(0, self.stop_and_exit),
                ),
            )
            self.tray_icon = pystray.Icon(
                "ChronoSnap Manager",
                imagem_tray,
                "ChronoSnap Manager",
                menu,
            )
            self.tray_icon.run_detached()
        except (ImportError, OSError, RuntimeError, NotImplementedError, tk.TclError) as exc:
            self.tray_icon = None
            messagebox.showerror(
                "ChronoSnap", f"Não foi possível iniciar o ícone da bandeja:\n{exc}"
            )
            return False
        return True

    def _restore_tray_icon(self):
        if self._start_tray_icon():
            return
        self.minimize_to_tray_var.set(False)
        self.cfg["minimize_to_tray"] = False
        try:
            CONFIG_FILE.write_text(
                json.dumps(self.cfg, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            messagebox.showerror(
                "ChronoSnap",
                f"Não foi possível salvar a configuração:\n{exc}",
            )

    def _stop_tray_icon(self):
        if self.tray_icon is None:
            return
        icon = self.tray_icon
        self.tray_icon = None
        icon.stop()

    def show_panel(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def on_minimize(self, event):
        if event.widget is not self or not self.minimize_to_tray_var.get():
            return
        self.after_idle(self._move_minimized_window_to_tray)

    def _move_minimized_window_to_tray(self):
        if self.state() != "iconic":
            return
        if self.tray_icon is None and not self._start_tray_icon():
            self.deiconify()
            return
        self.withdraw()

    def stop_and_exit(self):
        self.stop()
        self._stop_tray_icon()
        self.destroy()

    def open_browser(self):
        webbrowser.open(f"http://127.0.0.1:{self.cfg['port']}/auth/login")

    def refresh(self):
        on = self.running()
        self.status.configure(text="Em execução" if on else "Parado", fg="#067647" if on else "#b42318")
        self.btn_start.configure(state="disabled" if on else "normal")
        self.btn_stop.configure(state="normal" if on else "disabled")
        self.port_entry.configure(state="disabled" if on else "normal")
        radio_state = "disabled" if on else "normal"
        self.local_radio.configure(state=radio_state)
        self.network_radio.configure(state=radio_state)
        self.after(1000, self.refresh)

    def on_close(self):
        if self.minimize_to_tray_var.get():
            if self.tray_icon is None and not self._start_tray_icon():
                return
            self.withdraw()
            return

        if self.running():
            if not messagebox.askyesno("ChronoSnap", "O servidor está em execução. Parar e sair?"):
                return
            self.stop()
        self._stop_tray_icon()
        self.destroy()


if __name__ == "__main__":
    manager = Manager()
    manager.mainloop()
