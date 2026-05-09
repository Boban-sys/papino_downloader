"""
╔══════════════════════════════════════════════════════════════╗
║           Papino Downloader — yt-dlp + CustomTkinter  ║
║                         v1.1.0                               ║
╚══════════════════════════════════════════════════════════════╝

Dipendenze da installare:
    pip install yt-dlp customtkinter requests

FFmpeg (necessario per conversione audio e mux video+audio):
    • Windows : https://ffmpeg.org/download.html  → aggiungi al PATH
    • macOS   : brew install ffmpeg
    • Linux   : sudo apt install ffmpeg
"""

import os
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
import requests
import yt_dlp


# ─────────────────────────────────────────────────────────────────────────────
#  VERSIONE & GITHUB
#  Queste costanti vanno aggiornate ad ogni rilascio.
# ─────────────────────────────────────────────────────────────────────────────

__version__ = "1.1.0"
"""
Versione corrente dell'applicazione.
Il checker confronta questa stringa con __version__ del file remoto su GitHub.
Formato: MAJOR.MINOR.PATCH  (semantic versioning)
"""

# URL del file Python "grezzo" sul branch GitHub da monitorare.
# ⚠ Sostituisci con il tuo utente, repository e branch reali.
GITHUB_RAW_URL = (
    "https://raw.githubusercontent.com/TUO_UTENTE/TUO_REPO/main/yt_downloader.py"
)

# URL della pagina release (mostrata all'utente nel dialog di aggiornamento)
GITHUB_RELEASES_URL = (
    "https://github.com/TUO_UTENTE/TUO_REPO/releases"
)

# Timeout (secondi) per le richieste HTTP al server GitHub
GITHUB_TIMEOUT = 8


# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURAZIONE TEMA
# ─────────────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ─────────────────────────────────────────────────────────────────────────────
#  FORMATO OPTIONS
#  Struttura: label visibile → (yt_dlp_format_string, estensione_finale)
#
#  • yt_dlp_format_string  : istruzione a yt-dlp su quali stream scaricare
#                            (es. "bestvideo+bestaudio" → il miglior video
#                            separato + il miglior audio separato, poi FFmpeg
#                            li unisce nel contenitore richiesto)
#  • estensione_finale     : contenitore di output finale o codec audio
#
#  Contenitori video supportati da FFmpeg (e quindi da yt-dlp):
#      mp4  → H.264/AAC  — massima compatibilità
#      mkv  → contenitore aperto, supporta qualsiasi codec
#      avi  → legacy, compatibile con software più datati
# ─────────────────────────────────────────────────────────────────────────────
FORMAT_OPTIONS: dict[str, tuple[str, str]] = {
    # ── VIDEO MP4 ─────────────────────────────────────────────────────────
    # Preferisce esplicitamente bestaudio[ext=m4a] (= AAC) per garantire
    # la compatibilità del contenitore MP4.  Fallback a bestaudio generico
    # se m4a non è disponibile (FFmpeg ricoderà in AAC via postprocessor_args).
    "🎬  Video — Migliore qualità  [MP4]":  ("bestvideo+bestaudio[ext=m4a]/bestvideo+bestaudio/best",                              "mp4"),
    "🎬  Video — 1080p Full HD     [MP4]":  ("bestvideo[height<=1080]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]",  "mp4"),
    "🎬  Video — 720p HD           [MP4]":  ("bestvideo[height<=720]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]",    "mp4"),
    "🎬  Video — 480p SD           [MP4]":  ("bestvideo[height<=480]+bestaudio[ext=m4a]/bestvideo[height<=480]+bestaudio/best[height<=480]",    "mp4"),
    # ── VIDEO MKV ─────────────────────────────────────────────────────────
    # MKV supporta nativamente Opus, VP9, AV1: nessuna preferenza sul codec audio.
    "🎞  Video — Migliore qualità  [MKV]":  ("bestvideo+bestaudio/best",                              "mkv"),
    "🎞  Video — 1080p Full HD     [MKV]":  ("bestvideo[height<=1080]+bestaudio/best[height<=1080]",  "mkv"),
    "🎞  Video — 720p HD           [MKV]":  ("bestvideo[height<=720]+bestaudio/best[height<=720]",    "mkv"),
    # ── VIDEO AVI ─────────────────────────────────────────────────────────
    # AVI è un formato legacy: FFmpeg ricoderà comunque l'audio incompatibile.
    "📼  Video — Migliore qualità  [AVI]":  ("bestvideo+bestaudio[ext=m4a]/bestvideo+bestaudio/best",                              "avi"),
    "📼  Video — 1080p Full HD     [AVI]":  ("bestvideo[height<=1080]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]",  "avi"),
    "📼  Video — 720p HD           [AVI]":  ("bestvideo[height<=720]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]",    "avi"),
    # ── SOLO AUDIO ────────────────────────────────────────────────────────
    "🎵  Solo audio — MP3  (320 kbps)":     ("bestaudio/best",                                        "mp3"),
    "🎵  Solo audio — M4A (AAC originale)": ("bestaudio[ext=m4a]/bestaudio/best",                     "m4a"),
    "🎵  Solo audio — WAV (lossless)":      ("bestaudio/best",                                        "wav"),
}

