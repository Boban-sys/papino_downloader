"""
╔══════════════════════════════════════════════════════════════╗
║            YT Downloader — Crea collegamento desktop         ║
╚══════════════════════════════════════════════════════════════╝

Esegui questo script UNA SOLA VOLTA per:
  1. Creare l'icona  yt_downloader_icon.ico  (nella stessa cartella)
  2. Creare un collegamento (.lnk) sul Desktop di Windows

Dipendenze:
    pip install pywin32 Pillow

Uso:
    python crea_collegamento.py
"""

import os
import sys
import struct
import subprocess
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
#  PERCORSI
# ─────────────────────────────────────────────────────────────────────────────

# Cartella dove si trova questo script (e yt_downloader.py)
HERE = Path(__file__).resolve().parent

# File principali
MAIN_SCRIPT = HERE / "yt_downloader.py"
ICON_FILE   = HERE / "yt_downloader_icon.ico"

# Desktop dell'utente corrente (funziona anche con account non-admin)
DESKTOP = Path(os.path.expanduser("~/Desktop"))


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 1 — CREA L'ICONA .ICO
# ─────────────────────────────────────────────────────────────────────────────

def crea_icona():
    """
    Genera il file yt_downloader_icon.ico usando Pillow.

    Crea un'icona multi-risoluzione (256, 128, 64, 48, 32, 16 px) con:
      • Cerchio rosso stile YouTube
      • Triangolo play bianco
      • Badge download (freccia giù) in basso a destra

    Se Pillow non è installato mostra istruzioni e continua senza icona.
    """
    if ICON_FILE.exists():
        print(f"✔  Icona già presente: {ICON_FILE}")
        return True

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("⚠  Pillow non installato. Esegui: pip install Pillow")
        print("   Il collegamento verrà creato senza icona personalizzata.")
        return False

    print("🎨  Generazione icona…")
    sizes  = [256, 128, 64, 48, 32, 16]
    frames = []

    for size in sizes:
        img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # ── Sfondo cerchio rosso ──────────────────────────────────────────
        m = int(size * 0.04)
        draw.ellipse([m, m, size - m, size - m], fill="#FF0000")

        # ── Triangolo play bianco ─────────────────────────────────────────
        cx, cy = size // 2, size // 2
        r = size * 0.28
        draw.polygon([
            (cx - r * 0.6, cy - r),
            (cx - r * 0.6, cy + r),
            (cx + r,       cy),
        ], fill="white")

        # ── Badge download in basso a destra ─────────────────────────────
        bx = int(size * 0.72)
        by = int(size * 0.72)
        bw = int(size * 0.22)
        bh = int(size * 0.22)
        # Sfondo scuro del badge
        draw.rectangle([bx, by, bx + bw, by + bh], fill="#1a1a1a")
        # Corpo freccia (rettangolo verticale)
        aw = bw * 0.55
        ax = bx + (bw - aw) / 2
        draw.rectangle([ax, by + bh * 0.1, ax + aw, by + bh * 0.62], fill="white")
        # Punta freccia (triangolo)
        draw.polygon([
            (ax - aw * 0.5, by + bh * 0.60),
            (ax + aw * 1.5, by + bh * 0.60),
            (ax + aw * 0.5, by + bh * 0.92),
        ], fill="white")

        frames.append(img)

    frames[0].save(
        ICON_FILE,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=frames[1:],
    )
    print(f"✔  Icona salvata: {ICON_FILE}")
    return True


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 2 — CREA IL COLLEGAMENTO .LNK
#
#  Vengono tentati tre metodi in ordine di preferenza:
#    A) win32com  (pywin32)     — il più affidabile su Windows
#    B) PowerShell WScript.Shell — built-in Windows, nessuna dipendenza
#    C) File .bat               — fallback universale
# ─────────────────────────────────────────────────────────────────────────────

