"""DWG Compare - comparador de revisoes de desenhos tecnicos em PDF.

Desempenho:
- A janela abre imediatamente: numpy, OpenCV e PyMuPDF sao carregados em
  segundo plano, depois que a interface ja esta na tela.
- O visualizador redesenha apenas a area visivel da pagina, a partir de uma
  piramide de resolucoes, entao zoom e arraste ficam fluidos mesmo em folhas A0.
- O resultado da comparacao e guardado com 1 byte por pixel (imagem indexada) e
  as revisoes originais ficam num cache LRU limitado por memoria.

Pareamento de folhas:
- Cada par (folha anterior x folha atualizada) e comparado de forma independente.
  Quando as revisoes tem quantidades diferentes de folhas, o pareamento inicial e
  feito por semelhanca de miniaturas, mantendo a ordem das folhas.
- O usuario pode trocar o pareamento ou excluir folhas; apenas o par alterado e
  recomparado, com prioridade sobre a fila.
"""

import heapq
import io
import itertools
import math
import os
import queue
import sys
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageTk

# Carregados sob demanda por load_heavy_modules().
np = None
cv2 = None
fitz = None
_heavy_lock = threading.Lock()

# PyMuPDF nao e thread-safe: todo acesso a documentos passa por este lock.
FITZ_LOCK = threading.RLock()


def load_heavy_modules():
    global np, cv2, fitz
    with _heavy_lock:
        if fitz is not None:
            return
        import numpy as _np
        import cv2 as _cv2
        try:
            import pymupdf as _fitz
        except ImportError:
            import fitz as _fitz
        np, cv2 = _np, _cv2
        fitz = _fitz


APP_TITLE = "DWG Compare"
APP_SUBTITLE = "Comparador de revisões de desenhos técnicos"
APP_ID = "DWGCompare.Comparador"
# Parametros fixos de comparacao: equilibrio entre nitidez e velocidade.
DEFAULT_DPI = 200          # resolucao de renderizacao das paginas
DEFAULT_TOLERANCE = 2      # deslocamento (px) ainda considerado a mesma linha
DEFAULT_THRESHOLD = 210    # tons de cinza abaixo disso sao tratados como linha
THUMBNAIL_DPI = 24         # miniaturas usadas no pareamento automatico
MAX_ZOOM = 8.0
REVISION_CACHE_BYTES = 900 * 1024 * 1024

VIEW_DIFF = "diff"
VIEW_OLD = "old"
VIEW_NEW = "new"

# Indices da imagem de comparacao: fundo, comum, somente anterior, somente atualizado.
PALETTE_RGB = ((255, 255, 255), (70, 70, 70), (220, 35, 35), (25, 105, 220))
PALETTE_FLAT = [channel for color in PALETTE_RGB for channel in color]

# Tema
BG = "#0A1428"
HEADER = "#071022"
SURFACE = "#0F1D36"
SURFACE_2 = "#16284A"
HOVER = "#1E3562"
BORDER = "#22385F"
TEXT = "#E8EEF8"
MUTED = "#93A6C8"
SUBTLE = "#5F7499"
ACCENT = "#2F6BFF"
ACCENT_HOVER = "#4D82FF"
DANGER = "#E5484D"
DANGER_HOVER = "#F0646A"
SUCCESS = "#3DD68C"
WARNING = "#F5A524"
VIEWER_BG = "#071023"
SHADOW = "#030914"
COLOR_COMMON = "#464646"
COLOR_OLD = "#DC2323"
COLOR_NEW = "#1969DC"

GLYPHS = {
    "open": "",
    "swap": "",
    "play": "",
    "stop": "",
    "export": "",
    "prev": "",
    "next": "",
    "zoom_in": "",
    "zoom_out": "",
    "fit": "",
    "layers": "",
    "doc": "",
    "sync": "",
    "hide": "",
    "show": "",
    "warning": "",
}

# Definidos em setup_fonts(), depois que a janela existe.
UI_SCALE = 1.0
UI_FAMILY = "Segoe UI"
ICON_FAMILY = None


def px(value):
    return int(round(value * UI_SCALE))


def ui_font(size, weight="normal"):
    return (UI_FAMILY, size, weight)


def icon_font(size):
    return (ICON_FAMILY, size)