# Estensioni audio — usate per distinguere i post-processori FFmpeg
_AUDIO_EXTS = {"mp3", "m4a", "wav"}

# ─────────────────────────────────────────────────────────────────────────────
#  RILEVAMENTO FFMPEG
#
#  Invece di shutil.which() (che legge il PATH al momento dell'import e può
#  non riflettere le variabili di sistema aggiornate su Windows), eseguiamo
#  direttamente "ffmpeg -version" tramite subprocess.
#
#  subprocess.run con stdout/stderr PIPE e check=False non lancia eccezioni:
#    • returncode == 0  → FFmpeg trovato e funzionante
#    • FileNotFoundError → eseguibile non trovato nel PATH
#    • qualsiasi altro errore → trattiamo come assente
# ─────────────────────────────────────────────────────────────────────────────
def _detect_ffmpeg() -> bool:
    """
    Prova a eseguire 'ffmpeg -version' per verificare se FFmpeg è
    installato e raggiungibile nel PATH corrente del processo.

    Ritorna True se il comando ha successo (returncode 0), False altrimenti.

    Perché subprocess invece di shutil.which():
      shutil.which() controlla solo se un file eseguibile esiste nel PATH,
      ma su Windows il PATH viene letto all'avvio del processo Python e
      potrebbe non includere le variabili di sistema aggiunte di recente.
      subprocess.run() usa il PATH live del sistema operativo al momento
      della chiamata, risultando più affidabile.
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,          # non bloccare l'avvio per più di 5s
        )
        return result.returncode == 0
    except FileNotFoundError:
        # ffmpeg non trovato nel PATH
        return False
    except Exception:
        # timeout o altro errore imprevisto
        return False


_FFMPEG_OK: bool = _detect_ffmpeg()


# ─────────────────────────────────────────────────────────────────────────────
#  CLASSE PRINCIPALE
# ─────────────────────────────────────────────────────────────────────────────
class PapinoDownloader(ctk.CTk):
    """
    Finestra principale dell'applicazione.

    Eredita da ctk.CTk (CustomTkinter root window) e gestisce:
    - Layout dell'interfaccia grafica
    - Raccolta dell'input utente (URL, formato, cartella di destinazione)
    - Avvio del download su thread separato (non blocca la UI)
    - Aggiornamento in tempo reale di barra di avanzamento e log
    - Controllo aggiornamenti dal repository GitHub configurato
    """

    def __init__(self):
        super().__init__()

        self.title(f"YT Downloader  v{__version__}")
        self.geometry("820x680")
        self.resizable(True, True)
        self.minsize(700, 580)

        # Thread di download attivo (None se idle)
        self._download_thread: threading.Thread | None = None

        self._build_ui()

        # Mostra banner di avviso se FFmpeg non è installato.
        # Chiamato DOPO _build_ui() perché usa il log box.
        if not _FFMPEG_OK:
            self._show_ffmpeg_warning()

    # ─────────────────────────────────────────────────────────────────────
    #  UI BUILDER
    # ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        """
        Costruisce e posiziona tutti i widget dell'interfaccia.
        Chiamato una sola volta nel costruttore.

        Layout (dall'alto verso il basso):
            row 0 → Header (titolo, versione, bottone update)
            row 1 → Frame URL
            row 2 → Frame formato
            row 3 → Frame cartella di destinazione
            row 4 → Pulsante Download
            row 5 → Barra di avanzamento
            row 6 → Etichetta stato
            row 7 → Box log (espandibile verticalmente)
        """
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(8, weight=1)  # il log si espande verticalmente

        # ── 0. HEADER ─────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=30, pady=(24, 8))
        header.grid_columnconfigure(0, weight=1)

        # Titolo + sottotitolo (colonna sinistra)
        titles = ctk.CTkFrame(header, fg_color="transparent")
        titles.grid(row=0, column=0, rowspan=2, sticky="w")

        ctk.CTkLabel(
            titles,
            text="⬇  Papino Downloader",
            font=ctk.CTkFont(family="Helvetica", size=26, weight="bold"),
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            titles,
            text="Scarica video o audio direttamente dal tuo canale YouTube",
            font=ctk.CTkFont(size=12),
            text_color="gray60",
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        # Bottone "Controlla aggiornamenti" (colonna destra)
        self.update_btn = ctk.CTkButton(
            header,
            text="🔄  Aggiornamenti",
            width=160,
            height=34,
            font=ctk.CTkFont(size=12),
            fg_color="gray25",
            hover_color="gray35",
            command=self._check_update_async,   # avvia check su thread
        )
        self.update_btn.grid(row=0, column=1, sticky="ne")

        # Badge versione sotto il bottone
        ctk.CTkLabel(
            header,
            text=f"v{__version__}",
            font=ctk.CTkFont(size=10),
            text_color="gray50",
        ).grid(row=1, column=1, sticky="e", pady=(2, 0))

        # ── 1. URL INPUT ──────────────────────────────────────────────────
        url_frame = self._make_section_frame(row=1, label="🔗  URL del video o playlist")
        self.url_var = tk.StringVar()
        ctk.CTkEntry(
            url_frame,
            textvariable=self.url_var,
            placeholder_text="https://www.youtube.com/watch?v=...",
            height=40,
            font=ctk.CTkFont(size=13),
        ).pack(fill="x", padx=16, pady=(0, 14))

        # ── 2. FORMATO ────────────────────────────────────────────────────
        fmt_frame = self._make_section_frame(row=2, label="🎛  Formato di output")
        self.format_var = tk.StringVar(value=list(FORMAT_OPTIONS.keys())[0])
        ctk.CTkOptionMenu(
            fmt_frame,
            variable=self.format_var,
            values=list(FORMAT_OPTIONS.keys()),
            height=38,
            font=ctk.CTkFont(size=12),
            dynamic_resizing=False,
            width=580,
        ).pack(anchor="w", padx=16, pady=(0, 14))

        # ── 3. OPZIONI AGGIUNTIVE ─────────────────────────────────────────
        opt_frame = self._make_section_frame(row=3, label="⚙️  Opzioni")
        opt_inner = ctk.CTkFrame(opt_frame, fg_color="transparent")
        opt_inner.pack(fill="x", padx=16, pady=(0, 14))

        # Checkbox: scarica solo il video singolo oppure l'intera playlist.
        # Quando l'URL contiene un parametro &list=..., YouTube lo tratta
        # come playlist. Con noplaylist=True yt-dlp ignora la playlist
        # e scarica solo il video indicato da ?v=...
        self.only_video_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            opt_inner,
            text="Scarica solo il video singolo (ignora playlist)",
            variable=self.only_video_var,
            font=ctk.CTkFont(size=13),
        ).pack(anchor="w", pady=(0, 6))

        # Indicatore FFmpeg — informa l'utente sullo stato di FFmpeg
        # e cambia colore in base alla disponibilità
        ffmpeg_color  = "#2ecc71" if _FFMPEG_OK else "#e74c3c"
        ffmpeg_icon   = "✔" if _FFMPEG_OK else "✘"
        ffmpeg_text   = f"{ffmpeg_icon}  FFmpeg {'rilevato' if _FFMPEG_OK else 'NON trovato — qualità ridotta, conversione audio non disponibile'}"
        ctk.CTkLabel(
            opt_inner,
            text=ffmpeg_text,
            font=ctk.CTkFont(size=12),
            text_color=ffmpeg_color,
            anchor="w",
        ).pack(anchor="w")

        # ── 4. CARTELLA DI DESTINAZIONE ───────────────────────────────────
        dest_frame = self._make_section_frame(row=4, label="📁  Cartella di destinazione")
        dest_row = ctk.CTkFrame(dest_frame, fg_color="transparent")
        dest_row.pack(fill="x", padx=16, pady=(0, 14))
        dest_row.grid_columnconfigure(0, weight=1)

        self.dest_var = tk.StringVar(value=os.path.expanduser("~/Downloads"))
        ctk.CTkEntry(
            dest_row,
            textvariable=self.dest_var,
            height=38,
            font=ctk.CTkFont(size=12),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))

        ctk.CTkButton(
            dest_row,
            text="Sfoglia",
            width=90,
            height=38,
            command=self._browse_folder,
        ).grid(row=0, column=1)

        # ── 5. PULSANTE DOWNLOAD ──────────────────────────────────────────
        self.download_btn = ctk.CTkButton(
            self,
            text="⬇  Avvia Download",
            height=46,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._start_download,
        )
        self.download_btn.grid(row=5, column=0, sticky="ew", padx=30, pady=(16, 10))

        # ── 6. PROGRESS BAR ───────────────────────────────────────────────
        self.progress_bar = ctk.CTkProgressBar(self, height=10)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=6, column=0, sticky="ew", padx=30, pady=(0, 6))

        # ── 7. ETICHETTA STATO ────────────────────────────────────────────
        self.status_label = ctk.CTkLabel(
            self,
            text="In attesa…",
            font=ctk.CTkFont(size=12),
            text_color="gray60",
            anchor="w",
        )
        self.status_label.grid(row=7, column=0, sticky="ew", padx=32, pady=(0, 4))

        # ── 8. LOG BOX ────────────────────────────────────────────────────
        log_frame = ctk.CTkFrame(self, corner_radius=10)
        log_frame.grid(row=8, column=0, sticky="nsew", padx=30, pady=(0, 22))
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            log_frame,
            text="Log",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="gray55",
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(8, 2))

        self.log_box = ctk.CTkTextbox(
            log_frame,
            font=ctk.CTkFont(family="Courier", size=11),
            corner_radius=0,
            wrap="word",
            state="disabled",
        )
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=2, pady=(0, 2))

    # ─────────────────────────────────────────────────────────────────────
    #  HELPER UI
    # ─────────────────────────────────────────────────────────────────────

    def _make_section_frame(self, row: int, label: str) -> ctk.CTkFrame:
        """
        Crea un frame con etichetta intestazione e lo posiziona
        nella griglia principale alla riga specificata.

        Parametri:
            row   : riga della griglia root in cui inserire il frame
            label : testo dell'intestazione della sezione

        Ritorna:
            Il frame interno (dove aggiungere i widget figli).
        """
        outer = ctk.CTkFrame(self, corner_radius=12)
        outer.grid(row=row, column=0, sticky="ew", padx=30, pady=5)
        outer.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            outer,
            text=label,
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).pack(fill="x", padx=16, pady=(12, 6))

        return outer

    def _browse_folder(self):
        """
        Apre il dialog nativo del sistema operativo per scegliere
        la cartella di destinazione.  Aggiorna self.dest_var.
        """
        folder = filedialog.askdirectory(
            title="Seleziona cartella di destinazione",
            initialdir=self.dest_var.get(),
        )
        if folder:
            self.dest_var.set(folder)

    def _show_ffmpeg_warning(self):
        """
        Mostra un avviso nel log (e un messagebox) se FFmpeg non è
        presente nel PATH di sistema.

        Senza FFmpeg, yt-dlp non può:
          • unire stream video+audio separati (tipici dei video HD)
          • convertire l'audio in MP3 / WAV

        Il download viene eseguito comunque usando i formati pre-muxati
        (video e audio già uniti) che YouTube fornisce, ma la qualità
        massima disponibile potrebbe essere inferiore (es. 720p invece
        di 1080p, e solo M4A per l'audio).
        """
        self._log("⚠  FFmpeg NON trovato nel PATH di sistema.")
        self._log("   Qualità video limitata ai formati pre-muxati (max 720p su YouTube).")
        self._log("   Conversione audio (MP3/WAV) non disponibile.")
        self._log("   → Installa FFmpeg: https://ffmpeg.org/download.html")
        messagebox.showwarning(
            "FFmpeg non trovato",
            "FFmpeg non è installato o non è nel PATH.\n\n"
            "Senza FFmpeg:\n"
            "  • La qualità video sarà limitata (max ~720p pre-muxato)\n"
            "  • La conversione in MP3/WAV non è disponibile\n\n"
            "Installa FFmpeg e riavvia l'applicazione per abilitare\n"
            "tutte le funzionalità.\n\n"
            "https://ffmpeg.org/download.html",
        )

    # ─────────────────────────────────────────────────────────────────────
    #  LOG & STATUS  (thread-safe via self.after)
    # ─────────────────────────────────────────────────────────────────────

    def _log(self, msg: str):
        """
        Aggiunge una riga al box di log in modo thread-safe.

        Tkinter non è thread-safe: qualsiasi modifica ai widget
        deve avvenire nel main thread.  self.after(0, fn) accoda
        fn alla coda degli eventi del main thread.

        Parametri:
            msg : testo da appendere al log
        """
        def _write():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.after(0, _write)

    def _set_status(self, text: str):
        """Aggiorna l'etichetta di stato (thread-safe)."""
        self.after(0, lambda: self.status_label.configure(text=text))

    def _set_progress(self, value: float):
        """
        Aggiorna la barra di avanzamento (thread-safe).

        Parametri:
            value : float tra 0.0 (0 %) e 1.0 (100 %)
        """
        self.after(0, lambda: self.progress_bar.set(value))

    # ─────────────────────────────────────────────────────────────────────
    #  DOWNLOAD — AVVIO
    # ─────────────────────────────────────────────────────────────────────

    def _start_download(self):
        """
        Callback del pulsante «Avvia Download».

        Responsabilità:
            1. Valida i campi obbligatori (URL, cartella)
            2. Legge il formato selezionato dall'OptionMenu
            3. Disabilita il pulsante per evitare doppi click
            4. Avvia _run_download su un thread daemon separato
               così la UI rimane reattiva durante il download
        """
        url  = self.url_var.get().strip()
        dest = self.dest_var.get().strip()
        fmt_label = self.format_var.get()

        if not url:
            messagebox.showwarning("URL mancante", "Inserisci l'URL del video da scaricare.")
            return
        if not dest or not os.path.isdir(dest):
            messagebox.showwarning("Cartella non valida", "La cartella di destinazione non esiste.")
            return

        fmt_string, ext = FORMAT_OPTIONS[fmt_label]
        only_video = self.only_video_var.get()  # True → noplaylist

        self._set_progress(0)
        self._set_status("Avvio download…")
        self.download_btn.configure(state="disabled", text="⏳  Download in corso…")

        self._download_thread = threading.Thread(
            target=self._run_download,
            args=(url, dest, fmt_string, ext, only_video),
            daemon=True,
        )
        self._download_thread.start()

    # ─────────────────────────────────────────────────────────────────────
    #  DOWNLOAD — CORE  (thread separato)
    # ─────────────────────────────────────────────────────────────────────

    def _run_download(self, url: str, dest: str, fmt_string: str, ext: str, only_video: bool):
        """
        Esegue il download tramite yt-dlp.  Gira in thread separato.

        Parametri:
            url        : URL del video / playlist YouTube
            dest       : cartella di destinazione
            fmt_string : stringa formato yt-dlp (es. "bestvideo+bestaudio")
            ext        : estensione finale (mp4 | mkv | avi | mp3 | m4a | wav)
            only_video : se True imposta noplaylist=True → scarica solo il
                         video singolo anche se l'URL contiene &list=...

        Gestione FFmpeg mancante:
            yt-dlp usa FFmpeg per unire stream video e audio separati
            e per convertire i codec.  Se FFmpeg non è disponibile:
            • Video → si usa "best" che scarica uno stream pre-muxato
                      (video+audio già uniti da YouTube, spesso max 720p)
            • Audio → si usa "bestaudio[ext=m4a]/bestaudio" e si salva
                      il file as-is senza conversione di codec
        """
        audio_only = ext in _AUDIO_EXTS

        # ── Fallback se FFmpeg non è installato ───────────────────────────
        if not _FFMPEG_OK:
            if audio_only:
                # Senza FFmpeg non possiamo convertire: forziamo M4A nativo
                self._log("⚠  FFmpeg assente: salvo in M4A nativo (conversione MP3/WAV non disponibile)")
                fmt_string = "bestaudio[ext=m4a]/bestaudio/best"
                ext = "m4a"
                audio_only = True
            else:
                # Senza FFmpeg prendiamo il miglior formato pre-muxato disponibile
                self._log("⚠  FFmpeg assente: uso formato pre-muxato (qualità potrebbe essere < 1080p)")
                # best[ext=mp4] → preferisce mp4 già pronto; fallback a qualsiasi best
                fmt_string = "best[ext=mp4]/best[ext=webm]/best"
                # Non possiamo forzare il contenitore senza FFmpeg, usiamo mp4
                ext = "mp4"

        # ── Template nome file ────────────────────────────────────────────
        outtmpl = os.path.join(dest, "%(title)s [%(id)s].%(ext)s")

        # ── Post-processori (solo audio con FFmpeg) ───────────────────────
        postprocessors = []
        if audio_only and _FFMPEG_OK:
            postprocessors.append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": ext,
                "preferredquality": "320" if ext == "mp3" else "0",
            })

        ydl_opts = {
            "format":               fmt_string,
            "outtmpl":              outtmpl,
            "postprocessors":       postprocessors,
            # merge_output_format: contenitore finale per i video.
            # Ignorato se FFmpeg non è presente (non c'è merge da fare).
            "merge_output_format":  ext if (not audio_only and _FFMPEG_OK) else None,
            # noplaylist=True → scarica solo il video singolo ignorando &list=
            # noplaylist=False → scarica l'intera playlist se presente
            "noplaylist":           only_video,
            "progress_hooks":       [self._progress_hook],
            "logger":               _YTDLLogger(self._log),
            "quiet":                True,
            "no_warnings":          False,
        }

        # ── Rete di sicurezza audio per MP4 e AVI ────────────────────────
        # Se nonostante la preferenza per m4a yt-dlp seleziona uno stream
        # audio Opus (non supportato da MP4/AVI), questo argomento dice a
        # FFmpeg di ricodificarlo in AAC durante il merge.
        # Per MKV non è necessario: Opus è un codec nativo del contenitore.
        if not audio_only and _FFMPEG_OK and ext in ("mp4", "avi"):
            ydl_opts["postprocessor_args"] = {
                # "merger" indica gli argomenti passati all'istanza FFmpeg
                # che esegue il merge dei due stream (video + audio).
                # -c:v copy → copia il video senza ricodifica (veloce, no perdita)
                # -c:a aac  → ricodifica l'audio in AAC se necessario
                "merger": ["-c:v", "copy", "-c:a", "aac"]
            }

        # Rimuove la chiave None per non passare valori non validi a yt-dlp
        if ydl_opts["merge_output_format"] is None:
            del ydl_opts["merge_output_format"]

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                playlist_mode = "no-playlist" if only_video else "playlist"
                self._log(f"→ Avvio download: {url}")
                self._log(f"   Formato: {ext.upper()}  |  FFmpeg: {'✔' if _FFMPEG_OK else '✘'}  |  Modalità: {playlist_mode}")
                ydl.download([url])

            self._log("✅  Download completato!")
            self._set_status("✅  Completato")
            self._set_progress(1.0)
            self.after(0, lambda: messagebox.showinfo(
                "Download completato",
                f"File salvato in:\n{dest}",
            ))

        except yt_dlp.utils.DownloadError as e:
            self._log(f"❌  Errore download: {e}")
            self._set_status("❌  Errore durante il download")
            # e=e congela il valore nel default arg della lambda:
            # in Python 3 la variabile 'e' viene eliminata all'uscita
            # del blocco except, quindi la lambda la perderebbe senza questo trick.
            self.after(0, lambda e=e: messagebox.showerror("Errore download", str(e)))

        except Exception as e:
            self._log(f"❌  Errore imprevisto: {e}")
            self._set_status(f"❌  Errore: {e}")

        finally:
            self.after(0, lambda: self.download_btn.configure(
                state="normal",
                text="⬇  Avvia Download",
            ))

    # ─────────────────────────────────────────────────────────────────────
    #  PROGRESS HOOK
    # ─────────────────────────────────────────────────────────────────────

    def _progress_hook(self, d: dict):
        """
        Callback invocata da yt-dlp ad ogni chunk scaricato.

        Chiavi principali del dizionario d:
            status               → "downloading" | "finished" | "error"
            downloaded_bytes     → byte scaricati finora
            total_bytes          → dimensione totale (può essere assente)
            total_bytes_estimate → stima quando la dimensione è ignota
            speed                → byte/s  (può essere None)
            eta                  → secondi rimanenti (può essere None)
            filename             → percorso del file in scrittura
        """
        status = d.get("status")

        if status == "downloading":
            downloaded = d.get("downloaded_bytes", 0)
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)

            if total > 0:
                self._set_progress(downloaded / total)

            speed = d.get("speed") or 0
            eta   = d.get("eta")   or 0
            pct   = (downloaded / total * 100) if total else 0
            self._set_status(
                f"⬇  {pct:.1f}%  —  {_fmt_bytes(speed)}/s  —  ETA {_fmt_time(eta)}"
            )

        elif status == "finished":
            fname = os.path.basename(d.get("filename", ""))
            self._log(f"   ✔ Scaricato: {fname}")
            self._set_status("🔄  Post-elaborazione (FFmpeg)…")

        elif status == "error":
            self._log("❌  Errore segnalato dal progress hook")

    # ─────────────────────────────────────────────────────────────────────
    #  GITHUB UPDATE CHECKER
    # ─────────────────────────────────────────────────────────────────────

    def _check_update_async(self):
        """
        Punto d'ingresso del pulsante «🔄 Aggiornamenti».

        Disabilita il bottone e avvia _check_update_worker su un
        thread daemon separato per non bloccare la UI durante la
        richiesta HTTP a GitHub.
        """
        self.update_btn.configure(state="disabled", text="⏳  Controllo…")
        threading.Thread(target=self._check_update_worker, daemon=True).start()

    def _check_update_worker(self):
        """
        Worker (thread separato) per il controllo aggiornamenti.

        Flusso:
            1. Scarica il file .py grezzo dal branch GitHub configurato
            2. Estrae la riga  __version__ = "X.Y.Z"  con regex
            3. Confronta la versione remota con __version__ locale
               usando _parse_version() per comparazione numerica corretta
            4a. Versione più recente trovata → chiama _prompt_update()
            4b. Già aggiornati → mostra messaggio informativo
            5. Gestisce errori di rete, timeout, HTTP e parsing

        Nota: tutte le interazioni con la UI usano self.after(0, ...)
        perché questo metodo gira in un thread separato.
        """
        try:
            self._log(f"🔍  Controllo aggiornamenti su: {GITHUB_RAW_URL}")
            response = requests.get(GITHUB_RAW_URL, timeout=GITHUB_TIMEOUT)
            response.raise_for_status()   # lancia HTTPError per 4xx/5xx

            remote_src = response.text

            # Cerca  __version__ = "1.2.3"  (con virgolette singole o doppie)
            match = re.search(
                r'^__version__\s*=\s*["\']([^"\']+)["\']',
                remote_src,
                re.MULTILINE,
            )
            if not match:
                raise ValueError("Tag __version__ non trovato nel file remoto.")

            remote_ver = match.group(1)
            self._log(f"   Versione locale : {__version__}")
            self._log(f"   Versione remota : {remote_ver}")

            if _parse_version(remote_ver) > _parse_version(__version__):
                # Nuova versione disponibile: mostra il dialog nel main thread
                self.after(0, lambda: self._prompt_update(remote_ver, remote_src))
            else:
                self._log("✅  L'applicazione è già alla versione più recente.")
                self.after(0, lambda: messagebox.showinfo(
                    "Nessun aggiornamento",
                    f"Sei già alla versione più recente ({__version__}).",
                ))

        except requests.exceptions.ConnectionError:
            self._log("❌  Impossibile connettersi a GitHub. Verifica la connessione.")
            self.after(0, lambda: messagebox.showerror(
                "Errore di rete",
                "Impossibile connettersi a GitHub.\nVerifica la connessione Internet.",
            ))

        except requests.exceptions.Timeout:
            self._log(f"❌  Timeout dopo {GITHUB_TIMEOUT}s. GitHub non risponde.")
            self.after(0, lambda: messagebox.showerror(
                "Timeout",
                f"GitHub non ha risposto entro {GITHUB_TIMEOUT} secondi.",
            ))

        except requests.exceptions.HTTPError as e:
            code = e.response.status_code
            self._log(f"❌  HTTP {code}: repository o branch non trovato.")
            self.after(0, lambda code=code: messagebox.showerror(
                f"Errore HTTP {code}",
                "Repository o branch non raggiungibile.\n"
                "Verifica le costanti GITHUB_RAW_URL nel codice.",
            ))

        except ValueError as e:
            self._log(f"❌  Errore parsing versione: {e}")
            self.after(0, lambda e=e: messagebox.showerror("Errore", str(e)))

        finally:
            # Ripristina il bottone in ogni caso
            self.after(0, lambda: self.update_btn.configure(
                state="normal", text="🔄  Aggiornamenti"
            ))

    def _prompt_update(self, remote_ver: str, remote_src: str):
        """
        Mostra un dialog che informa l'utente della nuova versione
        e chiede se vuole aggiornare ora.

        Viene chiamato nel main thread tramite self.after().

        Parametri:
            remote_ver : stringa versione remota (es. "1.2.0")
            remote_src : contenuto completo del file .py remoto,
                         passato a _apply_update() se l'utente conferma
        """
        answer = messagebox.askyesno(
            "Aggiornamento disponibile",
            f"Nuova versione disponibile: {remote_ver}\n"
            f"Versione attuale: {__version__}\n\n"
            "Vuoi aggiornare ora?\n\n"
            "⚠ L'applicazione verrà riavviata automaticamente.",
            icon="question",
        )
        if answer:
            self._apply_update(remote_src)

    def _apply_update(self, remote_src: str):
        """
        Sostituisce il file .py corrente con il sorgente remoto
        e riavvia l'applicazione tramite os.execv.

        Flusso:
            1. Individua il percorso assoluto di questo script (__file__)
            2. Crea un backup (.bak) del file corrente per sicurezza
            3. Sovrascrive il file con il nuovo sorgente
            4. Riavvia il processo Python con os.execv (rimpiazza il
               processo corrente senza creare un figlio)

        Parametri:
            remote_src : contenuto testuale del nuovo file .py

        Gestione errori:
            • PermissionError → script non sovrascrivibile (es. read-only)
            • Qualsiasi altra eccezione → mostrata in un dialog
        """
        script_path = os.path.abspath(__file__)
        backup_path = script_path + ".bak"

        try:
            # Backup del file corrente
            self._log("💾  Creazione backup del file corrente…")
            shutil.copy2(script_path, backup_path)
            self._log(f"   Backup salvato in: {backup_path}")

            # Scrittura del nuovo sorgente
            self._log("✍  Scrittura nuova versione…")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(remote_src)

            self._log("🔄  Riavvio dell'applicazione…")
            # os.execv rimpiazza il processo corrente con una nuova
            # istanza Python: stesso eseguibile, stesso script, stessi args.
            # Non ritorna mai: l'app corrente termina qui.
            os.execv(sys.executable, [sys.executable, script_path])

        except PermissionError:
            self._log("❌  Permessi insufficienti per sovrascrivere il file.")
            messagebox.showerror(
                "Errore permessi",
                "Non è possibile sovrascrivere il file.\n"
                "Prova a eseguire l'applicazione come amministratore.",
            )
        except Exception as e:
            self._log(f"❌  Aggiornamento fallito: {e}")
            self.after(0, lambda e=e: messagebox.showerror("Errore aggiornamento", str(e)))


