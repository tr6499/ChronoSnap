"""Instalador visual do ChronoSnap para Linux (instala os binários compilados)."""
import os
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import subprocess

HERE = Path(__file__).resolve().parent
PAYLOAD = HERE / "payload"
BLUE, BLUE_DEEP, INK, SOFT, BG = "#0d6efd", "#0756a6", "#102a43", "#607486", "#f4f8fc"


def default_dir():
    return "/opt/ChronoSnap" if os.geteuid() == 0 else str(Path.home() / "ChronoSnap")


class Installer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ChronoSnap - Instalador")
        self.geometry("620x470")
        self.resizable(False, False)
        self.configure(bg=BG)
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, foreground=INK, font=("Sans", 10))
        s.configure("TCheckbutton", background=BG, foreground=INK, font=("Sans", 10))
        s.configure("Title.TLabel", font=("Sans", 16, "bold"), foreground=BLUE_DEEP)
        s.configure("Sub.TLabel", foreground=SOFT)
        s.configure("TButton", font=("Sans", 10), padding=8)
        s.configure("Accent.TButton", background=BLUE, foreground="white")
        s.map("Accent.TButton", background=[("active", BLUE_DEEP), ("disabled", "#9ec5fe")])
        s.configure("Horizontal.TProgressbar", background=BLUE)

        self.dir_var = tk.StringVar(value=default_dir())
        self.shortcut_var = tk.BooleanVar(value=True)
        self.postgresql_var = tk.BooleanVar(value=False)
        self.page = None
        self.show_license()

    def clear(self):
        if self.page:
            self.page.destroy()
        self.page = ttk.Frame(self, padding=24)
        self.page.pack(fill="both", expand=True)
        ttk.Label(self.page, text="ChronoSnap", style="Title.TLabel").pack(anchor="w")
        return self.page

    def show_license(self):
        p = self.clear()
        ttk.Label(p, text="GNU General Public License, versão 3", style="Sub.TLabel").pack(anchor="w", pady=(0, 8))
        bar = ttk.Frame(p)
        bar.pack(side="bottom", fill="x")
        ttk.Button(bar, text="Cancelar", command=self.destroy).pack(side="right")
        nxt = ttk.Button(bar, text="Avançar", style="Accent.TButton", command=self.show_options)
        nxt.pack(side="right", padx=8)
        try:
            content = (PAYLOAD / "LICENSE.txt").read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            content = "Arquivo da GNU GPL não encontrado. Não é possível continuar."
            nxt.configure(state="disabled")
        box = ttk.Frame(p)
        box.pack(fill="both", expand=True)
        txt = tk.Text(box, wrap="word", font=("Sans", 9), bg="white", fg=INK, relief="solid", bd=1)
        sb = ttk.Scrollbar(box, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        txt.insert("1.0", content)
        txt.configure(state="disabled")

    def show_options(self):
        p = self.clear()
        ttk.Label(p, text="Local de instalação", style="Sub.TLabel").pack(anchor="w", pady=(0, 18))
        row = ttk.Frame(p)
        row.pack(fill="x", pady=(4, 12))
        ttk.Entry(row, textvariable=self.dir_var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Procurar...", command=self.browse).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(p, text="Criar atalho do Manager na área de trabalho", variable=self.shortcut_var).pack(anchor="w")
        ttk.Checkbutton(
            p,
            text="Instalar servidor PostgreSQL local (requer internet e privilégios administrativos)",
            variable=self.postgresql_var,
        ).pack(anchor="w", pady=(8, 0))
        ttk.Label(
            p, text="O ChronoSnap é instalado já compilado. O PostgreSQL local é opcional e instalado pelos repositórios do sistema.\n"
                    "Se já houver PostgreSQL ou configuração existente, ajuste a conexão em Administração > Banco de dados.\n"
                    "Em atualizações, os dados do banco são preservados.",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=12)
        bar = ttk.Frame(p)
        bar.pack(side="bottom", fill="x")
        ttk.Button(bar, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="Instalar", style="Accent.TButton", command=self.start_install).pack(side="right", padx=8)

    def browse(self):
        cur = Path(self.dir_var.get())
        d = filedialog.askdirectory(initialdir=str(cur if cur.exists() else Path.home()))
        if d:
            p = Path(d)
            self.dir_var.set(str(p / "ChronoSnap") if any(p.iterdir()) and p.name != "ChronoSnap" else d)

    def start_install(self):
        raw = self.dir_var.get().strip()
        if not raw:
            return
        self.target = Path(raw).expanduser().resolve()
        p = self.clear()
        self.status = ttk.Label(p, text="Instalando...", style="Sub.TLabel")
        self.status.pack(anchor="w", pady=(0, 8))
        self.progress = ttk.Progressbar(p, mode="determinate", maximum=100)
        self.progress.pack(fill="x")
        self.close_btn = ttk.Button(p, text="Aguarde...", state="disabled", command=self.destroy)
        self.close_btn.pack(side="bottom", anchor="e")
        box = ttk.Frame(p)
        box.pack(fill="both", expand=True, pady=12)
        self.log = tk.Text(box, state="disabled", font=("Monospace", 9), bg="white", fg=INK, relief="solid", bd=1)
        self.log.pack(fill="both", expand=True)
        self.protocol("WM_DELETE_WINDOW", lambda: None)
        threading.Thread(target=self.run_install, daemon=True).start()

    def ui(self, text=None, pct=None, line=None):
        def apply():
            if text:
                self.status.configure(text=text)
            if pct is not None:
                self.progress.configure(value=pct)
            if line:
                self.log.configure(state="normal")
                self.log.insert("end", line + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
        self.after(0, apply)

    def run_install(self):
        try:
            t = self.target
            t.mkdir(parents=True, exist_ok=True)
            self.ui(pct=5, line=f"Destino: {t}")
            for i, name in enumerate(("server", "manager")):
                self.ui(f"Copiando {name}...", 10 + i * 40, f"Copiando {name}")
                shutil.copytree(PAYLOAD / name, t / name, dirs_exist_ok=True)
            (t / "data").mkdir(exist_ok=True)
            shutil.copy2(PAYLOAD / "LICENSE.txt", t / "LICENSE.txt")
            if self.postgresql_var.get():
                try:
                    self.install_postgresql()
                except Exception as exc:
                    self.ui(
                        line=f"AVISO: o PostgreSQL não foi instalado ({exc}). "
                        "O ChronoSnap usará SQLite até que o PostgreSQL seja configurado."
                    )
            self.ui("Criando atalhos...", 90)
            self.make_shortcuts(t)
            self.ui("Instalação concluída.", 100, "Concluído com sucesso.")
            self.after(0, lambda: self.finish(True))
        except Exception as exc:
            self.ui("Falha na instalação.", line=f"ERRO: {exc}")
            self.after(0, lambda: self.finish(False))

    def install_postgresql(self):
        script = HERE / "install_postgresql.sh"
        if not script.is_file():
            raise FileNotFoundError(
                "O script de instalação do PostgreSQL não foi incluído no pacote."
            )
        argumentos = [str(script), str(self.target / "data")]
        if os.geteuid() == 0:
            comando = argumentos
        else:
            pkexec = shutil.which("pkexec")
            if not pkexec:
                raise RuntimeError(
                    "O pkexec não está disponível. Execute o instalador como "
                    "administrador ou instale o PostgreSQL manualmente."
                )
            comando = [pkexec, *argumentos]

        self.ui("Instalando PostgreSQL pelos repositórios oficiais...")
        processo = subprocess.Popen(
            comando,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for linha in processo.stdout:
            self.ui(line=linha.rstrip())
        codigo = processo.wait()
        if codigo:
            raise RuntimeError(
                f"A instalação local do PostgreSQL falhou (código {codigo})."
            )

    def make_shortcuts(self, t):
        for exe in (t / "server" / "ChronoSnapServer", t / "manager" / "ChronoSnapManager"):
            if exe.exists():
                exe.chmod(0o755)
        launcher = t / "chronosnap-manager.sh"
        launcher.write_text(f'#!/bin/sh\nexec "{t}/manager/ChronoSnapManager" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
        entry = ("[Desktop Entry]\nType=Application\nName=ChronoSnap Manager\n"
                 f'Exec="{launcher}"\nPath={t}\nTerminal=false\nCategories=Utility;\n')
        apps = Path.home() / ".local" / "share" / "applications"
        apps.mkdir(parents=True, exist_ok=True)
        (apps / "chronosnap-manager.desktop").write_text(entry, encoding="utf-8")
        if self.shortcut_var.get():
            desk = Path.home() / "Desktop"
            if desk.exists():
                f = desk / "chronosnap-manager.desktop"
                f.write_text(entry, encoding="utf-8")
                f.chmod(0o755)
        uninstall = t / "desinstalar.sh"
        uninstall.write_text(
            "#!/bin/sh\n# Remove o sistema, mantendo a pasta data (banco e configurações).\n"
            f'rm -rf "{t}/server" "{t}/manager" "{t}/chronosnap-manager.sh" "{t}/LICENSE.txt"\n'
            'rm -f "$HOME/.local/share/applications/chronosnap-manager.desktop" "$HOME/Desktop/chronosnap-manager.desktop"\n'
            f'echo "Removido. Dados preservados em {t}/data"\n', encoding="utf-8")
        uninstall.chmod(0o755)

    def finish(self, ok):
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.close_btn.configure(text="Fechar", state="normal")
        if ok and messagebox.askyesno("ChronoSnap", "Instalação concluída. Abrir o Manager agora?"):
            subprocess.Popen([str(self.target / "manager" / "ChronoSnapManager")], cwd=self.target)
            self.destroy()
        elif not ok:
            messagebox.showerror("ChronoSnap", "A instalação falhou. Verifique o log.")


if __name__ == "__main__":
    Installer().mainloop()