def crea_collegamento_win32com() -> bool:
    """
    Metodo A: usa pywin32 (win32com.client) per creare il file .lnk.

    win32com.client.Dispatch("WScript.Shell") è il modo ufficiale
    Windows per creare shortcut programmaticamente.

    Parametri del collegamento:
        TargetPath      → python.exe
        Arguments       → percorso di yt_downloader.py
        WorkingDirectory→ cartella dell'app (per trovare l'icona)
        IconLocation    → file .ico + indice (0 = prima icona nel file)
        Description     → tooltip al passaggio del mouse
    """
    try:
        import win32com.client  # type: ignore
    except ImportError:
        return False

    print("🔗  Creazione collegamento con pywin32…")
    shell    = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(str(DESKTOP / "YT Downloader.lnk"))

    shortcut.TargetPath       = sys.executable          # python.exe corrente
    shortcut.Arguments        = f'"{MAIN_SCRIPT}"'
    shortcut.WorkingDirectory = str(HERE)
    shortcut.Description      = "YouTube Video Downloader"

    if ICON_FILE.exists():
        shortcut.IconLocation = f"{ICON_FILE},0"

    shortcut.save()
    return True


def crea_collegamento_powershell() -> bool:
    """
    Metodo B: usa PowerShell con WScript.Shell — disponibile su qualsiasi
    Windows senza dipendenze Python aggiuntive.

    Costruisce uno script PowerShell inline passato con -Command.
    Richiede che PowerShell sia nel PATH (normalmente lo è su Windows 7+).
    """
    lnk_path  = DESKTOP / "YT Downloader.lnk"
    icon_arg  = f'$s.IconLocation = "{ICON_FILE},0";' if ICON_FILE.exists() else ""

    ps_script = (
        f'$ws = New-Object -ComObject WScript.Shell;'
        f'$s = $ws.CreateShortcut("{lnk_path}");'
        f'$s.TargetPath = "{sys.executable}";'
        f'$s.Arguments = \'"{MAIN_SCRIPT}"\';'
        f'$s.WorkingDirectory = "{HERE}";'
        f'$s.Description = "YouTube Video Downloader";'
        f'{icon_arg}'
        f'$s.Save()'
    )

    try:
        print("🔗  Creazione collegamento con PowerShell…")
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def crea_collegamento_bat() -> bool:
    """
    Metodo C: crea un file .bat sul Desktop come fallback universale.

    Non è un vero collegamento .lnk (non supporta icone personalizzate),
    ma funziona su qualsiasi Windows e non richiede dipendenze.

    @echo off        → non mostra i comandi nel terminale
    start "" pythonw → usa pythonw.exe (niente finestra console)
    """
    bat_path = DESKTOP / "YT Downloader.bat"
    # pythonw.exe è la variante senza finestra console di python.exe
    pythonw = Path(sys.executable).parent / "pythonw.exe"
    if not pythonw.exists():
        pythonw = sys.executable   # fallback a python.exe normale

    bat_content = (
        f'@echo off\n'
        f'start "" "{pythonw}" "{MAIN_SCRIPT}"\n'
    )

    bat_path.write_text(bat_content, encoding="utf-8")
    print(f"⚠  Creato file .bat (fallback senza icona): {bat_path}")
    return True


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 58)
    print("  YT Downloader — Setup collegamento desktop")
    print("=" * 58)

    # Verifica che yt_downloader.py esista nella stessa cartella
    if not MAIN_SCRIPT.exists():
        print(f"\n❌  File non trovato: {MAIN_SCRIPT}")
        print("   Assicurati che crea_collegamento.py sia nella stessa")
        print("   cartella di yt_downloader.py e riprova.")
        input("\nPremi INVIO per uscire…")
        sys.exit(1)

    # Step 1: icona
    crea_icona()

    # Step 2: collegamento — prova i metodi in ordine
    print()
    successo = (
        crea_collegamento_win32com() or
        crea_collegamento_powershell() or
        crea_collegamento_bat()
    )

    print()
    if successo:
        print("✅  Collegamento creato sul Desktop!")
        print(f"   Cartella app : {HERE}")
        print(f"   Python usato : {sys.executable}")
    else:
        print("❌  Impossibile creare il collegamento automaticamente.")
        print(f"   Crea manualmente un collegamento a:\n   {MAIN_SCRIPT}")

    input("\nPremi INVIO per uscire…")


if __name__ == "__main__":
    main()