# ─────────────────────────────────────────────────────────────────────────────
#  LOGGER PERSONALIZZATO per yt-dlp
# ─────────────────────────────────────────────────────────────────────────────

class _YTDLLogger:
    """
    Adattatore che reindirizza i messaggi di yt-dlp verso il log della UI.

    yt-dlp si aspetta un oggetto con i metodi:
        debug(msg)   → messaggi diagnostici interni
        warning(msg) → avvertimenti non bloccanti
        error(msg)   → errori (spesso seguiti da DownloadError)
    """

    def __init__(self, log_fn):
        self._log = log_fn

    def debug(self, msg: str):
        if msg.startswith("[download]"):   # già gestito da progress_hook
            return
        self._log(f"   {msg}")

    def warning(self, msg: str):
        self._log(f"⚠  {msg}")

    def error(self, msg: str):
        self._log(f"❌  {msg}")


# ─────────────────────────────────────────────────────────────────────────────
#  UTILITY FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_bytes(n: float) -> str:
    """
    Converte byte in stringa human-readable (B → KB → MB → GB → TB).

    Esempi:
        512           → "512.0 B"
        1_500         → "1.5 KB"
        3_200_000     → "3.1 MB"
        1_100_000_000 → "1.0 GB"
    """
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _fmt_time(seconds: int) -> str:
    """
    Converte secondi in formato mm:ss.

    Esempi:
        90 → "1:30"
        5  → "0:05"
    """
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def _parse_version(ver_str: str) -> tuple[int, ...]:
    """
    Converte una stringa di versione in una tupla di interi
    per un confronto numerico corretto (non lessicografico).

    Esempi:
        "1.2.3"  → (1, 2, 3)
        "1.10.0" → (1, 10, 0)   ← 10 > 2 correttamente
        "2.0"    → (2, 0)

    Perché non usare il confronto stringa?
        "1.9.0" > "1.10.0" con confronto stringa (9 > 1),
        ma (1,9,0) < (1,10,0) con confronto tuple → corretto.
    """
    return tuple(int(x) for x in ver_str.strip().split("."))


# ─────────────────────────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = PapinoDownloader()
    app.mainloop()