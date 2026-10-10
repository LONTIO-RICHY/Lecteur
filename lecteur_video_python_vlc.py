#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lecteur vidéo / musique – Python (Tkinter + VLC)

Prérequis : VLC installé  +  pip install python-vlc
Lancement : python lecteur_video_python_vlc.py [fichier_ou_dossier]

Appuie sur H (ou F1) dans le lecteur pour voir tous les raccourcis.
Thème sombre / clair : bouton « Thème » ou touche D (choix mémorisé).

Facultatif – traduction des voix en français (sous-titres générés) :
    pip install faster-whisper deep-translator
"""

import os
import re
import sys
import tempfile
import threading
import time
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

try:
    import vlc
except (ImportError, OSError) as erreur:
    _r = tk.Tk()
    _r.withdraw()
    messagebox.showerror(
        "VLC introuvable",
        "Impossible de charger VLC.\n\n"
        "1) Installe VLC (même architecture 32/64 bits que Python)\n"
        "2) pip install python-vlc\n\n"
        f"Détail : {erreur}",
    )
    sys.exit(1)

EXT_VIDEO = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v",
             ".mpeg", ".mpg", ".ts", ".m2ts", ".3gp", ".ogv"}
EXT_AUDIO = {".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac", ".wma", ".opus", ".mka"}
EXT_MEDIA = EXT_VIDEO | EXT_AUDIO

TRIS = [
    "Date d'ajout (ancien → récent)",
    "Date d'ajout (récent → ancien)",
    "Nom (A → Z)",
]
ECHELLES = {
    "Adapté à la fenêtre": 0, "25 %": 0.25, "50 %": 0.5, "75 %": 0.75,
    "100 % (taille d'origine)": 1.0, "150 %": 1.5, "200 %": 2.0,
}
FORMATS = {"Auto": None, "16:9": "16:9", "4:3": "4:3", "1:1": "1:1",
           "21:9": "21:9", "16:10": "16:10"}
DESENT = {"Auto": "auto", "Désactivé": "off", "Yadif (qualité)": "yadif",
          "Blend": "blend", "Bob": "bob"}
VITESSES = ["0.25", "0.5", "0.75", "1", "1.25", "1.5", "1.75", "2", "3", "4"]
ETATS_LECTURE = (vlc.State.Playing, vlc.State.Paused, vlc.State.Buffering)

# Reconnaissance d'une piste française dans les noms de pistes de VLC
RE_FR = re.compile(r"fran[cç]ais|french|(?<![a-z])(?:fra|fre|fr)(?![a-z])", re.I)
# Modèle de reconnaissance vocale : "tiny" = très rapide, "base" = équilibré,
# "small" = plus précis mais nettement plus lent.
MODELE_WHISPER = "base"

# ---- Thèmes de l'interface (sombre / clair) --------------------------------
THEMES = {
    "sombre": {
        "bg": "#1e1e1e", "fg": "#e8e8e8", "champ": "#2b2b2b",
        "bouton": "#3a3a3a", "actif": "#4a4a4a", "bord": "#555555",
        "select": "#3d6fd1", "select_fg": "#ffffff", "creux": "#3a3a3a",
        "curseur": "#8ab4ff", "desactive": "#777777",
    },
    "clair": {
        "bg": "#f2f2f2", "fg": "#1a1a1a", "champ": "#ffffff",
        "bouton": "#e1e1e1", "actif": "#d0d0d0", "bord": "#b5b5b5",
        "select": "#2f6fe0", "select_fg": "#ffffff", "creux": "#cfcfcf",
        "curseur": "#2f6fe0", "desactive": "#9a9a9a",
    },
}
FICHIER_THEME = os.path.join(os.path.expanduser("~"), ".lecteur_vlc_theme")


def charger_theme():
    """Dernier thème choisi (sombre par défaut)."""
    try:
        with open(FICHIER_THEME, encoding="utf-8") as f:
            nom = f.read().strip()
        if nom in THEMES:
            return nom
    except OSError:
        pass
    return "sombre"


def sauver_theme(nom):
    try:
        with open(FICHIER_THEME, "w", encoding="utf-8") as f:
            f.write(nom)
    except OSError:
        pass


# ---- Écran d'accueil : dégradé arc-en-ciel animé ----------------------------
# Teintes proches du spectre réel (rouge, orange, jaune, vert, turquoise, bleu,
# indigo, violet) – légèrement adoucies pour un rendu naturel, comme dans le ciel.
ARC_STOPS = [
    (226, 45, 45),    # rouge
    (250, 135, 35),   # orange
    (252, 220, 55),   # jaune
    (70, 185, 85),    # vert
    (45, 185, 190),   # turquoise
    (50, 110, 225),   # bleu
    (80, 60, 190),    # indigo
    (150, 70, 195),   # violet
    (205, 55, 125),   # magenta (retour vers le rouge, boucle sans cassure)
]
ARC_NB_BANDES = 160
ARC_PRECISION = 720


def _couleur_arc(t):
    """Couleur du spectre pour t dans [0, 1[ (interpolation douce, cyclique)."""
    n = len(ARC_STOPS)
    x = (t % 1.0) * n
    i = int(x)
    f = x - i
    f = f * f * (3 - 2 * f)                      # smoothstep : transitions douces
    a, b = ARC_STOPS[i % n], ARC_STOPS[(i + 1) % n]
    r, g, bl = (round(a[k] + (b[k] - a[k]) * f) for k in range(3))
    return f"#{r:02x}{g:02x}{bl:02x}"


ARC_LUT = [_couleur_arc(i / ARC_PRECISION) for i in range(ARC_PRECISION)]

AIDE = """RACCOURCIS CLAVIER

Espace ............ lecture / pause
→  /  ← ........... avancer / reculer de 5 s  (Maj : 1 s, Ctrl : 1 min)
↑  /  ↓ ........... volume + / –
N  /  P ........... vidéo suivante / précédente (ou Page ↓ / Page ↑)
[  /  ] ........... vitesse – / +   (= ou Retour arrière : vitesse normale)
M ................. couper / remettre le son (l'image continue)
B ................. image noire / réafficher (le son continue)
J  /  K ........... son plus tôt / plus tard (−50 / +50 ms)
A  /  T ........... piste audio suivante / sous-titres suivants
F  ou  F11 ........ plein écran (Échap pour quitter, double-clic aussi)
R ................. réparer la lecture (recharge à la position actuelle)
S ................. stop
L ................. afficher / masquer la liste
D ................. thème sombre / clair
G ................. menu langues : audio, sous-titres, français, traduction des voix
SOURIS ............ clic sur la barre de progression = aller directement là ;
                    survol = temps affiché ; plein écran : bouge la souris pour
                    afficher la barre et les commandes
Ctrl+O ............ ouvrir un fichier      Ctrl+D : ouvrir un dossier
H  ou  F1 ......... cette aide

SYNCHRO : si le son arrive AVANT l'image → « Son plus tard » (+).
          si le son arrive APRÈS l'image → « Son plus tôt » (–).
"""


def date_ajout(chemin):
    """Date d'arrivée du fichier (création / téléchargement si le système la donne)."""
    try:
        st = os.stat(chemin)
    except OSError:
        return 0
    if hasattr(st, "st_birthtime"):          # macOS, BSD
        return st.st_birthtime
    if os.name == "nt":                      # Windows : st_ctime = création
        return st.st_ctime
    return st.st_mtime                       # Linux : meilleure approximation


def cle_naturelle(chemin):
    """Tri naturel : episode2 avant episode10."""
    return [int(t) if t.isdigit() else t
            for t in re.split(r"(\d+)", os.path.basename(chemin).lower())]


def texte(valeur):
    return valeur.decode("utf-8", "replace") if isinstance(valeur, bytes) else str(valeur)


def melanger(c1, c2, alpha):
    """Pose la couleur c1 (opacité alpha) sur c2 : simule une couleur semi-transparente."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * alpha + y * (1 - alpha)):02x}" for x, y in zip(a, b))


# Palette de la barre de commandes affichée en plein écran (toujours sombre)
PALETTE_PE = {
    "bg": "#141414", "creux": "#4a4a4a", "rempli": "#3d6fd1", "fg": "#ffffff",
    "bulle": "#2b2b2b", "bulle_fg": "#ffffff", "bord": "#666666",
    "fleche": melanger("#ffffff", "#141414", 1.0),
    "fleche_bord": melanger("#000000", "#141414", 1.0),
}


def temps_srt(secondes):
    ms = int(round(max(0.0, secondes) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ecrire_texte_srt(chemin_sortie, contenu):
    """Écrit le .srt à côté de la vidéo ; si le dossier est protégé, dans le dossier temporaire."""
    try:
        with open(chemin_sortie, "w", encoding="utf-8-sig") as f:
            f.write(contenu)
        return chemin_sortie
    except OSError:
        alt = os.path.join(tempfile.gettempdir(), os.path.basename(chemin_sortie))
        with open(alt, "w", encoding="utf-8-sig") as f:
            f.write(contenu)
        return alt


class BarreProgression(tk.Canvas):
    """Barre de progression : un clic va directement à cet endroit, le survol affiche le
    temps visé, et la position actuelle est repérée par une pointe de flèche de souris
    en pleine couleur (opaque)."""
    HAUTEUR = 48
    MARGE = 12
    Y = 27                      # ligne centrale de la piste
    FLECHE = [(0, 0), (0, 15), (3.8, 11.6), (6.6, 18), (9, 16.9), (6.2, 10.6), (11, 10.6)]

    def __init__(self, parent, app, palette):
        super().__init__(parent, height=self.HAUTEUR, highlightthickness=0, bd=0,
                         takefocus=False, cursor="hand2", bg=palette["bg"])
        self.app = app
        self.pal = palette
        self.valeur = 0.0        # position actuelle, entre 0 et 1
        self.survol = None       # fraction visée par la souris (ou None)
        self.actif = False       # True pendant un clic maintenu
        self._police = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        self.bind("<Configure>", lambda e: self.dessiner())
        self.bind("<Motion>", self._mouvement)
        self.bind("<Leave>", self._sortie)
        self.bind("<ButtonPress-1>", self._appui)
        self.bind("<B1-Motion>", self._glisser)
        self.bind("<ButtonRelease-1>", self._relache)

    def _fraction(self, x):
        largeur = max(1, self.winfo_width() - 2 * self.MARGE)
        return min(1.0, max(0.0, (x - self.MARGE) / largeur))

    def definir_palette(self, palette):
        self.pal = palette
        self.config(bg=palette["bg"])
        self.dessiner()

    def definir(self, fraction, force=False):
        if self.actif and not force:
            return
        if force or abs(fraction - self.valeur) >= 0.0005:
            self.valeur = fraction
            self.dessiner()

    def dessiner(self):
        c, pal, y = self, self.pal, self.Y
        c.delete("all")
        w = max(1, c.winfo_width())
        x0, x1 = self.MARGE, max(self.MARGE + 1, w - self.MARGE)
        x = x0 + (x1 - x0) * self.valeur
        c.create_rectangle(x0, y - 3, x1, y + 3, fill=pal["creux"], width=0)
        c.create_rectangle(x0, y - 3, x, y + 3, fill=pal["rempli"], width=0)
        if self.survol is not None and self.app.duree > 0:
            xs = x0 + (x1 - x0) * self.survol
            c.create_line(xs, y - 6, xs, y + 6, fill=pal["fg"], width=2)
            txt = self.app.formater(self.app.duree * self.survol)
            lw = self._police.measure(txt) + 16
            bx = min(max(xs - lw / 2, 2), w - lw - 2)
            c.create_rectangle(bx, 1, bx + lw, 20, fill=pal["bulle"], outline=pal["bord"])
            c.create_text(bx + lw / 2, 10.5, text=txt, font=self._police, fill=pal["bulle_fg"])
        # repère : pointe de flèche de souris, en pleine couleur
        pts = []
        for px, py in self.FLECHE:
            pts += [x + px, y + py]
        c.create_polygon(pts, fill=pal["fleche"], outline=pal["fleche_bord"], width=1)

    # --- souris
    def _mouvement(self, e):
        if self.app.duree > 0:
            self.survol = self._fraction(e.x)
            self.dessiner()

    def _sortie(self, _e):
        if not self.actif:
            self.survol = None
            self.dessiner()

    def _appui(self, e):
        if self.app.duree <= 0:
            return
        self.actif = True
        f = self._fraction(e.x)
        self.survol = self.valeur = f
        self.app._barre_appui(f)
        self.dessiner()

    def _glisser(self, e):
        if not self.actif:
            return
        f = self._fraction(e.x)
        self.survol = self.valeur = f
        self.app._barre_glisse(f)
        self.dessiner()

    def _relache(self, e):
        if not self.actif:
            return
        self.actif = False
        f = self._fraction(e.x)
        self.valeur = f
        dedans = 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height()
        self.survol = f if dedans else None
        self.app._barre_relache(f)
        self.dessiner()


class Lecteur:
    def __init__(self, root):
        self.root = root
        root.title("Lecteur Python – VLC")
        root.geometry("1100x720")
        root.minsize(900, 560)

        # ----- état -----
        self.liste, self.index, self.dossier = [], -1, None
        self.chemin_actuel = None
        self.duree = 0
        self.vitesse = 1.0
        self.decalage_ms = 0
        self.muet = False
        self.image_masquee = False
        self._piste_video = None
        self.echelle, self.ratio, self.desent = 0, None, "auto"
        self.mode_tri = TRIS[0]
        self.theme = charger_theme()
        self._combos = []
        self._osd_job = None
        self._controles_visibles = False
        self._derniere_activite = 0.0
        self._ptr = (0, 0)
        self._menu_ouvert = False
        self._sync_vol = False
        self._dernier_saut_barre = 0.0
        self._trad = {"actif": False, "pct": 0.0, "msg": "", "fini": None,
                      "erreur": None, "annuler": False, "media": None}

        self._glisse = False
        self._maj_auto = False
        self._saut, self._saut_job = 0, None
        self._jeton = 0
        self._charge_a = 0.0
        self._tentatives = 0
        self._fin_traitee = False
        self._immobile, self._dernier_temps = 0.0, -1
        self._msg, self._msg_fin = "", 0.0
        self._plein_ecran = False
        self._liste_visible = True
        self._ferme = False
        self._accueil_visible = False
        self._accueil_job = None
        self._phase = 0.0
        self._bandes = []

        self.hw = tk.BooleanVar(value=True)
        self.auto_suivant = tk.BooleanVar(value=True)
        self.pref_fr = tk.BooleanVar(value=True)

        self._construire_lecteur()
        self._construire_interface()
        self._lier_touches()
        self.afficher_accueil()

        root.protocol("WM_DELETE_WINDOW", self.fermer)
        root.focus_set()
        root.after(250, self._boucle)
        root.after(100, self._surveiller_souris)

    # ------------------------------------------------------------------ VLC
    def _construire_lecteur(self):
        windows = sys.platform.startswith("win")
        if not self.hw.get():
            hw = "none"
        else:
            # Windows : on évite D3D11VA (erreurs « get_buffer() failed » avec le HEVC
            # sur les puces Intel HD) et on utilise DXVA2, plus stable.
            hw = "dxva2" if windows else "any"
        options = [
            "--no-video-title-show",
            "--file-caching=1500",       # tampon : évite les saccades
            "--network-caching=3000",
            f"--avcodec-hw={hw}",
        ]
        if windows:
            # « mmdevice : cannot initialize COM (0x80010106) » : Tkinter a déjà initialisé
            # COM d'une autre façon → on passe par DirectSound, qui n'en a pas besoin.
            options.append("--aout=directsound")
        if sys.platform.startswith("linux"):
            options.append("--no-xlib")
        self.instance = vlc.Instance(*options)
        self.player = self.instance.media_player_new()

    def _attacher_fenetre(self):
        self.root.update_idletasks()
        handle = self.video_frame.winfo_id()
        if sys.platform.startswith("win"):
            self.player.set_hwnd(handle)
        elif sys.platform == "darwin":
            self.player.set_nsobject(handle)
        else:
            self.player.set_xwindow(handle)
        # VLC ne doit pas voler le clavier/la souris : nos raccourcis restent fiables
        self.player.video_set_key_input(False)
        self.player.video_set_mouse_input(False)

    def _charger(self, chemin, debut_ms=0, recuperation=False):
        self._jeton += 1
        jeton = self._jeton
        if not recuperation:
            self._tentatives = 0
        self.chemin_actuel = chemin
        self._fin_traitee = False
        self._immobile, self._dernier_temps = 0.0, -1
        self._charge_a = time.monotonic()
        try:
            self.player.stop()
            self.player.set_media(self.instance.media_new_path(chemin))
            self._attacher_fenetre()
            self.player.play()
        except Exception as e:
            self.message(f"Erreur d'ouverture : {e}", 5)
            return
        self.masquer_accueil()
        self.root.title(f"{os.path.basename(chemin)} – Lecteur Python VLC")
        self._maj_selection_liste()
        self.root.after(100, lambda: self._apres_demarrage(debut_ms, jeton))

    def _apres_demarrage(self, debut_ms, jeton, essais=0):
        if self._ferme or jeton != self._jeton:
            return
        etat = self.player.get_state()
        if etat in (vlc.State.Playing, vlc.State.Paused):
            self._reappliquer()
            if debut_ms > 0:
                self.player.set_time(int(debut_ms))
            if self._controles_visibles:
                self.barre_fen.lift()
            self.root.after(600, lambda: self._langue_auto(jeton))
            return
        if etat in (vlc.State.Error, vlc.State.Ended) or essais > 50:
            return
        self.root.after(100, lambda: self._apres_demarrage(debut_ms, jeton, essais + 1))

    def _reappliquer(self):
        """Réapplique tous les réglages à chaque nouvelle vidéo."""
        p = self.player
        reglages = (
            (p.set_rate, (self.vitesse,)),
            (p.audio_set_delay, (int(self.decalage_ms * 1000),)),
            (p.audio_set_mute, (1 if self.muet else 0,)),
            (p.audio_set_volume, (int(float(self.volume.get())),)),
            (p.video_set_scale, (self.echelle,)),
            (p.video_set_aspect_ratio, (self.ratio,)),
        )
        for fonction, args in reglages:
            try:
                fonction(*args)
            except Exception:
                pass
        if self.desent != "auto":
            self._appliquer_desent()
        if self.image_masquee:
            self._appliquer_image()

    def _reconstruire(self, debut_ms=0):
        """Recrée complètement VLC (utile si le décodage matériel pose problème)."""
        try:
            self.player.stop()
            self.player.release()
            self.instance.release()
        except Exception:
            pass
        self._construire_lecteur()
        if self.chemin_actuel:
            self._charger(self.chemin_actuel, debut_ms, recuperation=True)

    def reparer(self, auto=False):
        """Recharge la vidéo à la position actuelle (corrige blocages, son perdu, image figée…)."""
        if not self.chemin_actuel:
            return
        t = max(0, self.player.get_time())
        if auto:
            self._tentatives += 1
            if self._tentatives > 3:
                self.stop()
                self.message("Lecture impossible : fichier probablement corrompu", 5)
                if self.auto_suivant.get() and self.index + 1 < len(self.liste):
                    self.root.after(1500, self.suivant)
                return
            if self._tentatives >= 2 and self.hw.get():
                self.hw.set(False)
                self.message("Décodage matériel désactivé (problème détecté)", 4)
                self._reconstruire(t)
                return
        self.message("Réparation de la lecture…")
        self._charger(self.chemin_actuel, t, recuperation=auto)

    def _cmd_hw(self):
        t = max(0, self.player.get_time()) if self.chemin_actuel else 0
        self._reconstruire(t)
        self.message("Accélération matérielle : " + ("activée" if self.hw.get() else "désactivée"))

    # ------------------------------------------------------------ interface
    def _bouton(self, parent, libelle, commande, largeur=None):
        b = ttk.Button(parent, text=libelle, command=commande, takefocus=False)
        if largeur:
            b.config(width=largeur)
        b.pack(side="left", padx=2)
        return b

    def _combo(self, parent, titre, valeurs, defaut, commande, largeur):
        ttk.Label(parent, text=titre).pack(side="left", padx=(12, 3))
        c = ttk.Combobox(parent, values=valeurs, state="readonly",
                         width=largeur, takefocus=False)
        c.set(defaut)
        c.pack(side="left")
        self._combos.append(c)
        c.bind("<<ComboboxSelected>>",
               lambda e: (commande(c.get()), self.root.focus_set()))
        return c

    def _construire_interface(self):
        root = self.root
        self.bas = tk.Frame(root)
        self.bas.pack(side="bottom", fill="x")
        self.zone = tk.Frame(root)
        self.zone.pack(fill="both", expand=True)

        # liste de lecture (à droite)
        self.cadre_liste = tk.Frame(self.zone)
        self.cadre_liste.pack(side="right", fill="y")
        sb = ttk.Scrollbar(self.cadre_liste)
        sb.pack(side="right", fill="y")
        self.listbox = tk.Listbox(self.cadre_liste, width=34, exportselection=False,
                                  activestyle="none", yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="y")
        sb.config(command=self.listbox.yview)
        self.listbox.bind("<Double-Button-1>", self._double_clic_liste)
        self.listbox.bind("<ButtonRelease-1>", lambda e: root.focus_set())

        # zone vidéo
        self.video_frame = tk.Frame(self.zone, bg="black")
        self.video_frame.pack(side="left", fill="both", expand=True)
        self.video_frame.bind("<Double-Button-1>", lambda e: self.plein_ecran())
        self._construire_accueil()

        # ligne 1 : transport + actions
        l1 = ttk.Frame(self.bas)
        l1.pack(fill="x", padx=8, pady=(6, 2))
        self._bouton(l1, "⏮", self.precedent, 3)
        self.btn_lecture = self._bouton(l1, "▶", self.basculer_lecture, 3)
        self._bouton(l1, "⏹", self.stop, 3)
        self._bouton(l1, "⏭", self.suivant, 3)
        self._bouton(l1, "📂 Fichier", self.ouvrir)
        self._bouton(l1, "📁 Dossier", self.ouvrir_dossier)
        self.btn_muet = self._bouton(l1, "🔇 Muet", self.basculer_muet)
        self.btn_image = self._bouton(l1, "⬛ Image noire", self.basculer_image)
        self._bouton(l1, "⛶", self.plein_ecran, 3)
        self._bouton(l1, "🔄 Réparer", self.reparer)
        ttk.Label(l1, text="Volume").pack(side="left", padx=(12, 4))
        self.lbl_volume = ttk.Label(l1, text="100 %", width=6)
        self.volume = ttk.Scale(l1, from_=0, to=150, length=110,
                                command=self._cmd_volume, takefocus=False)
        self.volume.pack(side="left")
        self.lbl_volume.pack(side="left")
        self.volume.bind("<ButtonRelease-1>", lambda e: root.focus_set())
        self.volume.set(100)

        # ligne 2 : vitesse, zoom/résolution d'affichage, format
        l2 = ttk.Frame(self.bas)
        l2.pack(fill="x", padx=8, pady=2)
        ttk.Label(l2, text="Vitesse").pack(side="left", padx=(0, 3))
        self._bouton(l2, "−", lambda: self.changer_vitesse(-0.1), 2)
        self.combo_vitesse = ttk.Combobox(
            l2, values=[f"×{v}" for v in VITESSES], state="readonly",
            width=6, takefocus=False)
        self.combo_vitesse.set("×1")
        self.combo_vitesse.pack(side="left", padx=2)
        self._combos.append(self.combo_vitesse)
        self.combo_vitesse.bind(
            "<<ComboboxSelected>>",
            lambda e: (self.fixer_vitesse(float(self.combo_vitesse.get().lstrip("×"))),
                       root.focus_set()))
        self._bouton(l2, "+", lambda: self.changer_vitesse(0.1), 2)
        self._combo(l2, "Taille d'affichage", list(ECHELLES), "Adapté à la fenêtre",
                    self._choisir_echelle, 22)
        self._combo(l2, "Format", list(FORMATS), "Auto", self._choisir_format, 6)
        self._combo(l2, "Désentrelacement", list(DESENT), "Auto",
                    self._choisir_desent, 14)

        # ligne 3 : synchro son / image
        l3 = ttk.Frame(self.bas)
        l3.pack(fill="x", padx=8, pady=2)
        ttk.Label(l3, text="Synchro son/image").pack(side="left", padx=(0, 4))
        self._bouton(l3, "◀ Son plus tôt (−50)", lambda: self.changer_decalage(-50))
        self.sync = ttk.Scale(l3, from_=-3000, to=3000, length=240,
                              command=self._cmd_sync, takefocus=False)
        self.sync.pack(side="left", padx=4)
        self.sync.bind("<ButtonRelease-1>", lambda e: root.focus_set())
        self._bouton(l3, "Son plus tard (+50) ▶", lambda: self.changer_decalage(50))
        self._bouton(l3, "0", lambda: self.changer_decalage(None), 3)
        self.lbl_sync = ttk.Label(l3, text="0 ms", width=30)
        self.lbl_sync.pack(side="left", padx=6)
        self.sync.set(0)          # après la création de lbl_sync (évite l'AttributeError)

        # ligne 4 : tri + options
        l4 = ttk.Frame(self.bas)
        l4.pack(fill="x", padx=8, pady=2)
        self._combo(l4, "Ordre des fichiers du dossier", TRIS, TRIS[0],
                    self._changer_tri, 30)
        ttk.Checkbutton(l4, text="Enchaîner automatiquement", variable=self.auto_suivant,
                        takefocus=False).pack(side="left", padx=12)
        ttk.Checkbutton(l4, text="Accélération matérielle", variable=self.hw,
                        command=self._cmd_hw, takefocus=False).pack(side="left")
        self._bouton(l4, "☰ Liste", self.basculer_liste)
        self.btn_langues = self._bouton(l4, "🌐 Langues", self.menu_langues)
        self.btn_theme = self._bouton(l4, "", self.basculer_theme)
        self._bouton(l4, "❓ Aide", self.aide)

        # barre de progression + temps (clic = aller là, survol = temps, repère en flèche)
        l5 = ttk.Frame(self.bas)
        l5.pack(fill="x", padx=12, pady=(4, 0))
        self.position = BarreProgression(l5, self, self._palette_normale())
        self.position.pack(side="left", fill="x", expand=True)
        self.temps = ttk.Label(l5, text="00:00 / 00:00", width=16, anchor="e")
        self.temps.pack(side="left", padx=(8, 0))

        self.info = ttk.Label(self.bas, anchor="w")
        self.info.pack(fill="x", padx=12, pady=(2, 6))

        self._construire_osd()
        self._construire_controles_pe()
        self.appliquer_theme(self.theme)

    def _palette_normale(self):
        t = THEMES[self.theme]
        sombre = self.theme == "sombre"
        return {
            "bg": t["bg"], "creux": t["creux"], "rempli": t["select"], "fg": t["fg"],
            "bulle": t["champ"], "bulle_fg": t["fg"], "bord": t["bord"],
            "fleche": melanger("#ffffff" if sombre else "#1a1a1a", t["bg"], 1.0),
            "fleche_bord": melanger("#000000" if sombre else "#ffffff", t["bg"], 1.0),
        }

    # ------------------------------------------------------------- thème
    def appliquer_theme(self, nom):
        """Applique le thème « sombre » ou « clair » à toute l'interface."""
        t = THEMES[nom]
        self.theme = nom
        root = self.root
        style = ttk.Style(root)
        try:
            style.theme_use("clam")          # seul thème ttk qui accepte toutes les couleurs
        except tk.TclError:
            pass

        root.configure(bg=t["bg"])
        style.configure(".", background=t["bg"], foreground=t["fg"],
                        fieldbackground=t["champ"], troughcolor=t["creux"],
                        bordercolor=t["bord"], lightcolor=t["bg"], darkcolor=t["bg"],
                        focuscolor=t["bg"], insertcolor=t["fg"])
        style.map(".", foreground=[("disabled", t["desactive"])])
        style.configure("TFrame", background=t["bg"])
        style.configure("TLabel", background=t["bg"], foreground=t["fg"])

        style.configure("TButton", background=t["bouton"], foreground=t["fg"],
                        bordercolor=t["bord"], lightcolor=t["bouton"],
                        darkcolor=t["bouton"], padding=(6, 3))
        style.map("TButton",
                  background=[("pressed", t["select"]), ("active", t["actif"])],
                  foreground=[("pressed", t["select_fg"])],
                  lightcolor=[("pressed", t["select"]), ("active", t["actif"])],
                  darkcolor=[("pressed", t["select"]), ("active", t["actif"])])

        style.configure("TCheckbutton", background=t["bg"], foreground=t["fg"],
                        indicatorbackground=t["champ"], indicatorforeground=t["select_fg"],
                        indicatormargin=(0, 0, 4, 0))
        style.map("TCheckbutton",
                  background=[("active", t["bg"])],
                  indicatorbackground=[("selected", t["select"]),
                                       ("pressed", t["actif"])])

        style.configure("TCombobox", fieldbackground=t["champ"], background=t["bouton"],
                        foreground=t["fg"], arrowcolor=t["fg"], bordercolor=t["bord"],
                        lightcolor=t["champ"], darkcolor=t["champ"],
                        selectbackground=t["champ"], selectforeground=t["fg"])
        style.map("TCombobox",
                  fieldbackground=[("readonly", t["champ"])],
                  foreground=[("readonly", t["fg"])],
                  selectbackground=[("readonly", t["champ"])],
                  selectforeground=[("readonly", t["fg"])],
                  background=[("active", t["actif"]), ("readonly", t["bouton"])],
                  arrowcolor=[("disabled", t["desactive"])])

        for orient in ("Horizontal", "Vertical"):
            style.configure(f"{orient}.TScale", background=t["bg"],
                            troughcolor=t["creux"], bordercolor=t["bord"],
                            lightcolor=t["curseur"], darkcolor=t["curseur"])
            style.map(f"{orient}.TScale",
                      background=[("active", t["curseur"])])
        style.configure("Vertical.TScrollbar", background=t["bouton"],
                        troughcolor=t["creux"], bordercolor=t["bg"],
                        arrowcolor=t["fg"], lightcolor=t["bouton"], darkcolor=t["bouton"])
        style.map("Vertical.TScrollbar", background=[("active", t["actif"])])

        # widgets Tk classiques (pas ttk)
        for w in (self.bas, self.zone, self.cadre_liste):
            w.configure(bg=t["bg"])
        self.listbox.configure(bg=t["champ"], fg=t["fg"], selectbackground=t["select"],
                               selectforeground=t["select_fg"], highlightthickness=0,
                               bd=0, relief="flat")

        # listes déroulantes des Combobox
        for c in self._combos:
            try:
                popdown = root.tk.eval(f"ttk::combobox::PopdownWindow {c}")
                root.tk.call(f"{popdown}.f.l", "configure",
                             "-background", t["champ"], "-foreground", t["fg"],
                             "-selectbackground", t["select"],
                             "-selectforeground", t["select_fg"])
            except tk.TclError:
                pass
        root.option_add("*TCombobox*Listbox.background", t["champ"])
        root.option_add("*TCombobox*Listbox.foreground", t["fg"])
        root.option_add("*TCombobox*Listbox.selectBackground", t["select"])
        root.option_add("*TCombobox*Listbox.selectForeground", t["select_fg"])

        self.btn_theme.config(text="☀ Thème clair" if nom == "sombre" else "🌙 Thème sombre")
        self.position.definir_palette(self._palette_normale())

    def basculer_theme(self):
        nom = "clair" if self.theme == "sombre" else "sombre"
        self.appliquer_theme(nom)
        sauver_theme(nom)
        self.message("Thème " + nom)
        self.root.focus_set()

    def _lier_touches(self):
        r = self.root

        def lier(sequence, fonction):
            r.bind(sequence, lambda e, f=fonction: (f(), "break")[1])

        def lettre(c, fonction):
            lier(f"<{c.lower()}>", fonction)
            lier(f"<{c.upper()}>", fonction)

        lier("<space>", self.basculer_lecture)
        lier("<Right>", lambda: self.deplacer(5000))
        lier("<Left>", lambda: self.deplacer(-5000))
        lier("<Shift-Right>", lambda: self.deplacer(1000))
        lier("<Shift-Left>", lambda: self.deplacer(-1000))
        lier("<Control-Right>", lambda: self.deplacer(60000))
        lier("<Control-Left>", lambda: self.deplacer(-60000))
        lier("<Up>", lambda: self.changer_volume(5))
        lier("<Down>", lambda: self.changer_volume(-5))
        lier("<Next>", self.suivant)
        lier("<Prior>", self.precedent)
        lier("<bracketright>", lambda: self.changer_vitesse(0.1))
        lier("<bracketleft>", lambda: self.changer_vitesse(-0.1))
        lier("<equal>", lambda: self.fixer_vitesse(1.0))
        lier("<BackSpace>", lambda: self.fixer_vitesse(1.0))
        lier("<F11>", self.plein_ecran)
        lier("<Escape>", lambda: self.plein_ecran(False))
        lier("<F1>", self.aide)
        lier("<Control-o>", self.ouvrir)
        lier("<Control-O>", self.ouvrir)
        lier("<Control-d>", self.ouvrir_dossier)
        lier("<Control-D>", self.ouvrir_dossier)
        lettre("n", self.suivant)
        lettre("p", self.precedent)
        lettre("m", self.basculer_muet)
        lettre("b", self.basculer_image)
        lettre("f", self.plein_ecran)
        lettre("s", self.stop)
        lettre("r", self.reparer)
        lettre("j", lambda: self.changer_decalage(-50))
        lettre("k", lambda: self.changer_decalage(50))
        lettre("a", self.piste_audio_suivante)
        lettre("t", self.sous_titres_suivants)
        lettre("l", self.basculer_liste)
        lettre("h", self.aide)
        lettre("d", self.basculer_theme)
        lettre("g", self.menu_langues)

    # ------------------------------------------------ écran d'accueil animé
    def _construire_accueil(self):
        self.accueil = tk.Canvas(self.video_frame, highlightthickness=0, bd=0,
                                 bg="#222222", takefocus=False)
        self.accueil.bind("<Configure>", self._redessiner_accueil)
        self.accueil.bind("<Double-Button-1>", lambda e: self.plein_ecran())

    def _redessiner_accueil(self, _event=None):
        c = self.accueil
        w, h = max(1, c.winfo_width()), max(1, c.winfo_height())
        c.delete("all")
        n = ARC_NB_BANDES
        self._bandes = [
            c.create_rectangle(w * i / n, 0, w * (i + 1) / n + 1, h,
                               width=0, fill=ARC_LUT[0])
            for i in range(n)
        ]
        taille = max(18, min(52, w // 16))
        petit = max(10, min(15, w // 70))
        textes = (
            (h / 2 - taille * 0.4, "Lecteur Python – VLC", ("Segoe UI", taille, "bold")),
            (h / 2 + taille * 0.9,
             "Ctrl+O : ouvrir un fichier     Ctrl+D : ouvrir un dossier     H : aide",
             ("Segoe UI", petit)),
        )
        for y, txt, police in textes:
            c.create_text(w / 2 + 2, y + 2, text=txt, font=police, fill="#1c1c1c")  # ombre
            c.create_text(w / 2, y, text=txt, font=police, fill="#ffffff")
        self._peindre_accueil()

    def _peindre_accueil(self):
        n, taille = len(self._bandes), len(ARC_LUT)
        if not n:
            return
        decalage = int(self._phase * taille)
        for i, item in enumerate(self._bandes):
            self.accueil.itemconfig(item, fill=ARC_LUT[(decalage + i * taille // n) % taille])

    def afficher_accueil(self):
        if self._accueil_visible or self._ferme:
            return
        self._accueil_visible = True
        self.accueil.place(x=0, y=0, relwidth=1, relheight=1)
        tk.Misc.tkraise(self.accueil)            # au-dessus de la fenêtre VLC
        self._anim_accueil()

    def masquer_accueil(self):
        self._accueil_visible = False
        self.accueil.place_forget()
        if self._accueil_job is not None:
            try:
                self.root.after_cancel(self._accueil_job)
            except Exception:
                pass
            self._accueil_job = None

    def _anim_accueil(self):
        if self._ferme or not self._accueil_visible:
            self._accueil_job = None
            return
        self._phase = (self._phase + 0.004) % 1.0     # un tour complet ≈ 8 s
        self._peindre_accueil()
        self._accueil_job = self.root.after(33, self._anim_accueil)

    # ------------------------------------------------- fichiers / playlist
    def ouvrir(self):
        motifs = " ".join("*" + e for e in sorted(EXT_MEDIA))
        chemin = filedialog.askopenfilename(
            title="Choisir une vidéo ou une musique",
            filetypes=[("Vidéos et musiques", motifs), ("Tous les fichiers", "*.*")])
        if chemin:
            self.ouvrir_chemin(chemin)

    def ouvrir_dossier(self):
        dossier = filedialog.askdirectory(title="Choisir un dossier")
        if dossier:
            self.ouvrir_chemin(dossier)

    def ouvrir_chemin(self, chemin):
        chemin = os.path.normpath(os.path.abspath(chemin))
        if os.path.isdir(chemin):
            self._scanner(chemin)
            if not self.liste:
                self.message("Aucun fichier vidéo ou musique dans ce dossier", 4)
                return
            self.jouer_index(0)
        elif os.path.isfile(chemin):
            self._scanner(os.path.dirname(chemin), chemin)
            self._charger(chemin)
        else:
            self.message("Fichier introuvable", 4)

    def _scanner(self, dossier, courant=None):
        self.dossier = dossier
        try:
            fichiers = [os.path.join(dossier, f) for f in os.listdir(dossier)
                        if os.path.splitext(f)[1].lower() in EXT_MEDIA
                        and os.path.isfile(os.path.join(dossier, f))]
        except OSError:
            fichiers = []
        norm = os.path.normcase
        if courant and not any(norm(p) == norm(courant) for p in fichiers):
            fichiers.append(courant)
        self.liste = self._trier(fichiers)
        self.index = -1
        if courant:
            self.index = next((i for i, p in enumerate(self.liste)
                               if norm(p) == norm(courant)), -1)
        self.listbox.delete(0, "end")
        for p in self.liste:
            self.listbox.insert("end", os.path.basename(p))
        self._maj_selection_liste()

    def _trier(self, fichiers):
        if self.mode_tri == TRIS[2]:
            return sorted(fichiers, key=cle_naturelle)
        return sorted(fichiers, key=lambda p: (date_ajout(p), cle_naturelle(p)),
                      reverse=(self.mode_tri == TRIS[1]))

    def _changer_tri(self, mode):
        self.mode_tri = mode
        if self.dossier:
            self._scanner(self.dossier, self.chemin_actuel)
        self.message("Ordre : " + mode)

    def _maj_selection_liste(self):
        self.listbox.selection_clear(0, "end")
        if 0 <= self.index < len(self.liste):
            self.listbox.selection_set(self.index)
            self.listbox.see(self.index)

    def _double_clic_liste(self, event):
        i = self.listbox.nearest(event.y)
        if i >= 0:
            self.jouer_index(i)
        self.root.focus_set()

    def jouer_index(self, i):
        if 0 <= i < len(self.liste):
            self.index = i
            self._charger(self.liste[i])

    def suivant(self):
        if self.index + 1 < len(self.liste):
            self.jouer_index(self.index + 1)
        else:
            self.message("Fin de la liste")

    def precedent(self):
        if self.chemin_actuel and self.player.get_time() > 3000:
            self.player.set_time(0)          # comme VLC : d'abord retour au début
        elif self.index > 0:
            self.jouer_index(self.index - 1)

    # ------------------------------------------------------------ lecture
    def basculer_lecture(self):
        if not self.chemin_actuel:
            self.ouvrir()
            return
        etat = self.player.get_state()
        if etat == vlc.State.Playing:
            self.player.set_pause(1)
        elif etat == vlc.State.Paused:
            self.player.set_pause(0)
        elif etat in (vlc.State.Opening, vlc.State.Buffering):
            pass
        else:                                   # arrêté, terminé ou en erreur
            self._charger(self.chemin_actuel)

    def stop(self):
        self._jeton += 1
        self.player.stop()
        self.afficher_accueil()
        self._maj_barre(0)
        self._set_temps("00:00 / 00:00")

    def deplacer(self, ms):
        """Avance/recule. Les appuis rapprochés (touche maintenue) sont regroupés."""
        self._saut += ms
        if self._saut_job is None:
            self._saut_job = self.root.after(120, self._appliquer_saut)

    def _appliquer_saut(self):
        ms, self._saut, self._saut_job = self._saut, 0, None
        if not ms or not self.chemin_actuel:
            return
        etat = self.player.get_state()
        longueur = self.player.get_length()
        if etat == vlc.State.Ended:
            if ms < 0 and self.duree > 0:
                self._charger(self.chemin_actuel, max(0, self.duree + ms))
            return
        if etat not in (vlc.State.Playing, vlc.State.Paused, vlc.State.Buffering):
            return
        t = self.player.get_time()
        if t < 0:
            return
        nouveau = max(0, t + ms)
        if longueur > 0:
            nouveau = min(nouveau, max(0, longueur - 300))
        self.player.set_time(int(nouveau))
        signe = "⏩ +" if ms > 0 else "⏪ −"
        libelle = f"{signe}{abs(ms) // 1000} s"
        self.message(f"{libelle}  →  {self.formater(nouveau)}", 1.2, osd=False)
        self.afficher_osd(
            "seek", 1.6, texte=libelle,
            frac=(nouveau / longueur if longueur > 0 else 0),
            temps=f"{self.formater(nouveau)} / {self.formater(max(longueur, 0))}")

    def _set_temps(self, txt):
        self.temps.config(text=txt)
        if hasattr(self, "temps_pe"):
            self.temps_pe.config(text=txt)

    def _barres(self):
        return [b for b in (self.position, getattr(self, "position_pe", None)) if b is not None]

    def _synchro_barres(self, fraction):
        for b in self._barres():
            b.definir(fraction, force=True)

    def _barre_appui(self, fraction):
        self._glisse = True
        self._dernier_saut_barre = 0.0
        self._barre_glisse(fraction)

    def _barre_glisse(self, fraction):
        self._synchro_barres(fraction)
        if self.duree <= 0:
            return
        self._set_temps(f"{self.formater(self.duree * fraction)} / {self.formater(self.duree)}")
        maintenant = time.monotonic()
        if (maintenant - self._dernier_saut_barre >= 0.15
                and self.player.get_state() in ETATS_LECTURE):
            self._dernier_saut_barre = maintenant
            self.player.set_time(int(self.duree * fraction))

    def _barre_relache(self, fraction):
        self._glisse = False
        self._synchro_barres(fraction)
        self._aller_a(fraction)
        self._focus_root()

    def _aller_a(self, fraction):
        if not self.chemin_actuel or self.duree <= 0:
            return
        cible = int(self.duree * fraction)
        if self.player.get_state() in ETATS_LECTURE:
            self.player.set_time(cible)
        else:
            self._charger(self.chemin_actuel, cible)

    def _maj_barre(self, valeur):
        fraction = max(0.0, min(1.0, valeur / 1000.0))
        for b in self._barres():
            b.definir(fraction)

    # ------------------------------------------------------------- vitesse
    def fixer_vitesse(self, v):
        self.vitesse = round(min(4.0, max(0.25, v)), 2)
        try:
            self.player.set_rate(self.vitesse)
        except Exception:
            pass
        self.combo_vitesse.set(f"×{self.vitesse:g}")
        self.message(f"Vitesse ×{self.vitesse:g}")

    def changer_vitesse(self, delta):
        self.fixer_vitesse(self.vitesse + delta)

    # -------------------------------------------------------- son / image
    def _cmd_volume(self, valeur):
        vol = int(float(valeur))
        try:
            self.player.audio_set_volume(vol)
        except Exception:
            pass
        self.lbl_volume.config(text=f"{vol} %")
        if hasattr(self, "volume_pe") and not self._sync_vol:
            self._sync_vol = True
            try:
                self.volume_pe.set(vol)
            finally:
                self._sync_vol = False

    def _cmd_volume_pe(self, valeur):
        """Curseur de volume de la barre plein écran."""
        if self._sync_vol:
            return
        vol = int(float(valeur))
        self._sync_vol = True
        try:
            self.volume.set(vol)
        finally:
            self._sync_vol = False
        self._cmd_volume(vol)

    def changer_volume(self, delta):
        vol = int(min(150, max(0, float(self.volume.get()) + delta)))
        self.volume.set(vol)
        self._cmd_volume(vol)
        self.message(f"Volume {vol} %", 1.2, osd=False)
        self.afficher_osd("volume", 1.5, vol=vol, muet=self.muet)

    def basculer_muet(self):
        self.muet = not self.muet
        self.player.audio_set_mute(1 if self.muet else 0)
        self.btn_muet.config(text="🔊 Remettre le son" if self.muet else "🔇 Muet")
        self.message("Son coupé (l'image continue)" if self.muet else "Son rétabli", osd=False)
        self.afficher_osd("volume", 1.5, vol=int(float(self.volume.get())), muet=self.muet)

    def basculer_image(self):
        self.image_masquee = not self.image_masquee
        self._appliquer_image()
        self.btn_image.config(
            text="🖼 Afficher l'image" if self.image_masquee else "⬛ Image noire")
        self.message("Image masquée (le son continue)" if self.image_masquee
                     else "Image rétablie")

    def _appliquer_image(self):
        p = self.player
        try:
            if self.image_masquee:
                courante = p.video_get_track()
                if courante != -1:
                    self._piste_video = courante
                p.video_set_track(-1)
            else:
                ids = [i for i, _ in (p.video_get_track_description() or []) if i != -1]
                cible = self._piste_video if self._piste_video in ids else (ids[0] if ids else None)
                if cible is not None:
                    p.video_set_track(cible)
        except Exception:
            pass

    def _set_decalage(self, ms):
        ms = max(-3000, min(3000, int(round(ms / 10.0)) * 10))
        self.decalage_ms = ms
        try:
            self.player.audio_set_delay(ms * 1000)
        except Exception:
            pass
        self.lbl_sync.config(text=self._texte_sync())
        if abs(float(self.sync.get()) - ms) > 1:
            self.sync.set(ms)

    def _texte_sync(self):
        ms = self.decalage_ms
        if ms == 0:
            return "0 ms (synchro d'origine)"
        if ms < 0:
            return f"son avancé de {-ms} ms"
        return f"son retardé de {ms} ms"

    def _cmd_sync(self, valeur):
        self._set_decalage(float(valeur))

    def changer_decalage(self, delta):
        self._set_decalage(0 if delta is None else self.decalage_ms + delta)
        self.message("Synchro : " + self._texte_sync())

    def _cycler(self, nom, description, courante, definir):
        try:
            pistes = [(i, texte(n)) for i, n in (description() or [])]
            ids = [i for i, _ in pistes]
            if len(pistes) < 2:
                self.message(f"{nom} : aucune autre piste")
                return
            cur = courante()
            suiv = ids[(ids.index(cur) + 1) % len(ids)] if cur in ids else ids[0]
            definir(suiv)
            self.message(f"{nom} : {dict(pistes)[suiv]}", 3)
        except Exception:
            self.message(f"{nom} : indisponible")

    def piste_audio_suivante(self):
        p = self.player
        self._cycler("Piste audio", p.audio_get_track_description,
                     p.audio_get_track, p.audio_set_track)

    def sous_titres_suivants(self):
        p = self.player
        self._cycler("Sous-titres", p.video_get_spu_description,
                     p.video_get_spu, p.video_set_spu)

    # ----------------------------------------------- affichage / résolution
    def _choisir_echelle(self, nom):
        self.echelle = ECHELLES[nom]
        try:
            self.player.video_set_scale(self.echelle)
        except Exception:
            pass
        self.message("Taille d'affichage : " + nom)

    def _choisir_format(self, nom):
        self.ratio = FORMATS[nom]
        try:
            self.player.video_set_aspect_ratio(self.ratio)
        except Exception:
            pass
        self.message("Format : " + nom)

    def _choisir_desent(self, nom):
        valeur = DESENT[nom]
        revenir = valeur == "auto" and self.desent != "auto"
        self.desent = valeur
        if revenir:
            self.reparer()
        else:
            self._appliquer_desent()
            self.message("Désentrelacement : " + nom)

    def _appliquer_desent(self):
        if self.desent == "auto":
            return
        mode = None if self.desent == "off" else self.desent
        try:
            self.player.video_set_deinterlace(mode)
        except TypeError:
            try:
                self.player.video_set_deinterlace(1 if mode else 0, mode)
            except Exception:
                pass
        except Exception:
            pass

    def plein_ecran(self, force=None):
        voulu = (not self._plein_ecran) if force is None else force
        if voulu == self._plein_ecran:
            return
        self._plein_ecran = voulu
        self.root.attributes("-fullscreen", voulu)
        if voulu:
            self.bas.pack_forget()
            self.cadre_liste.pack_forget()
            self._ptr = self.root.winfo_pointerxy()
            self.root.after(200, self.afficher_controles)
        else:
            self.masquer_controles()
            self.bas.pack(side="bottom", fill="x", before=self.zone)
            if self._liste_visible:
                self.cadre_liste.pack(side="right", fill="y", before=self.video_frame)
        self.root.focus_set()

    def basculer_liste(self):
        self._liste_visible = not self._liste_visible
        if self._plein_ecran:
            return
        if self._liste_visible:
            self.cadre_liste.pack(side="right", fill="y", before=self.video_frame)
        else:
            self.cadre_liste.pack_forget()

    def aide(self):
        messagebox.showinfo("Aide – raccourcis", AIDE)
        self.root.focus_set()

    # ------------------------------------------- retour visuel (volume, avance…)
    def _fenetre_flottante(self, fond):
        """Fenêtre sans bordure posée AU-DESSUS de la vidéo. La fenêtre de VLC recouvre les
        widgets Tk ordinaires (surtout en plein écran) : il faut une vraie fenêtre à part."""
        fen = tk.Toplevel(self.root)
        fen.withdraw()
        fen.overrideredirect(True)
        fen.configure(bg=fond)
        try:
            fen.attributes("-alpha", 0.94)
        except tk.TclError:
            pass
        # les raccourcis clavier continuent de marcher si cette fenêtre prend le focus
        fen.bindtags(fen.bindtags() + (str(self.root),))
        return fen

    def _afficher_fenetre(self, fen, largeur, hauteur, haut=True):
        """Place la fenêtre flottante sur la zone vidéo (en haut ou en bas) et l'affiche."""
        v = self.video_frame
        vx, vy, vw, vh = v.winfo_rootx(), v.winfo_rooty(), v.winfo_width(), v.winfo_height()
        if largeur <= 0:
            largeur = vw
        x = vx + (vw - largeur) // 2
        y = vy + 28 if haut else vy + vh - hauteur
        fen.geometry(f"{largeur}x{hauteur}+{x}+{y}")
        fen.deiconify()
        fen.lift()
        try:
            fen.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.root.after_idle(self._focus_root)   # le clavier reste sur la fenêtre principale

    def _focus_root(self):
        try:
            self.root.focus_force()
        except Exception:
            pass

    def _construire_osd(self):
        self.osd_fen = self._fenetre_flottante("#111111")
        self.osd = tk.Canvas(self.osd_fen, width=320, height=84, bg="#111111",
                             highlightthickness=1, highlightbackground="#555555",
                             bd=0, takefocus=False)
        self.osd.pack(fill="both", expand=True)

    def afficher_osd(self, genre, duree=1.5, **d):
        """Petit panneau sur la vidéo (visible aussi en plein écran)."""
        if self._ferme or not hasattr(self, "osd"):
            return
        c, L, H = self.osd, 320, 84
        c.delete("all")
        blanc = "#ffffff"
        if genre == "volume":
            vol, muet = d["vol"], d.get("muet", False)
            icone = "🔇" if (muet or vol == 0) else ("🔉" if vol < 60 else "🔊")
            c.create_text(34, H / 2, text=icone, font=("Segoe UI Emoji", 22), fill=blanc)
            x0, x1, y = 70, 250, H / 2
            c.create_rectangle(x0, y - 5, x1, y + 5, fill="#444444", width=0)
            couleur = "#777777" if muet else ("#e8a33d" if vol > 100 else "#4f8cff")
            c.create_rectangle(x0, y - 5, x0 + (x1 - x0) * vol / 150, y + 5,
                               fill=couleur, width=0)
            xm = x0 + (x1 - x0) * 100 / 150
            c.create_line(xm, y - 10, xm, y + 10, fill="#aaaaaa")
            c.create_text(285, y, text="muet" if muet else f"{vol} %",
                          font=("Segoe UI", 13, "bold"), fill=blanc)
        elif genre == "seek":
            c.create_text(L / 2, 22, text=d["texte"], font=("Segoe UI", 17, "bold"), fill=blanc)
            x0, x1, y = 20, L - 20, 50
            c.create_rectangle(x0, y - 3, x1, y + 3, fill="#444444", width=0)
            c.create_rectangle(x0, y - 3, x0 + (x1 - x0) * max(0, min(1, d["frac"])), y + 3,
                               fill="#4f8cff", width=0)
            c.create_text(L / 2, 70, text=d["temps"], font=("Segoe UI", 11), fill="#dddddd")
        else:
            c.create_text(L / 2, H / 2, text=d["texte"], width=L - 30, justify="center",
                          font=("Segoe UI", 13, "bold"), fill=blanc)
        self._afficher_fenetre(self.osd_fen, L, H)
        if self._osd_job is not None:
            try:
                self.root.after_cancel(self._osd_job)
            except Exception:
                pass
        self._osd_job = self.root.after(int(duree * 1000), self._cacher_osd)

    def _cacher_osd(self):
        self._osd_job = None
        self.osd_fen.withdraw()

    # --------------------------------------- commandes affichées en plein écran
    def _construire_controles_pe(self):
        fond = PALETTE_PE["bg"]
        self.barre_fen = self._fenetre_flottante(fond)
        self.barre_pe = tk.Frame(self.barre_fen, bg=fond)
        self.barre_pe.pack(fill="both", expand=True)
        haut = tk.Frame(self.barre_pe, bg=fond)
        haut.pack(fill="x", padx=14, pady=(8, 0))
        self.position_pe = BarreProgression(haut, self, PALETTE_PE)
        self.position_pe.pack(side="left", fill="x", expand=True)
        self.temps_pe = tk.Label(haut, text="00:00 / 00:00", bg=fond, fg="#ffffff",
                                 font=("Segoe UI", 11), width=16, anchor="e")
        self.temps_pe.pack(side="left", padx=(8, 0))

        bas = tk.Frame(self.barre_pe, bg=fond)
        bas.pack(fill="x", padx=14, pady=(0, 10))

        def bouton(libelle, commande, largeur=4):
            b = tk.Button(bas, text=libelle, width=largeur, bg="#2b2b2b", fg="#ffffff",
                          activebackground="#3d6fd1", activeforeground="#ffffff",
                          relief="flat", bd=0, takefocus=False, font=("Segoe UI", 12),
                          command=lambda: (commande(), self._focus_root()))
            b.pack(side="left", padx=3)
            return b

        bouton("⏮", self.precedent)
        self.btn_lecture_pe = bouton("▶", self.basculer_lecture)
        bouton("⏭", self.suivant)
        tk.Label(bas, text="🔊", bg=fond, fg="#ffffff",
                 font=("Segoe UI", 12)).pack(side="left", padx=(14, 2))
        self.volume_pe = tk.Scale(bas, from_=0, to=150, orient="horizontal", length=130,
                                  showvalue=False, bg=fond, fg="#ffffff",
                                  troughcolor="#4a4a4a", highlightthickness=0, bd=0,
                                  sliderrelief="flat", activebackground="#3d6fd1",
                                  takefocus=False, command=self._cmd_volume_pe)
        self.volume_pe.pack(side="left")
        bouton("🌐 Langues", self.menu_langues, 11).pack_configure(padx=(14, 3))
        bouton("⛶", lambda: self.plein_ecran(False))
        self._sync_vol = True
        try:
            self.volume_pe.set(float(self.volume.get()))
        finally:
            self._sync_vol = False

    def afficher_controles(self):
        if not self._plein_ecran:
            return
        self._controles_visibles = True
        self._derniere_activite = time.monotonic()
        self.barre_fen.update_idletasks()
        hauteur = max(60, self.barre_pe.winfo_reqheight())
        self._afficher_fenetre(self.barre_fen, 0, hauteur, haut=False)
        self.position_pe.dessiner()

    def masquer_controles(self):
        self._controles_visibles = False
        self.barre_fen.withdraw()

    def _pointeur_sur_barre(self, x, y):
        b = self.barre_pe
        return (b.winfo_rootx() <= x <= b.winfo_rootx() + b.winfo_width()
                and b.winfo_rooty() <= y <= b.winfo_rooty() + b.winfo_height())

    def _surveiller_souris(self):
        """Suit la souris même au-dessus de la vidéo (la fenêtre VLC absorbe ses événements)."""
        if self._ferme:
            return
        try:
            x, y = self.root.winfo_pointerxy()
            if self.root.state() == "iconic":
                self.masquer_controles()
                self._cacher_osd()
            if self._plein_ecran:
                maintenant = time.monotonic()
                if abs(x - self._ptr[0]) + abs(y - self._ptr[1]) >= 3:
                    self._derniere_activite = maintenant
                    if not self._controles_visibles:
                        self.afficher_controles()
                if self._controles_visibles:
                    if self._pointeur_sur_barre(x, y):
                        self._derniere_activite = maintenant
                    elif (maintenant - self._derniere_activite > 2.5
                          and not self._glisse and not self._menu_ouvert):
                        self.masquer_controles()
            self._ptr = (x, y)
        except Exception:
            pass
        self.root.after(100, self._surveiller_souris)

    # ------------------------------------------------- langues (audio / sous-titres)
    @staticmethod
    def _pistes(description):
        try:
            return [(i, texte(n)) for i, n in (description() or [])]
        except Exception:
            return []

    def _piste_fr(self, pistes):
        for i, nom in pistes:
            if i != -1 and RE_FR.search(nom):
                return i, nom
        return None

    def choisir_audio(self, i, nom):
        try:
            self.player.audio_set_track(i)
            self.message("Audio : " + nom, 3)
        except Exception:
            self.message("Audio : changement impossible")

    def choisir_sous_titres(self, i, nom):
        try:
            self.player.video_set_spu(i)
            self.message("Sous-titres : " + (nom if i != -1 else "désactivés"), 3)
        except Exception:
            self.message("Sous-titres : changement impossible")

    def audio_francais(self):
        piste = self._piste_fr(self._pistes(self.player.audio_get_track_description))
        if piste:
            self.choisir_audio(*piste)
        else:
            self.message("Aucune piste audio en français dans cette vidéo", 4)

    def sous_titres_francais(self):
        piste = self._piste_fr(self._pistes(self.player.video_get_spu_description))
        if piste:
            self.choisir_sous_titres(*piste)
        else:
            self.message("Aucun sous-titre en français (menu Langues → traduire)", 4)

    def _langue_auto(self, jeton, essais=0):
        """À l'ouverture d'une vidéo : audio en français si possible, sinon sous-titres français."""
        if self._ferme or jeton != self._jeton or not self.pref_fr.get():
            return
        p = self.player
        audio = [(i, n) for i, n in self._pistes(p.audio_get_track_description) if i != -1]
        if not audio and essais < 12:             # VLC liste les pistes avec un petit délai
            self.root.after(500, lambda: self._langue_auto(jeton, essais + 1))
            return
        try:
            fr = self._piste_fr(audio)
            if fr:
                if p.audio_get_track() != fr[0]:
                    p.audio_set_track(fr[0])
                    self.message("Audio en français sélectionné", 3)
                return
            fr = self._piste_fr(self._pistes(p.video_get_spu_description))
            if fr and p.video_get_spu() != fr[0]:
                p.video_set_spu(fr[0])
                self.message("Sous-titres en français activés", 3)
        except Exception:
            pass

    def ajouter_sous_titres(self):
        chemin = filedialog.askopenfilename(
            title="Choisir un fichier de sous-titres",
            filetypes=[("Sous-titres", "*.srt *.ass *.ssa *.sub *.vtt"), ("Tous les fichiers", "*.*")])
        if chemin and self.chemin_actuel:
            try:
                self.player.video_set_subtitle_file(chemin)
                self.root.after(700, self._activer_dernier_spu)
                self.message("Sous-titres ajoutés : " + os.path.basename(chemin), 4)
            except Exception as e:
                self.message(f"Sous-titres non chargés : {e}", 5)
        self.root.focus_set()

    def _activer_dernier_spu(self):
        try:
            ids = [i for i, _ in self._pistes(self.player.video_get_spu_description) if i != -1]
            if ids:
                self.player.video_set_spu(ids[-1])
        except Exception:
            pass

    def menu_langues(self):
        p = self.player
        if self._plein_ecran or self.theme == "sombre":
            coul = dict(bg="#2b2b2b", fg="#ffffff", activebackground="#3d6fd1",
                        activeforeground="#ffffff")
        else:
            coul = dict(bg="#ffffff", fg="#1a1a1a", activebackground="#2f6fe0",
                        activeforeground="#ffffff")
        m = tk.Menu(self.root, tearoff=0, **coul)
        audio = [(i, n) for i, n in self._pistes(p.audio_get_track_description) if i != -1]
        spu = self._pistes(p.video_get_spu_description)
        try:
            cur_a = p.audio_get_track()
        except Exception:
            cur_a = None
        try:
            cur_s = p.video_get_spu()
        except Exception:
            cur_s = None

        if audio:
            ma = tk.Menu(m, tearoff=0, **coul)
            for i, n in audio:
                ma.add_command(label=("✓ " if i == cur_a else "    ") + n,
                               command=lambda i=i, n=n: self.choisir_audio(i, n))
            m.add_cascade(label="Langue audio", menu=ma)
        else:
            m.add_command(label="Langue audio (aucune piste : lance une vidéo)", state="disabled")
        if spu:
            ms = tk.Menu(m, tearoff=0, **coul)
            for i, n in spu:
                nom = n if i != -1 else "Désactivés"
                ms.add_command(label=("✓ " if i == cur_s else "    ") + nom,
                               command=lambda i=i, n=n: self.choisir_sous_titres(i, n))
            m.add_cascade(label="Sous-titres", menu=ms)
        else:
            m.add_command(label="Sous-titres (aucun : lance une vidéo)", state="disabled")

        m.add_separator()
        m.add_command(label="Audio en français", command=self.audio_francais)
        m.add_command(label="Sous-titres en français", command=self.sous_titres_francais)
        m.add_checkbutton(label="Choisir le français automatiquement", variable=self.pref_fr)
        m.add_separator()
        m.add_command(label="Ajouter un fichier de sous-titres…", command=self.ajouter_sous_titres)
        m.add_command(label="Traduire un fichier de sous-titres (.srt) en français…",
                      command=self.traduire_srt)
        m.add_command(
            label=("Annuler la traduction en cours" if self._trad["actif"]
                   else "Traduire les voix en français (génère des sous-titres)…"),
            command=self.traduire_voix_fr)

        self._menu_ouvert = True
        try:
            x, y = self.root.winfo_pointerxy()
            m.tk_popup(x, y)
        finally:
            m.grab_release()
            self._menu_ouvert = False

    # ---------------------------------------- traduction en français (en arrière-plan)
    @staticmethod
    def _modules_traduction(*noms):
        import importlib.util
        return [n for n in noms if importlib.util.find_spec(n) is None]

    def _texte_traduction(self):
        t = self._trad
        if not t["actif"]:
            return ""
        return f"traduction FR : {t['msg']} {int(t['pct'] * 100)} %"

    def traduire_voix_fr(self):
        t = self._trad
        if t["actif"]:
            t["annuler"] = True
            self.message("Annulation de la traduction…", 3)
            return
        if not self.chemin_actuel:
            self.message("Ouvre d'abord une vidéo", 3)
            return
        if self._modules_traduction("faster_whisper", "deep_translator"):
            messagebox.showinfo(
                "Modules manquants",
                "Cette fonction a besoin de deux modules Python.\n\n"
                "Dans l'invite de commande, tape :\n\n"
                "pip install faster-whisper deep-translator\n\n"
                "Puis relance le lecteur.")
            self.root.focus_set()
            return
        if not messagebox.askyesno(
                "Traduire les voix en français",
                "Le lecteur va écouter les voix de la vidéo et créer des sous-titres en "
                "français (fichier .fr.srt à côté de la vidéo).\n\n"
                "• Internet est nécessaire (modèle téléchargé la 1re fois + traduction en ligne)\n"
                "• Cela peut être long sur un PC sans carte graphique dédiée\n"
                "• Tu peux continuer à regarder pendant ce temps ; les sous-titres "
                "s'activeront à la fin\n\nCommencer ?"):
            self.root.focus_set()
            return
        self.root.focus_set()
        chemin = self.chemin_actuel
        t.update(actif=True, pct=0.0, msg="préparation", fini=None, erreur=None,
                 annuler=False, media=chemin)
        self.message("Traduction des voix lancée en arrière-plan…", 4)
        threading.Thread(target=self._travail_voix, args=(chemin,), daemon=True).start()

    def _travail_voix(self, chemin):
        t = self._trad
        try:
            from faster_whisper import WhisperModel
            from deep_translator import GoogleTranslator
            t["msg"] = "chargement du modèle"
            modele = WhisperModel(MODELE_WHISPER, device="cpu", compute_type="int8")
            t["msg"] = "écoute des voix"
            segments, info = modele.transcribe(chemin, beam_size=1, vad_filter=True)
            total = max(1.0, float(getattr(info, "duration", 0) or 0))
            traducteur = None
            if getattr(info, "language", "fr") != "fr":
                traducteur = GoogleTranslator(source="auto", target="fr")
            blocs, echecs = [], 0
            for seg in segments:
                if t["annuler"]:
                    raise RuntimeError("Traduction annulée")
                src = seg.text.strip()
                if not src:
                    continue
                fr = src
                if traducteur:
                    try:
                        fr = traducteur.translate(src) or src
                    except Exception:
                        echecs += 1
                blocs.append((seg.start, seg.end, fr))
                t["pct"] = min(0.99, seg.end / total)
            if not blocs:
                raise RuntimeError("Aucune voix détectée dans cette vidéo")
            contenu = "\n".join(
                f"{n}\n{temps_srt(a)} --> {temps_srt(b)}\n{txt}\n"
                for n, (a, b, txt) in enumerate(blocs, 1))
            sortie = ecrire_texte_srt(os.path.splitext(chemin)[0] + ".fr.srt", contenu)
            t["media"] = chemin
            t["fini"] = sortie
            if traducteur and echecs > len(blocs) // 2:
                t["erreur"] = ("Traduction en ligne impossible (connexion ?) : "
                               "sous-titres créés dans la langue d'origine")
        except Exception as e:
            traceback.print_exc()
            t["erreur"] = f"Traduction : {e}"
        finally:
            t["actif"] = False

    def traduire_srt(self):
        t = self._trad
        if t["actif"]:
            self.message("Une traduction est déjà en cours", 3)
            return
        if self._modules_traduction("deep_translator"):
            messagebox.showinfo(
                "Module manquant",
                "Dans l'invite de commande, tape :\n\npip install deep-translator\n\n"
                "Puis relance le lecteur.")
            self.root.focus_set()
            return
        chemin = filedialog.askopenfilename(
            title="Fichier de sous-titres à traduire en français",
            filetypes=[("Sous-titres SRT", "*.srt"), ("Tous les fichiers", "*.*")])
        self.root.focus_set()
        if not chemin:
            return
        t.update(actif=True, pct=0.0, msg="traduction du fichier", fini=None,
                 erreur=None, annuler=False, media=None)
        self.message("Traduction des sous-titres lancée…", 4)
        threading.Thread(target=self._travail_srt, args=(chemin,), daemon=True).start()

    def _travail_srt(self, chemin):
        t = self._trad
        try:
            from deep_translator import GoogleTranslator
            try:
                with open(chemin, encoding="utf-8-sig") as f:
                    contenu = f.read()
            except UnicodeDecodeError:
                with open(chemin, encoding="latin-1") as f:
                    contenu = f.read()
            blocs = [b for b in re.split(r"\r?\n\s*\r?\n", contenu.strip()) if b.strip()]
            traducteur = GoogleTranslator(source="auto", target="fr")
            sortie, echecs = [], 0
            for n, bloc in enumerate(blocs, 1):
                if t["annuler"]:
                    raise RuntimeError("Traduction annulée")
                lignes = bloc.splitlines()
                k = next((i for i, l in enumerate(lignes) if "-->" in l), None)
                if k is None:
                    continue
                entete = lignes[:k + 1]
                propre = re.sub(r"<[^>]+>|\{\\[^}]*\}", "", "\n".join(lignes[k + 1:])).strip()
                fr = propre
                if propre:
                    try:
                        fr = traducteur.translate(propre) or propre
                    except Exception:
                        echecs += 1
                sortie.append("\n".join(entete) + "\n" + fr)
                t["pct"] = n / len(blocs)
            if not sortie:
                raise RuntimeError("Aucun sous-titre lisible dans ce fichier")
            fichier = ecrire_texte_srt(os.path.splitext(chemin)[0] + ".fr.srt",
                                       "\n\n".join(sortie) + "\n")
            t["media"] = None
            t["fini"] = fichier
            if echecs > len(sortie) // 2:
                t["erreur"] = "Traduction en ligne impossible (connexion ?)"
        except Exception as e:
            traceback.print_exc()
            t["erreur"] = f"Traduction : {e}"
        finally:
            t["actif"] = False

    def _suivre_traduction(self):
        """Appelée par la boucle principale : récupère le résultat du travail en arrière-plan."""
        t = self._trad
        if t["fini"]:
            fichier, media, t["fini"] = t["fini"], t["media"], None
            if self.chemin_actuel and (
                    media is None or os.path.normcase(media) == os.path.normcase(self.chemin_actuel)):
                try:
                    self.player.video_set_subtitle_file(fichier)
                    self.root.after(700, self._activer_dernier_spu)
                    self.message("Sous-titres en français prêts et activés ✔", 6)
                except Exception as e:
                    self.message(f"Sous-titres créés mais non chargés : {e}", 7)
            else:
                self.message("Sous-titres français créés : " + fichier, 8)
        if t["erreur"]:
            texte_erreur, t["erreur"] = t["erreur"], None
            self.message(texte_erreur, 8)

    # ---------------------------------------------------------- boucle
    def message(self, txt, duree=2.0, osd=True):
        self._msg, self._msg_fin = txt, time.monotonic() + duree
        self.info.config(text=txt)
        if osd and self._plein_ecran:        # la barre du bas est cachée en plein écran
            self.afficher_osd("texte", duree, texte=txt)

    def _boucle(self):
        if self._ferme:
            return
        try:
            self._mettre_a_jour()
        except Exception:
            traceback.print_exc()
        self.root.after(250, self._boucle)

    def _mettre_a_jour(self):
        p = self.player
        etat = p.get_state()
        longueur, t = p.get_length(), p.get_time()
        recent = time.monotonic() - self._charge_a < 1.5

        icone = "⏸" if etat == vlc.State.Playing else "▶"
        self.btn_lecture.config(text=icone)
        self.btn_lecture_pe.config(text=icone)
        self._suivre_traduction()

        if longueur > 0:
            self.duree = longueur
            if t >= 0 and not self._glisse:
                self._maj_barre(min(1000, t / longueur * 1000))
                self._set_temps(f"{self.formater(t)} / {self.formater(longueur)}")

        # Surveillance : lecture « bloquée » (image/son figés) → réparation auto
        if etat == vlc.State.Playing:
            if t == self._dernier_temps:
                self._immobile += 0.25
            else:
                self._immobile = 0.0
            self._dernier_temps = t
            if self._immobile >= 6:
                self._immobile = 0.0
                self.message("Lecture bloquée – réparation automatique…", 3)
                self.reparer(auto=True)
                return
        else:
            self._immobile, self._dernier_temps = 0.0, -1

        if etat == vlc.State.Ended and not self._fin_traitee and not recent:
            self._fin_traitee = True
            self._maj_barre(1000)
            if self.auto_suivant.get() and self.index + 1 < len(self.liste):
                self.suivant()
            else:
                self.message("Fin de la lecture", 4)
        elif etat == vlc.State.Error and not recent:
            self.reparer(auto=True)
            return

        if time.monotonic() >= self._msg_fin:
            self.info.config(text=self._statut())

    def _statut(self):
        trad = self._texte_traduction()
        if not self.chemin_actuel:
            base = "Ouvre un fichier (Ctrl+O) ou un dossier (Ctrl+D)  –  H = aide"
            return base + ("  •  " + trad if trad else "")
        morceaux = [os.path.basename(self.chemin_actuel)]
        if self.liste:
            morceaux.append(f"{self.index + 1}/{len(self.liste)}")
        try:
            w, h = self.player.video_get_size(0)
        except Exception:
            w = h = 0
        if w and h:
            morceaux.append(f"{w}×{h}")
        morceaux.append(f"vitesse ×{self.vitesse:g}")
        if self.decalage_ms:
            morceaux.append("synchro " + self._texte_sync())
        if self.muet:
            morceaux.append("muet")
        if self.image_masquee:
            morceaux.append("image masquée")
        if trad:
            morceaux.append(trad)
        return "  •  ".join(morceaux)

    @staticmethod
    def formater(ms):
        secondes = max(0, int(ms / 1000))
        minutes, secondes = divmod(secondes, 60)
        heures, minutes = divmod(minutes, 60)
        if heures:
            return f"{heures:02d}:{minutes:02d}:{secondes:02d}"
        return f"{minutes:02d}:{secondes:02d}"

    def fermer(self):
        self._ferme = True
        try:
            self.player.stop()
            self.player.release()
            self.instance.release()
        except Exception:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    app = Lecteur(root)
    if len(sys.argv) > 1:
        root.after(400, lambda: app.ouvrir_chemin(sys.argv[1]))
    root.mainloop()


if __name__ == "__main__":
    main()
