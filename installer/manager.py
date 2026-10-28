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
    # Sem console (build compilado), erros de inicialização seriam invisíveis.
    import tempfile
    import traceback
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    log = Path(tempfile.gettempdir()) / "chronosnap-manager-error.log"
    try:
        log.write_text(text, encoding="utf-8")
    except OSError:
        pass
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

CONFIG_FILE = DATA_DIR / "manager.json"
LOG_FILE = DATA_DIR / "logs" / "server.log"
BLUE, BLUE_DEEP, INK, SOFT, BG = "#0d6efd", "#0756a6", "#102a43", "#607486", "#f4f8fc"
APP_VERSION = "1.0.3"
GNU_LICENSE_URL = "https://www.gnu.org/licenses/gpl-3.0.html"


def load_config():
    cfg = {"mode": "local", "port": 8000, "minimize_to_tray": False}
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
    return cfg


def server_host(mode):
    return "0.0.0.0" if mode == "network" else "127.0.0.1"


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
        self.geometry("680x500")
        self.configure(bg=BG)
        self.proc = None
        self.cfg = load_config()
        self.access_var = tk.StringVar(value=self.cfg["mode"])
        self.minimize_to_tray_var = tk.BooleanVar(
            value=self.cfg["minimize_to_tray"] and IS_WIN
        )
        self.tray_icon = None
        self._style()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Unmap>", self.on_minimize)
        if self.minimize_to_tray_var.get():
            self.after_idle(self._restore_tray_icon)
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
        license_window.geometry("760x680")
        license_window.minsize(600, 480)
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
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.append("Servidor parado.\n")

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
    Manager().mainloop()