def prepare_windows_process():
    """Interface nitida com escala > 100% e icone proprio na barra de tarefas."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def setup_fonts(root):
    global UI_SCALE, UI_FAMILY, ICON_FAMILY
    UI_SCALE = max(1.0, root.winfo_fpixels("1i") / 96.0)

    def available(family):
        return tkfont.Font(root, family=family).actual("family") == family

    for family in ("Segoe UI", "Helvetica Neue", "Arial"):
        if available(family):
            UI_FAMILY = family
            break
    for family in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if available(family):
            ICON_FAMILY = family
            break


def build_airplane_icon(size=256):
    """Desenha o icone do aplicativo (aviao visto de cima sobre fundo azul)."""
    scale = 4  # supersampling para bordas suaves
    s = size * scale
    image = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22), fill=(23, 52, 120, 255))
    draw.rounded_rectangle((int(s * 0.04), int(s * 0.04), int(s * 0.96), int(s * 0.96)),
                           radius=int(s * 0.19), fill=(47, 107, 255, 255))

    plane = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    pd = ImageDraw.Draw(plane)

    def p(x, y):
        return (x * s / 100.0, y * s / 100.0)

    white = (255, 255, 255, 255)
    # fuselagem
    pd.rounded_rectangle((*p(45.5, 12), *p(54.5, 84)), radius=int(s * 0.045), fill=white)
    # asas
    pd.polygon([p(50, 36), p(88, 56), p(88, 62), p(50, 52), p(12, 62), p(12, 56)], fill=white)
    # estabilizadores
    pd.polygon([p(50, 72), p(66, 82), p(66, 86), p(50, 82), p(34, 86), p(34, 82)], fill=white)
    plane = plane.rotate(-45, resample=Image.Resampling.BICUBIC, center=(s / 2, s / 2))
    image.alpha_composite(plane)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def fmt_int(value):
    return f"{value:,}".replace(",", ".")


def fmt_pct(value):
    return f"{value:.4f}".replace(".", ",") + " %"


def elide(text, limit):
    if len(text) <= limit:
        return text
    keep = limit - 1
    return text[: keep // 2] + "…" + text[-(keep - keep // 2):]


ISO_SIZES = {"A0": (841, 1189), "A1": (594, 841), "A2": (420, 594), "A3": (297, 420), "A4": (210, 297)}


def describe_page_size(width_pt, height_pt):
    width = width_pt * 25.4 / 72.0
    height = height_pt * 25.4 / 72.0
    short, long_ = sorted((width, height))
    for name, (a, b) in ISO_SIZES.items():
        if abs(short - a) <= 3 and abs(long_ - b) <= 3:
            return f"{name} · {width:.0f}×{height:.0f} mm"
    return f"{width:.0f}×{height:.0f} mm"


class PDFComparator:
    """Renderiza e compara folhas de desenhos tecnicos."""

    def __init__(self, dpi=DEFAULT_DPI, tolerance=DEFAULT_TOLERANCE, threshold=DEFAULT_THRESHOLD):
        self.dpi = int(dpi)
        self.tolerance = int(tolerance)
        self.threshold = int(threshold)

    @staticmethod
    def pdf_info(path):
        load_heavy_modules()
        with FITZ_LOCK, fitz.open(path) as document:
            sizes = [(round(p.rect.width, 3), round(p.rect.height, 3)) for p in document]
            return len(document), sizes

    def render_page(self, document, page_index, dpi=None, gray=False):
        load_heavy_modules()
        scale = (dpi or self.dpi) / 72.0
        colorspace = fitz.csGRAY if gray else fitz.csRGB
        with FITZ_LOCK:
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=colorspace, alpha=False)
            samples = pixmap.samples
            height, width, channels = pixmap.height, pixmap.width, pixmap.n
        array = np.frombuffer(samples, dtype=np.uint8).reshape(height, width, channels)
        return array[:, :, 0] if gray else array

    def thumbnail(self, document, page_index):
        """Mapa de densidade de tinta 64x64 e proporcao da folha, usados no pareamento."""
        gray = self.render_page(document, page_index, dpi=THUMBNAIL_DPI, gray=True)
        ink = (gray < self.threshold).astype(np.float32)
        return cv2.resize(ink, (64, 64), interpolation=cv2.INTER_AREA), gray.shape[1] / gray.shape[0]

    @staticmethod
    def similarity(a, b):
        (map_a, ratio_a), (map_b, ratio_b) = a, b
        if abs(ratio_a - ratio_b) / max(ratio_a, ratio_b) > 0.05:
            return 0.0  # formatos/orientacoes diferentes
        total = float(map_a.sum() + map_b.sum())
        if total == 0:
            return 1.0
        return 1.0 - float(np.abs(map_a - map_b).sum()) / total

    @classmethod
    def align_sheets(cls, old_thumbs, new_thumbs):
        """Pareia as folhas mantendo a ordem e maximizando a semelhanca.

        Todas as folhas do documento menor recebem par; as excedentes do maior
        (ex.: partlist adicionada) ficam sem par. Retorna [(old|None, new|None)].
        """
        swapped = len(old_thumbs) > len(new_thumbs)
        short, long_ = (new_thumbs, old_thumbs) if swapped else (old_thumbs, new_thumbs)
        n, m = len(short), len(long_)
        sim = [[cls.similarity(a, b) for b in long_] for a in short]

        negative = -1e9
        dp = [[negative] * (m + 1) for _ in range(n + 1)]
        dp[0] = [0.0] * (m + 1)
        for i in range(1, n + 1):
            for j in range(i, m + 1):
                dp[i][j] = max(dp[i][j - 1], dp[i - 1][j - 1] + sim[i - 1][j - 1])

        match = {}  # indice no documento maior -> indice no menor
        i, j = n, m
        while i > 0:
            if j > i and dp[i][j] == dp[i][j - 1]:
                j -= 1
            else:
                match[j - 1] = i - 1
                i, j = i - 1, j - 1

        pairs = []
        for j in range(m):
            k = match.get(j)
            pairs.append((j, k) if swapped else (k, j))
        return pairs

    def compare_images(self, old_rgb, new_rgb):
        """Retorna (imagem indexada por PALETTE_RGB, estatisticas)."""
        if old_rgb.shape != new_rgb.shape:
            raise ValueError("As imagens renderizadas possuem dimensões diferentes.")

        # Pixels escuros sao tratados como linhas/textos do desenho.
        old_mask = cv2.cvtColor(old_rgb, cv2.COLOR_RGB2GRAY) < self.threshold
        new_mask = cv2.cvtColor(new_rgb, cv2.COLOR_RGB2GRAY) < self.threshold

        radius = max(0, self.tolerance)
        if radius > 0:
            size = radius * 2 + 1
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
            old_near = cv2.dilate(old_mask.view(np.uint8), kernel).view(bool)
            new_near = cv2.dilate(new_mask.view(np.uint8), kernel).view(bool)
        else:
            old_near = old_mask
            new_near = new_mask

        # Uma linha e comum quando encontra linha da outra revisao dentro da tolerancia.
        common = (old_mask & new_near) | (new_mask & old_near)
        removed = old_mask & ~new_near
        added = new_mask & ~old_near

        index = common.view(np.uint8).copy()
        index[removed] = 2
        index[added] = 3

        removed_pixels = int(np.count_nonzero(removed))
        added_pixels = int(np.count_nonzero(added))
        changed_pixels = removed_pixels + added_pixels
        ink_pixels = max(1, int(np.count_nonzero(old_mask | new_mask)))

        stats = {
            "changed_pixels": changed_pixels,
            "ink_pixels": ink_pixels,
            "percent_changed": changed_pixels * 100.0 / ink_pixels,
            "removed_pixels": removed_pixels,
            "added_pixels": added_pixels,
        }
        return index, stats


class JobRunner:
    """Thread unica que executa tarefas por prioridade (menor valor primeiro)."""

    def __init__(self):
        self._heap = []
        self._seq = itertools.count()
        self._cv = threading.Condition()
        self._closing = False
        threading.Thread(target=self._run, daemon=True, name="compare").start()

    def submit(self, fn, priority=1):
        with self._cv:
            if self._closing:
                return
            heapq.heappush(self._heap, (priority, next(self._seq), fn))
            self._cv.notify()

    def clear(self):
        with self._cv:
            self._heap.clear()

    def close(self, final=None):
        with self._cv:
            self._heap.clear()
            if final is not None:
                heapq.heappush(self._heap, (-1, next(self._seq), final))
            self._closing = True
            self._cv.notify()

    def _run(self):
        while True:
            with self._cv:
                while not self._heap:
                    if self._closing:
                        return
                    self._cv.wait()
                _, _, fn = heapq.heappop(self._heap)
            try:
                fn()
            except Exception:
                pass  # cada tarefa reporta os proprios erros


class CompareSession:
    """Documentos abertos e fila de trabalho de uma comparacao."""

    def __init__(self, old_path, new_path):
        self.paths = {VIEW_OLD: old_path, VIEW_NEW: new_path}
        self.comparator = PDFComparator()
        self.runner = JobRunner()
        self.done = set()  # (id do par, versao) ja comparados; usado so pelo runner
        self._docs = {}    # usado apenas pela thread do runner

    def _doc(self, kind):
        document = self._docs.get(kind)
        if document is None:
            with FITZ_LOCK:
                document = fitz.open(self.paths[kind])
            self._docs[kind] = document
        return document

    def plan(self):
        """Retorna (pares iniciais, {tipo: quantidade de folhas}, pareamento_automatico)."""
        load_heavy_modules()
        with FITZ_LOCK:
            counts = {kind: len(self._doc(kind)) for kind in (VIEW_OLD, VIEW_NEW)}
        if counts[VIEW_OLD] == counts[VIEW_NEW]:
            return [(i, i) for i in range(counts[VIEW_OLD])], counts, False
        thumbs = {
            kind: [self.comparator.thumbnail(self._doc(kind), i) for i in range(counts[kind])]
            for kind in (VIEW_OLD, VIEW_NEW)
        }
        return PDFComparator.align_sheets(thumbs[VIEW_OLD], thumbs[VIEW_NEW]), counts, True

    def compare(self, old_index, new_index):
        """Retorna (indices, stats, render anterior, render atualizado nativo)."""
        old_image = self.comparator.render_page(self._doc(VIEW_OLD), old_index)
        new_native = self.comparator.render_page(self._doc(VIEW_NEW), new_index)
        new_image = new_native
        if new_native.shape[:2] != old_image.shape[:2]:
            # Folhas de tamanhos diferentes: a atualizada e ajustada ao tamanho da anterior.
            new_image = cv2.resize(new_native, (old_image.shape[1], old_image.shape[0]),
                                   interpolation=cv2.INTER_AREA)
        diff, stats = self.comparator.compare_images(old_image, new_image)
        stats["resized"] = new_image is not new_native
        return diff, stats, old_image, new_native

    def close(self):
        def close_docs():
            with FITZ_LOCK:
                for document in self._docs.values():
                    document.close()
            self._docs.clear()

        self.runner.close(final=close_docs)


class SheetPair:
    """Uma linha da lista: folha anterior x folha atualizada (qualquer lado pode faltar)."""

    _ids = itertools.count()

    def __init__(self, old, new):
        self.id = str(next(self._ids))
        self.old = old
        self.new = new
        self.excluded = False
        self.version = 0
        self.raster = None
        self.stats = None
        self.error = None
        self.queued_priority = None  # None = fora da fila

    @property
    def comparable(self):
        return self.old is not None and self.new is not None

    @property
    def needs_compare(self):
        return self.comparable and not self.excluded and self.raster is None and self.error is None

    def reset(self):
        self.version += 1
        self.raster = None
        self.stats = None
        self.error = None
        self.queued_priority = None


class PageRaster:
    """Imagem de pagina com piramide de resolucoes reduzidas.

    O visualizador recorta apenas a regiao visivel do nivel mais adequado ao
    zoom, em vez de redimensionar a pagina inteira a cada redesenho.
    """

    _palette = None

    def __init__(self, array, indexed=False):
        self.levels = [array]
        self.indexed = indexed
        self.height, self.width = array.shape[:2]

    @property
    def nbytes(self):
        return sum(level.nbytes for level in self.levels)

    def drop_levels(self):
        del self.levels[1:]

    @classmethod
    def palette(cls):
        if cls._palette is None:
            cls._palette = np.array(PALETTE_RGB, dtype=np.uint8)
        return cls._palette

    def _to_rgb(self, array):
        return self.palette()[array] if array.ndim == 2 else array

    def _level(self, scale):
        k = 0
        while k < 6 and scale * (2 ** (k + 1)) <= 1.0:
            k += 1
        while len(self.levels) <= k:
            source = self._to_rgb(self.levels[-1])
            h, w = source.shape[:2]
            if w < 64 or h < 64:
                break
            self.levels.append(cv2.resize(source, (w // 2, h // 2), interpolation=cv2.INTER_AREA))
        return self.levels[min(k, len(self.levels) - 1)]

    def render(self, scale, ox, oy, cw, ch):
        """Renderiza a area visivel. Retorna (PIL.Image, x, y) no canvas ou None."""
        array = self._level(scale)
        lh, lw = array.shape[:2]
        sx = scale * self.width / lw    # pixels de tela por pixel do nivel
        sy = scale * self.height / lh

        vx0, vy0 = max(0.0, ox), max(0.0, oy)
        vx1 = min(self.width * scale, ox + cw)
        vy1 = min(self.height * scale, oy + ch)
        if vx1 <= vx0 or vy1 <= vy0:
            return None

        lx0, ly0 = int(vx0 / sx), int(vy0 / sy)
        lx1 = min(lw, int(math.ceil(vx1 / sx)))
        ly1 = min(lh, int(math.ceil(vy1 / sy)))
        crop = self._to_rgb(array[ly0:ly1, lx0:lx1])

        out_w = max(1, int(round((lx1 - lx0) * sx)))
        out_h = max(1, int(round((ly1 - ly0) * sy)))
        if (out_w, out_h) != (crop.shape[1], crop.shape[0]):
            if sx < 1.0:
                interpolation = cv2.INTER_AREA
            elif sx >= 3.0:
                interpolation = cv2.INTER_NEAREST
            else:
                interpolation = cv2.INTER_LINEAR
            crop = cv2.resize(crop, (out_w, out_h), interpolation=interpolation)

        image = Image.fromarray(np.ascontiguousarray(crop))
        return image, lx0 * sx - ox, ly0 * sy - oy


class RevisionCache:
    """Cache LRU, limitado por memoria, das folhas originais renderizadas.

    Folhas ausentes sao renderizadas em uma thread propria, sem travar a interface.
    """

    def __init__(self, old_path, new_path, dpi, budget_bytes=REVISION_CACHE_BYTES):
        self.paths = {VIEW_OLD: old_path, VIEW_NEW: new_path}
        self.comparator = PDFComparator(dpi=dpi)
        self.budget = budget_bytes
        self._items = OrderedDict()
        self._pending = set()
        self._lock = threading.Lock()
        self._docs = {}  # usado apenas pela thread do executor
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="render")
        self._closed = False

    def get(self, kind, index):
        key = (kind, index)
        with self._lock:
            raster = self._items.get(key)
            if raster is not None:
                self._items.move_to_end(key)
            return raster

    def put(self, kind, index, raster):
        with self._lock:
            self._items[(kind, index)] = raster
            self._items.move_to_end((kind, index))
            total = sum(item.nbytes for item in self._items.values())
            while total > self.budget and len(self._items) > 2:
                _, evicted = self._items.popitem(last=False)
                total -= evicted.nbytes

    def request(self, kind, index, callback):
        key = (kind, index)
        with self._lock:
            if self._closed or key in self._pending:
                return
            self._pending.add(key)
        self._executor.submit(self._load, kind, index, callback)

    def _load(self, kind, index, callback):
        error = None
        try:
            if self.get(kind, index) is None:
                document = self._docs.get(kind)
                if document is None:
                    with FITZ_LOCK:
                        document = fitz.open(self.paths[kind])
                    self._docs[kind] = document
                self.put(kind, index, PageRaster(self.comparator.render_page(document, index)))
        except Exception as exc:
            error = exc
        finally:
            with self._lock:
                self._pending.discard((kind, index))
        callback(self, kind, index, error)

    def close(self):
        with self._lock:
            self._closed = True
            self._items.clear()

        def close_docs():
            with FITZ_LOCK:
                for document in self._docs.values():
                    document.close()
            self._docs.clear()

        self._executor.submit(close_docs)
        self._executor.shutdown(wait=False)


# ---------------------------------------------------------------- widgets

class FlatButton(tk.Frame):
    """Botao plano com icone opcional e estado de hover/selecao."""

    PALETTES = {
        # variante: (fundo, fundo no hover, texto)
        "primary": (ACCENT, ACCENT_HOVER, "#FFFFFF"),
        "secondary": (SURFACE_2, HOVER, TEXT),
        "ghost": (None, SURFACE_2, MUTED),
        "danger": (DANGER, DANGER_HOVER, "#FFFFFF"),
        "segment": (SURFACE_2, HOVER, MUTED),
    }

    def __init__(self, parent, text="", icon=None, command=None, variant="secondary",
                 padx=12, pady=7, font_size=10, bold=False):
        super().__init__(parent, bd=0, highlightthickness=0, cursor="hand2")
        self.command = command
        self.variant = variant
        self.enabled = True
        self.selected = False
        self.hover = False
        self.font_size = font_size

        self.inner = tk.Frame(self, bd=0)
        self.inner.pack(expand=True, padx=px(padx), pady=px(pady))
        self.icon_label = tk.Label(self.inner, bd=0, font=icon_font(font_size) if ICON_FAMILY else None)
        self.text_label = tk.Label(self.inner, bd=0, font=ui_font(font_size, "bold" if bold else "normal"))
        for part in (self, self.inner, self.icon_label, self.text_label):
            part.bind("<Enter>", self._on_enter)
            part.bind("<Leave>", self._on_leave)
            part.bind("<ButtonRelease-1>", self._on_click)
        self.set_content(text, icon)

    def set_content(self, text=None, icon=None, variant=None):
        if variant:
            self.variant = variant
        self.icon_label.pack_forget()
        self.text_label.pack_forget()
        has_icon = bool(icon and ICON_FAMILY)
        if has_icon:
            self.icon_label.configure(text=GLYPHS.get(icon, icon))
            self.icon_label.pack(side="left", padx=(0, px(8) if text else 0))
        if text:
            self.text_label.configure(text=text)
            self.text_label.pack(side="left")
        self._refresh()

    def set_enabled(self, enabled):
        self.enabled = enabled
        self._refresh()

    def set_selected(self, selected):
        self.selected = selected
        self._refresh()

    def _refresh(self):
        normal, hover, fg = self.PALETTES[self.variant]
        if normal is None:
            normal = self.master.cget("bg")
        if self.selected:
            bg, fg = ACCENT, "#FFFFFF"
        elif not self.enabled:
            bg, fg = (SURFACE_2 if self.variant in ("primary", "danger") else normal), SUBTLE
        else:
            bg = hover if self.hover else normal
        for part in (self, self.inner):
            part.configure(bg=bg)
        for label in (self.icon_label, self.text_label):
            label.configure(bg=bg, fg=fg)
        cursor = "hand2" if self.enabled else "arrow"
        for part in (self, self.inner, self.icon_label, self.text_label):
            part.configure(cursor=cursor)

    def _pointer_inside(self):
        try:
            widget = self.winfo_containing(*self.winfo_pointerxy())
        except (KeyError, tk.TclError):
            return False
        while widget is not None:
            if widget is self:
                return True
            widget = widget.master
        return False

    def _on_enter(self, _event):
        if not self.hover:
            self.hover = True
            self._refresh()

    def _on_leave(self, _event):
        if self.hover and not self._pointer_inside():
            self.hover = False
            self._refresh()

    def _on_click(self, _event):
        if self.enabled and self.command and self._pointer_inside():
            self.command()


class Segmented(tk.Frame):
    """Grupo de botoes mutuamente exclusivos (segmented control)."""

    def __init__(self, parent, options, command, font_size=9, padx=12, pady=6):
        super().__init__(parent, bg=SURFACE_2, padx=px(3), pady=px(3))
        self.buttons = {}
        for value, text, icon in options:
            button = FlatButton(self, text, icon, command=lambda v=value: command(v),
                                variant="segment", padx=padx, pady=pady, font_size=font_size)
            button.pack(side="left", fill="both", expand=True)
            self.buttons[value] = button

    def set(self, value):
        for key, button in self.buttons.items():
            button.set_selected(key == value)


class FileCard(tk.Frame):
    """Cartao clicavel que mostra o PDF selecionado e suas informacoes."""

    def __init__(self, parent, title, accent, command):
        super().__init__(parent, bg=SURFACE_2, highlightthickness=1,
                         highlightbackground=BORDER, highlightcolor=BORDER, cursor="hand2")
        self.command = command
        body = tk.Frame(self, bg=SURFACE_2)
        body.pack(fill="x", padx=px(14), pady=px(12))

        top = tk.Frame(body, bg=SURFACE_2)
        top.pack(fill="x")
        dot = tk.Canvas(top, width=px(10), height=px(10), bg=SURFACE_2, highlightthickness=0)
        dot.create_oval(1, 1, px(10) - 1, px(10) - 1, fill=accent, outline="")
        dot.pack(side="left", padx=(0, px(8)))
        tk.Label(top, text=title.upper(), font=ui_font(8, "bold"), fg=MUTED, bg=SURFACE_2).pack(side="left")
        if ICON_FAMILY:
            self.icon = tk.Label(top, text=GLYPHS["open"], font=icon_font(11), fg=MUTED, bg=SURFACE_2)
            self.icon.pack(side="right")

        self.name = tk.Label(body, text="Nenhum arquivo selecionado", font=ui_font(10, "bold"),
                             fg=SUBTLE, bg=SURFACE_2, anchor="w")
        self.name.pack(fill="x", pady=(px(8), 0))
        self.meta = tk.Label(body, text="Clique para selecionar um PDF", font=ui_font(9),
                             fg=SUBTLE, bg=SURFACE_2, anchor="w")
        self.meta.pack(fill="x", pady=(px(2), 0))

        for widget in self._descendants(self):
            widget.bind("<Enter>", lambda _e: self.configure(highlightbackground=ACCENT))
            widget.bind("<Leave>", lambda _e: self.configure(highlightbackground=BORDER))
            widget.bind("<ButtonRelease-1>", lambda _e: self.command())

    @staticmethod
    def _descendants(widget):
        yield widget
        for child in widget.winfo_children():
            yield from FileCard._descendants(child)

    def set_file(self, path):
        if path:
            self.name.configure(text=elide(os.path.basename(path), 38), fg=TEXT)
        else:
            self.name.configure(text="Nenhum arquivo selecionado", fg=SUBTLE)

    def set_meta(self, text, error=False):
        self.meta.configure(text=text, fg=DANGER if error else MUTED)


# ---------------------------------------------------------------- aplicacao

class ComparatorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        setup_fonts(self)
        self.title(f"{APP_TITLE} · {APP_SUBTITLE}")
        self.configure(bg=BG)
        icon = build_airplane_icon()
        self._icons = [ImageTk.PhotoImage(icon.resize((n, n), Image.Resampling.LANCZOS))
                       for n in (256, 48, 32, 16)]
        self.iconphoto(True, *self._icons)

        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        width, height = min(px(1400), sw - 80), min(px(880), sh - 80)
        self.geometry(f"{width}x{height}+{(sw - width) // 2}+{(sh - height) // 3}")
        self.minsize(min(px(1000), sw - 40), min(px(640), sh - 80))
        if sys.platform == "win32":
            try:
                self.state("zoomed")
            except tk.TclError:
                pass

        self.paths = {VIEW_OLD: "", VIEW_NEW: ""}
        self.status_var = tk.StringVar(value="Selecione os dois PDFs para começar.")
        self.page_var = tk.StringVar(value="–")
        self.zoom_var = tk.StringVar(value="–")

        self.pairs = []          # SheetPair, na ordem exibida na lista
        self.sheet_counts = {VIEW_OLD: 0, VIEW_NEW: 0}
        self.current = 0         # indice em self.pairs
        self.view_mode = VIEW_DIFF
        self.zoom = 1.0
        self.fit = True
        self.ox = 0.0
        self.oy = 0.0
        self.compare_session = None
        self.cache = None
        self.held = {}           # folhas do par atual, protegidas do LRU
        self.token = 0           # identifica a comparacao corrente
        self.busy = False
        self.started_at = 0.0
        self.run_label = "Comparação"
        self.plan_note = ""
        self._cancelled = False
        self._photo = None
        self._shown = None       # (id do par, raster) exibido no canvas
        self._render_pending = False
        self._drag = None
        self._last_dir = os.path.expanduser("~")
        self._ui_queue = queue.SimpleQueue()

        self._build_styles()
        self._build_ui()
        self._bind_shortcuts()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(0, self._style_title_bar)
        self.after(30, self._drain_ui_queue)
        # Pre-carrega os modulos pesados enquanto o usuario escolhe os arquivos.
        self.after(100, lambda: threading.Thread(target=self._warm_up, daemon=True).start())

    # ------------------------------------------------------------ setup

    @staticmethod
    def _warm_up():
        try:
            load_heavy_modules()
        except Exception:
            pass  # o erro aparece de forma clara quando o usuario comparar

    def _style_title_bar(self):
        """Barra de titulo escura no Windows 10/11."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            dark = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))
            r, g, b = (int(HEADER[i:i + 2], 16) for i in (1, 3, 5))
            caption = ctypes.c_int(r | (g << 8) | (b << 16))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), ctypes.sizeof(caption))
        except Exception:
            pass

    def _build_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Accent.Horizontal.TProgressbar", troughcolor=SURFACE_2, background=ACCENT,
                        bordercolor=SURFACE_2, lightcolor=ACCENT, darkcolor=ACCENT, thickness=px(4))
        style.configure("Dark.Vertical.TScrollbar", troughcolor=SURFACE, background=SURFACE_2,
                        bordercolor=SURFACE, lightcolor=SURFACE_2, darkcolor=SURFACE_2,
                        arrowcolor=MUTED, gripcount=0, arrowsize=px(12))
        style.map("Dark.Vertical.TScrollbar", background=[("active", HOVER)])
        style.configure("Pages.Treeview", background=SURFACE, fieldbackground=SURFACE, foreground=TEXT,
                        rowheight=px(28), borderwidth=0, font=ui_font(9))
        style.map("Pages.Treeview", background=[("selected", HOVER)], foreground=[("selected", "#FFFFFF")])
        style.configure("Pages.Treeview.Heading", background=SURFACE, foreground=SUBTLE, relief="flat",
                        borderwidth=0, font=ui_font(8, "bold"), padding=(px(4), px(4)))
        style.map("Pages.Treeview.Heading", background=[("active", SURFACE)])
        style.layout("Pages.Treeview", [("Pages.Treeview.treearea", {"sticky": "nswe"})])

        style.configure("Dark.TCombobox", fieldbackground=SURFACE_2, background=SURFACE_2, foreground=TEXT,
                        arrowcolor=MUTED, bordercolor=BORDER, lightcolor=SURFACE_2, darkcolor=SURFACE_2,
                        padding=(px(8), px(4)), arrowsize=px(12))
        style.map("Dark.TCombobox",
                  fieldbackground=[("readonly", SURFACE_2), ("disabled", SURFACE)],
                  foreground=[("disabled", SUBTLE), ("readonly", TEXT)],
                  selectbackground=[("readonly", SURFACE_2)], selectforeground=[("readonly", TEXT)],
                  bordercolor=[("focus", ACCENT)], arrowcolor=[("disabled", SUBTLE), ("active", TEXT)],
                  background=[("active", HOVER)])
        self.option_add("*TCombobox*Listbox.background", SURFACE_2)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
        self.option_add("*TCombobox*Listbox.font", ui_font(10))
        self.option_add("*TCombobox*Listbox.borderWidth", 0)

    def _build_ui(self):
        self._build_header()
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)

        sidebar = tk.Frame(body, bg=SURFACE, width=px(340))
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Frame(body, bg=BORDER, width=1).pack(side="left", fill="y")
        self._build_sidebar(sidebar)

        main = tk.Frame(body, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        self._build_toolbar(main)
        self._build_viewer(main)
        self._build_statusbar(main)

        self._set_view(VIEW_DIFF)
        self._update_page_info()
        self._sync_editor()

    def _build_header(self):
        header = tk.Frame(self, bg=HEADER, height=px(56))
        header.pack(fill="x")
        header.pack_propagate(False)

        size = px(26)
        logo = tk.Canvas(header, width=size, height=size, bg=HEADER, highlightthickness=0)
        unit = size / 26.0
        logo.create_rectangle(2 * unit, 8 * unit, 18 * unit, 24 * unit, outline=COLOR_OLD, width=max(2, px(2)))
        logo.create_rectangle(8 * unit, 2 * unit, 24 * unit, 18 * unit, outline=ACCENT, width=max(2, px(2)))
        logo.pack(side="left", padx=(px(20), px(12)))

        tk.Label(header, text=APP_TITLE, font=ui_font(13, "bold"), fg=TEXT, bg=HEADER).pack(side="left")
        tk.Frame(header, bg=BORDER, width=1, height=px(22)).pack(side="left", padx=px(14))
        tk.Label(header, text=APP_SUBTITLE, font=ui_font(10), fg=MUTED, bg=HEADER).pack(side="left")

    def _section_title(self, parent, text, pady=(0, 0)):
        label = tk.Label(parent, text=text.upper(), font=ui_font(8, "bold"), fg=SUBTLE, bg=SURFACE, anchor="w")
        label.pack(fill="x", pady=pady)
        return label

    def _build_sidebar(self, sidebar):
        side = tk.Frame(sidebar, bg=SURFACE)
        side.pack(fill="both", expand=True, padx=px(18), pady=px(18))

        # Arquivos
        files_header = tk.Frame(side, bg=SURFACE)
        files_header.pack(fill="x", pady=(0, px(8)))
        tk.Label(files_header, text="ARQUIVOS", font=ui_font(8, "bold"), fg=SUBTLE, bg=SURFACE).pack(side="left")
        self.swap_button = FlatButton(files_header, "Inverter", "swap", command=self._swap_files,
                                      variant="ghost", padx=6, pady=2, font_size=8)
        self.swap_button.pack(side="right")

        self.cards = {
            VIEW_OLD: FileCard(side, "Revisão anterior", COLOR_OLD, lambda: self._select_file(VIEW_OLD)),
            VIEW_NEW: FileCard(side, "Revisão atualizada", COLOR_NEW, lambda: self._select_file(VIEW_NEW)),
        }
        self.cards[VIEW_OLD].pack(fill="x")
        self.cards[VIEW_NEW].pack(fill="x", pady=(px(8), 0))

        # Acao principal
        self.compare_button = FlatButton(side, "Comparar revisões", "play", command=self.start_comparison,
                                         variant="primary", pady=11, font_size=10, bold=True)
        self.compare_button.pack(fill="x", pady=(px(22), 0))
        self.progress = ttk.Progressbar(side, mode="determinate", style="Accent.Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(px(12), 0))
        tk.Label(side, textvariable=self.status_var, font=ui_font(9), fg=MUTED, bg=SURFACE,
                 anchor="w", justify="left", wraplength=px(300)).pack(fill="x", pady=(px(6), 0))

        # Rodape: exportar e editor do par selecionado. A lista ocupa o resto.
        self.export_button = FlatButton(side, "Exportar resultados", "export", command=self.export_results,
                                        variant="secondary", pady=9)
        self.export_button.pack(side="bottom", fill="x", pady=(px(12), 0))
        self.export_button.set_enabled(False)
        self._build_pair_editor(side)

        self._section_title(side, "Folhas", pady=(px(22), px(6)))
        tree_frame = tk.Frame(side, bg=SURFACE)
        tree_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_frame, columns=("pair", "diff"), show="headings",
                                 style="Pages.Treeview", selectmode="browse")
        self.tree.heading("pair", text="ANT.  ↔  ATU.", anchor="w")
        self.tree.heading("diff", text="DIFERENÇA", anchor="e")
        self.tree.column("pair", anchor="w", width=px(110), stretch=True)
        self.tree.column("diff", anchor="e", width=px(130), stretch=True)
        self.tree.tag_configure("same", foreground=SUCCESS)
        self.tree.tag_configure("changed", foreground=TEXT)
        self.tree.tag_configure("pending", foreground=MUTED)
        self.tree.tag_configure("single", foreground=WARNING)
        self.tree.tag_configure("excluded", foreground=SUBTLE)
        self.tree.tag_configure("error", foreground=DANGER)
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview,
                               style="Dark.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

    def _build_pair_editor(self, side):
        """Painel para trocar o pareamento da linha selecionada ou exclui-la."""
        editor = tk.Frame(side, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        editor.pack(side="bottom", fill="x", pady=(px(12), 0))
        body = tk.Frame(editor, bg=SURFACE)
        body.pack(fill="x", padx=px(12), pady=px(10))
        body.columnconfigure(1, weight=1)

        tk.Label(body, text="FOLHA SELECIONADA", font=ui_font(8, "bold"), fg=SUBTLE,
                 bg=SURFACE, anchor="w").grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, px(8)))

        self.pair_combos = {}
        for row, (kind, title, color) in enumerate(((VIEW_OLD, "Anterior", COLOR_OLD),
                                                     (VIEW_NEW, "Atualizada", COLOR_NEW)), start=1):
            label = tk.Frame(body, bg=SURFACE)
            label.grid(row=row, column=0, sticky="w", pady=px(3))
            dot = tk.Canvas(label, width=px(8), height=px(8), bg=SURFACE, highlightthickness=0)
            dot.create_oval(0, 0, px(8), px(8), fill=color, outline="")
            dot.pack(side="left", padx=(0, px(6)))
            tk.Label(label, text=title, font=ui_font(9), fg=MUTED, bg=SURFACE, width=9,
                     anchor="w").pack(side="left")
            combo = ttk.Combobox(body, state="disabled", style="Dark.TCombobox", font=ui_font(10))
            combo.grid(row=row, column=1, sticky="ew", pady=px(3))
            combo.bind("<<ComboboxSelected>>", lambda _e, k=kind: self._on_pair_combo(k))
            self.pair_combos[kind] = combo

        self.exclude_button = FlatButton(body, "Excluir do compare", "hide", command=self._toggle_excluded,
                                         variant="ghost", padx=8, pady=5, font_size=9)
        self.exclude_button.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(px(8), 0))

    def _build_toolbar(self, main):
        bar = tk.Frame(main, bg=BG)
        bar.pack(fill="x", padx=px(16), pady=(px(12), px(10)))

        self.view_selector = Segmented(bar, [
            (VIEW_DIFF, "Comparação", "layers"),
            (VIEW_OLD, "Anterior", "doc"),
            (VIEW_NEW, "Atualizada", "doc"),
        ], self._set_view, font_size=9, padx=14, pady=6)
        self.view_selector.pack(side="left")

        zoom = tk.Frame(bar, bg=BG)
        zoom.pack(side="right")
        FlatButton(zoom, icon="zoom_out", text="" if ICON_FAMILY else "−", command=self.zoom_out,
                   variant="ghost", padx=8).pack(side="left")
        tk.Label(zoom, textvariable=self.zoom_var, font=ui_font(9), fg=TEXT, bg=BG,
                 width=12).pack(side="left")
        FlatButton(zoom, icon="zoom_in", text="" if ICON_FAMILY else "+", command=self.zoom_in,
                   variant="ghost", padx=8).pack(side="left")
        FlatButton(zoom, "Ajustar", "fit", command=self.fit_to_window, variant="ghost",
                   padx=10).pack(side="left", padx=(px(6), 0))
        FlatButton(zoom, "1:1", command=self.actual_size, variant="ghost", padx=10).pack(side="left")

        nav = tk.Frame(bar, bg=BG)
        nav.place(relx=0.5, rely=0.5, anchor="center")
        FlatButton(nav, icon="prev", text="" if ICON_FAMILY else "‹", command=self.previous_page,
                   variant="ghost", padx=8).pack(side="left")
        tk.Label(nav, textvariable=self.page_var, font=ui_font(10, "bold"), fg=TEXT, bg=BG,
                 padx=px(10)).pack(side="left")
        FlatButton(nav, icon="next", text="" if ICON_FAMILY else "›", command=self.next_page,
                   variant="ghost", padx=8).pack(side="left")

    def _build_viewer(self, main):
        frame = tk.Frame(main, bg=BORDER, padx=1, pady=1)
        frame.pack(fill="both", expand=True, padx=px(16))
        self.canvas = tk.Canvas(frame, bg=VIEWER_BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<Configure>", lambda _e: self._request_render())
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.canvas.bind("<Button-4>", lambda e: self._zoom_by(1.2, (e.x, e.y)))  # Linux
        self.canvas.bind("<Button-5>", lambda e: self._zoom_by(1 / 1.2, (e.x, e.y)))
        for button in ("1", "2"):
            self.canvas.bind(f"<ButtonPress-{button}>", self._start_pan)
            self.canvas.bind(f"<B{button}-Motion>", self._pan)
            self.canvas.bind(f"<ButtonRelease-{button}>", self._end_pan)
        self.canvas.bind("<Double-Button-1>", lambda _e: self.fit_to_window())

        # Elementos sobrepostos ao canvas
        self.badge = tk.Frame(self.canvas, bg=SURFACE, padx=px(12), pady=px(6))
        self.badge_dot = tk.Canvas(self.badge, width=px(10), height=px(10), bg=SURFACE, highlightthickness=0)
        self.badge_dot.pack(side="left", padx=(0, px(8)))
        self.badge_label = tk.Label(self.badge, font=ui_font(9, "bold"), fg=TEXT, bg=SURFACE)
        self.badge_label.pack(side="left")

        self.legend = tk.Frame(self.canvas, bg=SURFACE, padx=px(14), pady=px(8))
        for text, color in (("Comum", COLOR_COMMON), ("Somente anterior", COLOR_OLD),
                            ("Somente atualizada", COLOR_NEW)):
            swatch = tk.Frame(self.legend, bg=color, width=px(14), height=px(14),
                              highlightthickness=1, highlightbackground=MUTED if color == COLOR_COMMON else color)
            swatch.pack(side="left", padx=(0, px(6)))
            tk.Label(self.legend, text=text, font=ui_font(9), fg=TEXT, bg=SURFACE).pack(side="left", padx=(0, px(16)))

        self.loading = tk.Label(self.canvas, text="Carregando…", font=ui_font(9, "bold"),
                                fg="#FFFFFF", bg=ACCENT, padx=px(14), pady=px(6))

    def _build_statusbar(self, main):
        bar = tk.Frame(main, bg=BG)
        bar.pack(fill="x", padx=px(16), pady=(px(10), px(12)))

        def stat(parent, color, title):
            box = tk.Frame(parent, bg=BG)
            box.pack(side="left", padx=(0, px(22)))
            if color:
                dot = tk.Canvas(box, width=px(8), height=px(8), bg=BG, highlightthickness=0)
                dot.create_oval(0, 0, px(8), px(8), fill=color, outline="")
                dot.pack(side="left", padx=(0, px(6)))
            tk.Label(box, text=title, font=ui_font(9), fg=MUTED, bg=BG).pack(side="left", padx=(0, px(6)))
            value = tk.Label(box, text="–", font=ui_font(9, "bold"), fg=TEXT, bg=BG)
            value.pack(side="left")
            return value

        self.stat_diff = stat(bar, None, "Diferença sobre linhas")
        self.stat_removed = stat(bar, COLOR_OLD, "Somente anterior")
        self.stat_added = stat(bar, COLOR_NEW, "Somente atualizada")
        tk.Label(bar, text="1 2 3  vistas  ·  Espaço  alterna  ·  ←/→  folhas  ·  F  ajustar",
                 font=ui_font(8), fg=SUBTLE, bg=BG).pack(side="right")

    def _bind_shortcuts(self):
        self.bind("<Key>", self._on_key)

    # ------------------------------------------------------------ arquivos

    def _select_file(self, which):
        title = "Selecione a revisão anterior" if which == VIEW_OLD else "Selecione a revisão atualizada"
        path = filedialog.askopenfilename(title=title, initialdir=self._last_dir,
                                          filetypes=[("Arquivos PDF", "*.pdf"), ("Todos os arquivos", "*.*")])
        if not path:
            return
        self._last_dir = os.path.dirname(path)
        self.paths[which] = path
        self.cards[which].set_file(path)
        self.cards[which].set_meta("Lendo arquivo…")
        threading.Thread(target=self._read_info_worker, args=(which, path), daemon=True).start()

    def _read_info_worker(self, which, path):
        try:
            count, sizes = PDFComparator.pdf_info(path)
            text = f"{count} folha{'s' if count != 1 else ''}"
            if sizes:
                text += " · " + describe_page_size(*sizes[0])
                if len(set(sizes)) > 1:
                    text += " (tamanhos variados)"
            error = False
        except Exception as exc:
            text, error = f"Não foi possível ler o PDF: {exc}", True
        self._post(self._info_ready, which, path, text, error)

    def _info_ready(self, which, path, text, error):
        if self.paths[which] == path:
            self.cards[which].set_meta(text, error)

    def _swap_files(self):
        old_meta = (self.cards[VIEW_OLD].meta.cget("text"), self.cards[VIEW_OLD].meta.cget("fg"))
        new_meta = (self.cards[VIEW_NEW].meta.cget("text"), self.cards[VIEW_NEW].meta.cget("fg"))
        self.paths[VIEW_OLD], self.paths[VIEW_NEW] = self.paths[VIEW_NEW], self.paths[VIEW_OLD]
        for which, (text, fg) in ((VIEW_OLD, new_meta), (VIEW_NEW, old_meta)):
            self.cards[which].set_file(self.paths[which])
            self.cards[which].meta.configure(text=text, fg=fg)

    # ------------------------------------------------------------ comparacao

    def _post(self, callback, *args):
        """Agenda callback na thread da interface (seguro a partir de threads de trabalho)."""
        self._ui_queue.put((callback, args))

    def _drain_ui_queue(self):
        try:
            while True:
                callback, args = self._ui_queue.get_nowait()
                callback(*args)
        except queue.Empty:
            pass
        self.after(30, self._drain_ui_queue)

    def _set_status(self, text):
        self.status_var.set(text)

    def start_comparison(self):
        if self.busy:
            self.cancel_comparison()
            return

        old_path, new_path = self.paths[VIEW_OLD], self.paths[VIEW_NEW]
        if not os.path.isfile(old_path) or not os.path.isfile(new_path):
            messagebox.showwarning(APP_TITLE, "Selecione dois arquivos PDF válidos.")
            return

        self.token += 1
        if self.compare_session is not None:
            self.compare_session.close()
        if self.cache is not None:
            self.cache.close()
        self.compare_session = CompareSession(old_path, new_path)
        self.cache = RevisionCache(old_path, new_path, DEFAULT_DPI)
        self.pairs, self.held = [], {}
        self.current = 0
        self.fit = True
        self._shown = None
        self._cancelled = False
        self.plan_note = ""
        self.tree.delete(*self.tree.get_children())
        self.progress.configure(value=0, maximum=1)
        self._set_busy(True, "Comparação")
        self._set_status("Analisando as folhas…")
        self._update_overlays()
        self._update_page_info()
        self._sync_editor()
        self._request_render()

        token, session = self.token, self.compare_session
        session.runner.submit(lambda: self._plan_job(token, session), priority=0)

    def cancel_comparison(self):
        self._cancelled = True
        if self.compare_session is not None:
            self.compare_session.runner.clear()
        for pair in self.pairs:
            pair.queued_priority = None
        self._set_busy(False)
        done = sum(1 for p in self.pairs if p.raster is not None)
        total = sum(1 for p in self.pairs if p.comparable and not p.excluded)
        self._set_status(f"Cancelado · {done} de {total} par(es) comparados. "
                         f"Ao abrir um par pendente ele é comparado na hora.")
        self._refresh_tree()

    def _set_busy(self, busy, label=None):
        if busy and not self.busy:
            self.started_at = time.perf_counter()
            self.run_label = label or "Recomparação"
        self.busy = busy
        if busy:
            self.compare_button.set_content("Cancelar", "stop", variant="danger")
        else:
            self.compare_button.set_content("Comparar revisões", "play", variant="primary")
        self.compare_button.set_enabled(True)
        self.export_button.set_enabled(not busy and any(p.raster is not None for p in self.pairs))

    def _plan_job(self, token, session):
        try:
            pairs, counts, automatic = session.plan()
            self._post(self._plan_ready, token, pairs, counts, automatic)
        except Exception as exc:
            self._post(self._comparison_failed, token, str(exc))

    def _plan_ready(self, token, pair_specs, counts, automatic):
        if token != self.token:
            return
        self.sheet_counts = counts
        self.pairs = [SheetPair(old, new) for old, new in pair_specs]
        for kind, combo in self.pair_combos.items():
            combo.configure(values=["Nenhuma"] + [f"Folha {i + 1}" for i in range(counts[kind])])
        if automatic:
            self.plan_note = (f"Folhas: {counts[VIEW_OLD]} × {counts[VIEW_NEW]} · "
                              f"pareamento automático, ajuste se precisar.")
        if not self._cancelled:
            for pair in self.pairs:
                if pair.needs_compare:
                    self._queue_pair(pair, priority=1)
        self._refresh_tree()
        if self.pairs:
            self._show_pair(0)
        self._check_finished()

    def _queue_pair(self, pair, priority):
        """Coloca o par na fila. Prioridade 0 passa na frente da comparacao inicial."""
        if pair.queued_priority is not None and pair.queued_priority <= priority:
            return
        pair.queued_priority = priority
        token, session, version = self.token, self.compare_session, pair.version
        old, new = pair.old, pair.new

        def job():
            key = (pair.id, version)
            if pair.version != version or key in session.done:
                return  # par alterado ou ja comparado por outra tarefa
            session.done.add(key)
            try:
                diff, stats, old_image, new_image = session.compare(old, new)
                cache = self.cache
                if cache is not None and cache.paths == session.paths:
                    cache.put(VIEW_OLD, old, PageRaster(old_image))
                    cache.put(VIEW_NEW, new, PageRaster(new_image))
                self._post(self._pair_ready, token, pair, version, PageRaster(diff, indexed=True), stats, None)
            except Exception as exc:
                self._post(self._pair_ready, token, pair, version, None, None, str(exc))

        if not self.busy:
            self._set_busy(True)
        session.runner.submit(job, priority)
        self._update_row(pair)

    def _pair_ready(self, token, pair, version, raster, stats, error):
        if token != self.token or pair.version != version:
            return
        pair.raster, pair.stats, pair.error = raster, stats, error
        pair.queued_priority = None
        self._update_row(pair)
        if pair in self.pairs and self.pairs.index(pair) == self.current:
            self._update_overlays()
            self._update_page_info()
            self._request_render()
        self._check_finished()

    def _check_finished(self):
        total = sum(1 for p in self.pairs if p.comparable and not p.excluded)
        done = sum(1 for p in self.pairs if p.comparable and not p.excluded
                   and (p.raster is not None or p.error))
        self.progress.configure(maximum=max(1, total), value=done)
        pending = [p for p in self.pairs if p.queued_priority is not None]
        note = f"\n{self.plan_note}" if self.plan_note else ""
        if pending:
            self._set_status(f"Comparando… {done} de {total} par(es) prontos.{note}")
            return
        if not self.busy:
            return
        self._set_busy(False)
        elapsed = time.perf_counter() - self.started_at
        changed = sum(1 for p in self.pairs if p.stats and p.stats["changed_pixels"] and not p.excluded)
        singles = sum(1 for p in self.pairs if not p.comparable and not p.excluded)
        text = f"{self.run_label} concluída em {elapsed:.1f} s · {done} par(es), {changed} com alterações."
        if singles:
            text += f" {singles} folha(s) sem par."
        self._set_status(text + note)
        self._update_page_info()
        self._request_render()

    def _comparison_failed(self, token, error):
        if token != self.token:
            return
        self._set_busy(False)
        self._set_status("Falha na comparação.")
        self._request_render()
        messagebox.showerror(APP_TITLE, error)

    # ------------------------------------------------------------ pareamento manual

    def _pair_text(self, pair):
        old = str(pair.old + 1) if pair.old is not None else "–"
        new = str(pair.new + 1) if pair.new is not None else "–"
        return f"{old}   ↔   {new}"

    def _pair_status(self, pair):
        if pair.excluded:
            return "Excluída", "excluded"
        if not pair.comparable:
            return ("Só na anterior" if pair.new is None else "Só na atualizada"), "single"
        if pair.error:
            return "Erro", "error"
        if pair.stats is None:
            return ("Comparando…" if pair.queued_priority is not None else "Pendente"), "pending"
        if pair.stats["changed_pixels"] == 0:
            return "Sem alterações", "same"
        return fmt_pct(pair.stats["percent_changed"]), "changed"

    def _update_row(self, pair):
        if self.tree.exists(pair.id):
            status, tag = self._pair_status(pair)
            self.tree.item(pair.id, values=(self._pair_text(pair), status), tags=(tag,))

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for pair in self.pairs:
            status, tag = self._pair_status(pair)
            self.tree.insert("", "end", iid=pair.id, values=(self._pair_text(pair), status), tags=(tag,))
        if self.pairs:
            current = self.pairs[self.current].id
            self.tree.selection_set(current)
            self.tree.see(current)

    def _sync_editor(self):
        pair = self.pairs[self.current] if self.pairs else None
        for kind, combo in self.pair_combos.items():
            if pair is None:
                combo.set("")
                combo.configure(state="disabled")
                continue
            sheet = pair.old if kind == VIEW_OLD else pair.new
            combo.configure(state="readonly")
            combo.current(0 if sheet is None else sheet + 1)
        if pair is not None and pair.excluded:
            self.exclude_button.set_content("Incluir no compare", "show")
        else:
            self.exclude_button.set_content("Excluir do compare", "hide")
        self.exclude_button.set_enabled(pair is not None)

    def _on_pair_combo(self, kind):
        self.canvas.focus_set()  # devolve os atalhos de teclado ao visualizador
        if not self.pairs:
            return
        choice = self.pair_combos[kind].current()
        self._assign_sheet(self.pairs[self.current], kind, None if choice <= 0 else choice - 1)

    def _assign_sheet(self, pair, kind, sheet):
        """Muda a folha de um lado do par mantendo cada folha em exatamente uma linha.

        Se a folha escolhida estava em outra linha, as duas linhas trocam de folha.
        Se o lado for esvaziado, a folha liberada vira uma linha propria (sem par).
        """
        attr = "old" if kind == VIEW_OLD else "new"
        previous = getattr(pair, attr)
        if previous == sheet:
            return
        changed = [pair]
        other = next((p for p in self.pairs if p is not pair and getattr(p, attr) == sheet), None)
        if sheet is not None and other is not None:
            setattr(other, attr, previous)
            changed.append(other)
        setattr(pair, attr, sheet)
        if sheet is None:
            orphan = SheetPair(previous, None) if kind == VIEW_OLD else SheetPair(None, previous)
            self.pairs.insert(self.pairs.index(pair) + 1, orphan)

        self.pairs = [p for p in self.pairs if p.old is not None or p.new is not None]
        if pair not in self.pairs:  # a linha atual ficou vazia
            self.current = min(self.current, len(self.pairs) - 1)
        else:
            self.current = self.pairs.index(pair)
        for item in changed:
            item.reset()
            if item in self.pairs and item.needs_compare:
                self._queue_pair(item, priority=0 if item is pair else 1)
        self._refresh_tree()
        self._show_pair(self.current, force=True)
        self._check_finished()

    def _toggle_excluded(self):
        if not self.pairs:
            return
        pair = self.pairs[self.current]
        pair.excluded = not pair.excluded
        if pair.needs_compare and pair.queued_priority is None:
            self._queue_pair(pair, priority=0)
        self._update_row(pair)
        self._sync_editor()
        self._update_overlays()
        self._check_finished()
        if not self.busy:
            included = sum(1 for p in self.pairs if p.comparable and not p.excluded)
            self._set_status(f"{included} par(es) incluídos no compare.")

    # ------------------------------------------------------------ navegacao e vistas

    def _show_pair(self, index, force=False):
        if not 0 <= index < len(self.pairs):
            return
        if index != self.current or force:
            if self._shown is not None:
                self._shown[1].drop_levels()
            self.held = {}
        self.current = index
        pair = self.pairs[index]
        if self.tree.exists(pair.id):
            if self.tree.selection() != (pair.id,):
                self.tree.selection_set(pair.id)
            self.tree.see(pair.id)
        if pair.needs_compare:
            self._queue_pair(pair, priority=0)  # o par aberto passa na frente da fila
        self._prefetch()
        self._sync_editor()
        self._update_overlays()
        self._update_page_info()
        self._request_render()

    def _on_tree_select(self, _event):
        selection = self.tree.selection()
        if not selection:
            return
        index = next((i for i, p in enumerate(self.pairs) if p.id == selection[0]), None)
        if index is not None and index != self.current:
            self._show_pair(index)

    def previous_page(self):
        self._show_pair(self.current - 1)

    def next_page(self):
        self._show_pair(self.current + 1)

    def _set_view(self, mode):
        self.view_mode = mode
        self.view_selector.set(mode)
        self._update_overlays()
        self._request_render()

    def toggle_revision(self):
        self._set_view(VIEW_NEW if self.view_mode == VIEW_OLD else VIEW_OLD)

    def _prefetch(self):
        """Garante as folhas do par atual em memoria (ou as carrega em segundo plano)."""
        if self.cache is None or not self.pairs:
            return
        pair = self.pairs[self.current]
        for kind, sheet in ((VIEW_OLD, pair.old), (VIEW_NEW, pair.new)):
            if sheet is None or (kind, sheet) in self.held:
                continue
            raster = self.cache.get(kind, sheet)
            if raster is not None:
                self.held[(kind, sheet)] = raster
            else:
                self.cache.request(kind, sheet, self._on_revision_loaded)

    def _on_revision_loaded(self, cache, kind, index, error):
        self._post(self._revision_loaded, cache, kind, index, error)

    def _revision_loaded(self, cache, kind, sheet, error):
        if cache is not self.cache or not self.pairs:
            return
        pair = self.pairs[self.current]
        if sheet != (pair.old if kind == VIEW_OLD else pair.new):
            return
        if error is not None:
            self._set_status(f"Erro ao carregar a folha: {error}")
            self._set_loading(None)
            return
        raster = cache.get(kind, sheet)
        if raster is not None:
            self.held[(kind, sheet)] = raster
        self._request_render()

    def _sheet_raster(self, kind, sheet):
        key = (kind, sheet)
        raster = self.held.get(key)
        if raster is None and self.cache is not None:
            raster = self.cache.get(*key)
            if raster is None:
                self.cache.request(kind, sheet, self._on_revision_loaded)
            else:
                self.held[key] = raster
        return raster

    def _resolve_view(self):
        """Retorna (raster, estado) do que deve aparecer no visualizador.

        Estados: ok, comparing, loading, missing, error.
        """
        pair = self.pairs[self.current]
        if self.view_mode == VIEW_DIFF:
            if pair.comparable:
                if pair.raster is not None:
                    return pair.raster, "ok"
                if pair.error:
                    return None, "error"
                return None, "comparing"
            kind = VIEW_OLD if pair.old is not None else VIEW_NEW
        else:
            kind = self.view_mode
        sheet = pair.old if kind == VIEW_OLD else pair.new
        if sheet is None:
            return None, "missing"
        raster = self._sheet_raster(kind, sheet)
        return (raster, "ok") if raster is not None else (None, "loading")

    def _update_overlays(self):
        if not self.pairs:
            self.badge.place_forget()
            self.legend.place_forget()
            self._set_loading(None)
            return

        pair = self.pairs[self.current]
        paths = self.cache.paths if self.cache is not None else self.paths
        if self.view_mode == VIEW_DIFF and pair.comparable:
            text, color = f"Comparação · folha {pair.old + 1} × folha {pair.new + 1}", ACCENT
            if pair.stats and pair.stats.get("resized"):
                text += " · tamanhos diferentes (ajustado)"
        else:
            if self.view_mode == VIEW_DIFF:
                kind = VIEW_OLD if pair.old is not None else VIEW_NEW
                prefix = "Sem par · "
            else:
                kind, prefix = self.view_mode, ""
            sheet = pair.old if kind == VIEW_OLD else pair.new
            label = "Revisão anterior" if kind == VIEW_OLD else "Revisão atualizada"
            if sheet is None:
                text = f"{label} · sem folha correspondente"
            else:
                text = f"{prefix}{label} · folha {sheet + 1} · {elide(os.path.basename(paths[kind]), 40)}"
            color = COLOR_OLD if kind == VIEW_OLD else COLOR_NEW
        if pair.excluded:
            text += " · excluída do compare"
        self.badge_label.configure(text=text)
        self.badge_dot.delete("all")
        self.badge_dot.create_oval(0, 0, px(10), px(10), fill=color, outline="")
        self.badge.place(x=px(14), y=px(14), anchor="nw")

        if self.view_mode == VIEW_DIFF and pair.comparable:
            self.legend.place(x=px(14), rely=1.0, y=-px(14), anchor="sw")
        else:
            self.legend.place_forget()

    def _set_loading(self, text):
        if text:
            self.loading.configure(text=text)
            self.loading.place(relx=0.5, y=px(14), anchor="n")
        else:
            self.loading.place_forget()

    def _update_page_info(self):
        labels = (self.stat_diff, self.stat_removed, self.stat_added)
        if not self.pairs:
            self.page_var.set("–")
            self.zoom_var.set("–")
            for label in labels:
                label.configure(text="–")
            return
        pair = self.pairs[self.current]
        old = f"{pair.old + 1}" if pair.old is not None else "–"
        new = f"{pair.new + 1}" if pair.new is not None else "–"
        self.page_var.set(f"Folha {old} ↔ {new}   ·   {self.current + 1} de {len(self.pairs)}")
        stat = pair.stats
        if stat is None:
            for label in labels:
                label.configure(text="–")
            return
        self.stat_diff.configure(text=fmt_pct(stat["percent_changed"]))
        self.stat_removed.configure(text=f"{fmt_int(stat['removed_pixels'])} px")
        self.stat_added.configure(text=f"{fmt_int(stat['added_pixels'])} px")

    # ------------------------------------------------------------ renderizacao

    def _request_render(self):
        if not self._render_pending:
            self._render_pending = True
            self.after_idle(self._render)

    def _canvas_size(self):
        return max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())

    def _fit_zoom(self, width, height, cw, ch):
        margin = px(28)
        return max(0.005, min((cw - 2 * margin) / width, (ch - 2 * margin) / height))

    def _clamp_offsets(self, width, height, cw, ch):
        dw, dh = width * self.zoom, height * self.zoom
        overscroll = px(60)
        if dw <= cw:
            self.ox = (dw - cw) / 2
        else:
            self.ox = min(max(self.ox, -overscroll), dw - cw + overscroll)
        if dh <= ch:
            self.oy = (dh - ch) / 2
        else:
            self.oy = min(max(self.oy, -overscroll), dh - ch + overscroll)

    def _render(self):
        self._render_pending = False
        cw, ch = self._canvas_size()
        if cw < 10 or ch < 10:
            return
        if not self.pairs:
            if self.busy:
                self._draw_message("sync", "Analisando as folhas…",
                                   "As folhas aparecem aqui assim que ficam prontas.")
            else:
                self._draw_message("layers", "Nenhuma comparação carregada",
                                   "Selecione a revisão anterior e a atualizada na barra lateral\n"
                                   "e clique em Comparar revisões.")
            return

        pair = self.pairs[self.current]
        raster, state = self._resolve_view()
        self._set_loading({"comparing": "Comparando folhas…",
                           "loading": "Carregando folha…"}.get(state))
        if raster is None:
            if state in ("comparing", "loading"):
                if self._shown is not None and self._shown[0] == pair.id:
                    return  # mantem a imagem atual ate a nova ficar pronta
                # mostra a folha disponivel do par enquanto a comparacao roda
                for kind, sheet in ((VIEW_OLD, pair.old), (VIEW_NEW, pair.new)):
                    if sheet is not None:
                        raster = self._sheet_raster(kind, sheet)
                        if raster is not None:
                            break
            if raster is None:
                if state == "missing":
                    side = "anterior" if self.view_mode == VIEW_OLD else "atualizada"
                    self._draw_message("warning", f"Esta linha não tem folha na revisão {side}",
                                       "Use o painel Folha selecionada para escolher uma folha\n"
                                       "ou veja a outra revisão.")
                elif state == "error":
                    self._draw_message("warning", "Não foi possível comparar este par", pair.error or "")
                else:
                    self._draw_message("sync", "Carregando…", "")
                return

        self.canvas.delete("empty")
        if self.fit:
            self.zoom = self._fit_zoom(raster.width, raster.height, cw, ch)
        self._clamp_offsets(raster.width, raster.height, cw, ch)
        self.zoom_var.set(f"Ajustado · {self.zoom * 100:.0f}%" if self.fit else f"{self.zoom * 100:.0f}%")

        result = raster.render(self.zoom, self.ox, self.oy, cw, ch)
        self.canvas.delete("page")
        x0, y0 = -self.ox, -self.oy
        x1, y1 = x0 + raster.width * self.zoom, y0 + raster.height * self.zoom
        shadow = px(5)
        self.canvas.create_rectangle(x0 + shadow, y0 + shadow, x1 + shadow, y1 + shadow,
                                     fill=SHADOW, outline="", tags="page")
        if result is not None:
            image, dx, dy = result
            self._photo = ImageTk.PhotoImage(image)
            self.canvas.create_image(int(round(dx)), int(round(dy)), image=self._photo,
                                     anchor="nw", tags="page")
        self._shown = (pair.id, raster)

    def _draw_message(self, icon, title, subtitle):
        canvas = self.canvas
        canvas.delete("all")
        self._shown = None
        cw, ch = self._canvas_size()
        cx, cy = cw / 2, ch / 2
        if ICON_FAMILY:
            canvas.create_text(cx, cy - px(52), text=GLYPHS[icon], font=icon_font(34), fill=SUBTLE, tags="empty")
        canvas.create_text(cx, cy, text=title, font=ui_font(15, "bold"), fill=TEXT, tags="empty")
        canvas.create_text(cx, cy + px(26), text=subtitle, font=ui_font(10), fill=MUTED,
                           justify="center", anchor="n", tags="empty")

    # ------------------------------------------------------------ zoom e arraste

    def _zoom_by(self, factor, anchor=None):
        if self._shown is None:
            return
        raster = self._shown[1]
        cw, ch = self._canvas_size()
        fit_zoom = self._fit_zoom(raster.width, raster.height, cw, ch)
        new_zoom = min(MAX_ZOOM, max(fit_zoom * 0.5, self.zoom * factor))
        ax, ay = anchor if anchor else (cw / 2, ch / 2)
        # Mantem fixo o ponto sob o cursor.
        ix, iy = (self.ox + ax) / self.zoom, (self.oy + ay) / self.zoom
        self.zoom, self.fit = new_zoom, False
        self.ox, self.oy = ix * new_zoom - ax, iy * new_zoom - ay
        self._request_render()

    def zoom_in(self):
        self._zoom_by(1.25)

    def zoom_out(self):
        self._zoom_by(1 / 1.25)

    def fit_to_window(self):
        self.fit = True
        self._request_render()

    def actual_size(self):
        if self.zoom:
            self._zoom_by(1.0 / self.zoom)

    def on_mouse_wheel(self, event):
        self._zoom_by(1.2 ** (event.delta / 120.0), (event.x, event.y))
        return "break"

    def _start_pan(self, event):
        self.canvas.focus_set()
        self._drag = (event.x, event.y, self.ox, self.oy)
        if self._shown is not None:
            self.canvas.configure(cursor="fleur")

    def _pan(self, event):
        if self._drag is None or self._shown is None:
            return
        x, y, ox, oy = self._drag
        self.ox, self.oy = ox - (event.x - x), oy - (event.y - y)
        self._request_render()

    def _end_pan(self, _event):
        self._drag = None
        self.canvas.configure(cursor="")

    def _on_key(self, event):
        if isinstance(self.focus_get(), (tk.Entry, ttk.Entry)):
            return
        actions = {
            "1": lambda: self._set_view(VIEW_DIFF),
            "2": lambda: self._set_view(VIEW_OLD),
            "3": lambda: self._set_view(VIEW_NEW),
            "space": self.toggle_revision,
            "Left": self.previous_page,
            "Prior": self.previous_page,
            "Right": self.next_page,
            "Next": self.next_page,
            "f": self.fit_to_window,
            "F": self.fit_to_window,
            "0": self.actual_size,
            "plus": self.zoom_in,
            "equal": self.zoom_in,
            "KP_Add": self.zoom_in,
            "minus": self.zoom_out,
            "KP_Subtract": self.zoom_out,
        }
        action = actions.get(event.keysym)
        if action:
            action()
            return "break"

    # ------------------------------------------------------------ exportacao

    def export_results(self):
        if self.busy:
            return
        pairs = [p for p in self.pairs if p.raster is not None and not p.excluded]
        if not pairs:
            messagebox.showinfo(APP_TITLE, "Não há pares comparados para exportar.")
            return
        folder = filedialog.askdirectory(title="Selecione a pasta de destino", initialdir=self._last_dir)
        if not folder:
            return
        self.export_button.set_enabled(False)
        self.compare_button.set_enabled(False)
        self._set_status("Exportando…")
        jobs = [(p.old, p.new, p.raster) for p in pairs]
        threading.Thread(target=self._export_worker, args=(folder, jobs, DEFAULT_DPI), daemon=True).start()

    def _export_worker(self, folder, jobs, dpi):
        try:
            load_heavy_modules()
            pdf_path = os.path.join(folder, "comparacao_completa.pdf")
            with FITZ_LOCK:
                document = fitz.open()
            try:
                for index, (old, new, raster) in enumerate(jobs, start=1):
                    image = Image.fromarray(raster.levels[0])
                    image.putpalette(PALETTE_FLAT)
                    buffer = io.BytesIO()
                    image.save(buffer, "PNG", compress_level=3)
                    data = buffer.getvalue()
                    name = f"comparacao_{index:02d}_ant{old + 1}_atu{new + 1}.png"
                    with open(os.path.join(folder, name), "wb") as handle:
                        handle.write(data)
                    # Pagina do PDF com o mesmo tamanho fisico do desenho original.
                    with FITZ_LOCK:
                        page = document.new_page(width=raster.width * 72.0 / dpi,
                                                 height=raster.height * 72.0 / dpi)
                        page.insert_image(page.rect, stream=data)
                    self._post(self._set_status, f"Exportando par {index} de {len(jobs)}…")
                with FITZ_LOCK:
                    document.save(pdf_path, deflate=True)
            finally:
                with FITZ_LOCK:
                    document.close()
            self._post(self._export_finished, None, pdf_path, len(jobs))
        except Exception as exc:
            self._post(self._export_finished, str(exc), None, 0)

    def _export_finished(self, error, pdf_path, count):
        self.export_button.set_enabled(True)
        self.compare_button.set_enabled(True)
        if error:
            self._set_status("Falha na exportação.")
            messagebox.showerror(APP_TITLE, f"Não foi possível exportar:\n{error}")
        else:
            self._set_status(f"Exportado: {count} par(es).")
            messagebox.showinfo(APP_TITLE, f"Arquivos exportados com sucesso.\n\nPDF: {pdf_path}\n"
                                           f"PNG: {count} par(es) comparado(s).")

    # ------------------------------------------------------------ encerramento

    def _on_close(self):
        if self.compare_session is not None:
            self.compare_session.close()
        if self.cache is not None:
            self.cache.close()
        self.destroy()


def main():
    prepare_windows_process()
    app = ComparatorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
