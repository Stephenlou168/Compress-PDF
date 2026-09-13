import ctypes
import io
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import zlib

import pikepdf
from pikepdf import PdfImage
from PIL import Image

# Enable High DPI Awareness on Windows to fix visual blurriness
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# Enable Drag and Drop support if library exists; fallback smoothly if missing
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    BaseClass = TkinterDnD.Tk
    DND_AVAILABLE = True
except ImportError:
    BaseClass = tk.Tk
    DND_AVAILABLE = False

PRESETS = {
    "Max Compression": 
    {
        "quality": 30, 
        "max_dimension": 1000
    },
    "Balanced": 
    {
        "quality": 65, 
        "max_dimension": 1600
    },
    "High Quality": 
    {
        "quality": 85, 
        "max_dimension": 2400
    },
    "Custom": None,
}


def compress_pdf(input_path, output_path, quality, max_dimension, progress_callback=None):

    pdf = pikepdf.open(input_path)
    pages = list(pdf.pages)
    total = max(len(pages), 1)

    for i, page in enumerate(pages):
        for _name, raw_image in page.images.items():

            src_cs = raw_image.get("/ColorSpace")
            safe_cs = True

            if src_cs is not None:
                if isinstance(src_cs, pikepdf.Name):
                    safe_cs = str(src_cs) in (
                        "/DeviceRGB",
                        "/DeviceGray",
                        "/DeviceCMYK",
                        "/CalRGB",
                        "/CalGray",
                    )
                elif isinstance(src_cs, pikepdf.Array) and len(src_cs) > 0:
                    safe_cs = str(src_cs[0]) == "/ICCBased"
                else:
                    safe_cs = False
            if not safe_cs:
                continue

            try:
                pdf_image = PdfImage(raw_image)
                pil_image = pdf_image.as_pil_image()
            except Exception:
                continue

            src_filter = raw_image.get("/Filter")
            is_jpeg_source = src_filter == pikepdf.Name("/DCTDecode") or ( isinstance(src_filter, pikepdf.Array) and pikepdf.Name("/DCTDecode") in src_filter)

            if pil_image.mode != "RGB":
                pil_image = pil_image.convert("RGB")

            smask_obj = raw_image.get("/SMask")
            smask_image = None
            if smask_obj is not None:
                try:
                    smask_image = PdfImage(smask_obj).as_pil_image()
                    if smask_image.mode != "L":
                        smask_image = smask_image.convert("L")
                except Exception:
                    smask_image = None

            resized = False
            if max_dimension:
                w, h = pil_image.size
                longest = max(w, h)
                if longest > max_dimension:
                    scale = max_dimension / longest
                    new_size = (
                        max(1, int(w * scale)),
                        max(1, int(h * scale)),
                    )
                    pil_image = pil_image.resize(new_size, Image.LANCZOS)
                    if smask_image is not None:
                        smask_image = smask_image.resize( new_size, Image.LANCZOS )
                    resized = True

            if not is_jpeg_source and not resized:
                continue

            for key in ("/Mask", "/Decode"):
                if key in raw_image:
                    del raw_image[key]
            if smask_image is None and "/SMask" in raw_image:
                del raw_image["/SMask"]

            if is_jpeg_source:
                buf = io.BytesIO()
                pil_image.save(buf, format="JPEG", quality=quality)
                raw_image.write( buf.getvalue(), filter=pikepdf.Name("/DCTDecode") )
            else:
                raw_bytes = pil_image.tobytes()
                raw_image.write(
                    zlib.compress(raw_bytes, level=9),
                    filter=pikepdf.Name("/FlateDecode"),
                )

            raw_image.Width = pil_image.width
            raw_image.Height = pil_image.height
            raw_image.ColorSpace = pikepdf.Name("/DeviceRGB")
            raw_image.BitsPerComponent = 8

            if smask_image is not None:
                smask_bytes = zlib.compress(smask_image.tobytes(), level=9)
                smask_obj.write(smask_bytes, filter=pikepdf.Name("/FlateDecode"))
                smask_obj.Width = smask_image.width
                smask_obj.Height = smask_image.height
                smask_obj.ColorSpace = pikepdf.Name("/DeviceGray")
                smask_obj.BitsPerComponent = 8
                for key in ("/DecodeParms", "/Decode"):
                    if key in smask_obj:
                        del smask_obj[key]

        if progress_callback:
            progress_callback((i + 1) / total * 100)

    pdf.save(
        output_path,
        compress_streams=True,
        object_stream_mode=pikepdf.ObjectStreamMode.generate,
    )
    pdf.close()


class PDFCompressorApp(BaseClass):
    """PDF Compressor Interface."""

    BG_DARK = "#121212"
    CARD_BG = "#1A1A1E"
    DROPZONE_BG = "#222228"
    BORDER_COLOR = "#2D2D35"

    GOLD = "#D4AF37"
    GOLD_HOVER = "#E5C158"
    TEXT_MAIN = "#F3F3F5"
    TEXT_MUTED = "#8A8A93"
    ERROR_COLOR = "#FF5555"

    def __init__(self):
        super().__init__()
        self.title("PDF Compressor")
        self.geometry("700x720")
        self.minsize(550, 500)
        self.configure(bg=self.BG_DARK)

        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.preset = tk.StringVar(value="Balanced")
        self.quality = tk.DoubleVar(value=65)
        self.max_dimension = tk.DoubleVar(value=1600)

        self._setup_style()
        self._build_scrollable_ui()
        self.apply_preset()

    def _setup_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background=self.BG_DARK)
        style.configure("Card.TFrame", background=self.CARD_BG)

        # Headings
        style.configure(
            "HeroTitle.TLabel",
            background=self.BG_DARK,
            foreground=self.TEXT_MAIN,
            font=("Segoe UI", 20, "bold"),
        )
        style.configure(
            "HeroSubtitle.TLabel",
            background=self.BG_DARK,
            foreground=self.TEXT_MUTED,
            font=("Segoe UI", 9),
        )

        style.configure(
            "CardHeader.TLabel",
            background=self.CARD_BG,
            foreground=self.GOLD,
            font=("Segoe UI", 10, "bold"),
        )
        style.configure(
            "CardMuted.TLabel",
            background=self.CARD_BG,
            foreground=self.TEXT_MUTED,
            font=("Segoe UI", 9),
        )
        style.configure(
            "CardLabel.TLabel",
            background=self.CARD_BG,
            foreground=self.TEXT_MAIN,
            font=("Segoe UI", 9, "bold"),
        )
        style.configure(
            "Value.TLabel",
            background=self.CARD_BG,
            foreground=self.GOLD,
            font=("Segoe UI", 9, "bold"),
        )

        # Controls
        style.configure(
            "TRadiobutton",
            background=self.CARD_BG,
            foreground=self.TEXT_MAIN,
            font=("Segoe UI", 9),
        )
        style.map(
            "TRadiobutton",
            background=[("active", self.CARD_BG)],
            foreground=[("selected", self.GOLD)],
        )

        style.configure(
            "Horizontal.TScale",
            background=self.CARD_BG,
            troughcolor="#121212",
            sliderthickness=14,
            borderwidth=0,
        )

        style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#121212",
            background=self.GOLD,
            borderwidth=0,
            thickness=4,
        )

        # Primary Button
        style.configure(
            "Primary.TButton",
            font=("Segoe UI", 9, "bold"),
            foreground="#121212",
            background=self.GOLD,
            borderwidth=0,
            padding=(16, 8),
        )
        style.map(
            "Primary.TButton",
            background=[("active", self.GOLD_HOVER), ("disabled", "#333333")],
            foreground=[("disabled", "#666666")],
        )

    def _build_scrollable_ui(self):

        self.canvas = tk.Canvas( self, bg=self.BG_DARK, highlightthickness=0, borderwidth=0 )
        self.scrollbar = ttk.Scrollbar( self, orient="vertical", command=self.canvas.yview )
        self.scroll_frame = ttk.Frame(self.canvas, style="TFrame")

        self.scroll_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")
            ),
        )

        self.canvas_window = self.canvas.create_window( (0, 0), window=self.scroll_frame, anchor="nw" )
        self.canvas.bind( "<Configure>", lambda e: self.canvas.itemconfig(self.canvas_window, width=e.width))

        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # Enable mousewheel scrolling
        self.bind_all(
            "<MouseWheel>",
            lambda e: self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"),
        )

        self._build_ui(self.scroll_frame)

    def _build_ui(self, parent):
        container = ttk.Frame(parent, padding=(24, 20, 24, 20))
        container.pack(fill="both", expand=True)

        # Header Hero
        ttk.Label(
            container, text="Compress & Optimize PDF", style="HeroTitle.TLabel"
        ).pack(anchor="center")
        ttk.Label(
            container,
            text="Reduce file size by downsampling embedded images and streamlining object streams.",
            style="HeroSubtitle.TLabel",
        ).pack(anchor="center", pady=(2, 16))

        # Central Dropzone Box
        drop_wrapper = tk.Frame(
            container,
            bg=self.BORDER_COLOR,
            padx=1,
            pady=1,
        )
        drop_wrapper.pack(fill="x", pady=(0, 14))

        self.drop_card = tk.Frame(
            drop_wrapper, bg=self.DROPZONE_BG, padx=16, pady=18
        )
        self.drop_card.pack(fill="both", expand=True)

        self.icon_label = tk.Label(
            self.drop_card,
            text="📄",
            font=("Segoe UI", 22),
            bg=self.DROPZONE_BG,
            fg=self.GOLD,
        )
        self.icon_label.pack()

        self.drop_title = tk.Label(
            self.drop_card,
            text="Select your PDF file or drop it here",
            font=("Segoe UI", 11, "bold"),
            bg=self.DROPZONE_BG,
            fg=self.TEXT_MAIN,
        )
        self.drop_title.pack(pady=(4, 2))

        self.file_status = tk.Label(
            self.drop_card,
            text="No file selected",
            font=("Segoe UI", 8),
            bg=self.DROPZONE_BG,
            fg=self.TEXT_MUTED,
        )
        self.file_status.pack(pady=(0, 10))

        browse_btn = ttk.Button(
            self.drop_card,
            text="Select File",
            command=self.browse_input,
            style="Primary.TButton",
        )
        browse_btn.pack()

        # Drag & Drop Binding
        if DND_AVAILABLE:
            self.drop_card.drop_target_register(DND_FILES)
            self.drop_card.dnd_bind("<<Drop>>", self._on_drop_file)

        # Presets Card
        preset_card = self._create_card(container)
        ttk.Label(
            preset_card, text="Compression Preset", style="CardHeader.TLabel"
        ).pack(anchor="w", pady=(0, 6))

        preset_grid = ttk.Frame(preset_card, style="Card.TFrame")
        preset_grid.pack(fill="x")

        for name in PRESETS:
            rb = ttk.Radiobutton(
                preset_grid,
                text=name,
                value=name,
                variable=self.preset,
                command=self.apply_preset,
            )
            rb.pack(side="left", expand=True, anchor="w")

        # Custom Fine-Tuning Card
        custom_card = self._create_card(container)
        ttk.Label(
            custom_card, text="Custom Controls", style="CardHeader.TLabel"
        ).pack(anchor="w")

        q_row = ttk.Frame(custom_card, style="Card.TFrame")
        q_row.pack(fill="x", pady=(6, 2))
        ttk.Label(
            q_row, text="JPEG Quality", style="CardLabel.TLabel", width=14
        ).pack(side="left")

        self.quality_scale = ttk.Scale(
            q_row,
            from_=10,
            to=95,
            variable=self.quality,
            orient="horizontal",
            command=self._update_quality_label,
        )
        self.quality_scale.pack(side="left", fill="x", expand=True, padx=8)

        self.quality_label = ttk.Label(
            q_row, text="65%", style="Value.TLabel", width=6, anchor="e"
        )
        self.quality_label.pack(side="right")

        d_row = ttk.Frame(custom_card, style="Card.TFrame")
        d_row.pack(fill="x", pady=2)
        ttk.Label(
            d_row, text="Max Dimension", style="CardLabel.TLabel", width=14
        ).pack(side="left")

        self.dim_scale = ttk.Scale(
            d_row,
            from_=400,
            to=3000,
            variable=self.max_dimension,
            orient="horizontal",
            command=self._update_dimension_label,
        )
        self.dim_scale.pack(side="left", fill="x", expand=True, padx=8)

        self.dim_label = ttk.Label(
            d_row, text="1600 px", style="Value.TLabel", width=8, anchor="e"
        )
        self.dim_label.pack(side="right")

        # Footer Actions
        action_row = ttk.Frame(container, style="TFrame")
        action_row.pack(fill="x", pady=(8, 0))

        self.compress_btn = ttk.Button(
            action_row,
            text="Compress PDF",
            command=self.start_compression,
            style="Primary.TButton",
        )
        self.compress_btn.pack(side="left")

        status_container = ttk.Frame(action_row, style="TFrame")
        status_container.pack(side="left", fill="x", expand=True, padx=(16, 0))

        self.status_label = ttk.Label(
            status_container,
            text="Ready",
            style="HeroSubtitle.TLabel",
        )
        self.status_label.pack(anchor="w", pady=(0, 2))

        self.progress = ttk.Progressbar(
            status_container,
            mode="determinate",
            style="Horizontal.TProgressbar",
        )
        self.progress.pack(fill="x")

        self.result_label = ttk.Label(
            container,
            text="",
            justify="left",
            style="HeroSubtitle.TLabel",
            wraplength=600,
        )
        self.result_label.pack(fill="x", pady=(10, 0))

    def _create_card(self, parent):
        wrapper = tk.Frame(
            parent,
            bg=self.BORDER_COLOR,
            padx=1,
            pady=1,
        )
        wrapper.pack(fill="x", pady=(0, 10))

        inner = ttk.Frame(wrapper, style="Card.TFrame", padding=(14, 10))
        inner.pack(fill="both", expand=True)
        return inner

    def _on_drop_file(self, event):
        path = event.data.strip("{}")
        if path.lower().endswith(".pdf") and os.path.isfile(path):
            self.set_selected_file(path)
        else:
            messagebox.showerror(
                "Invalid File", "Please drop a valid .pdf file."
            )

    def set_selected_file(self, path):
        self.input_path.set(path)
        base, _ext = os.path.splitext(path)
        self.output_path.set(f"{base}_compressed.pdf")

        filename = os.path.basename(path)
        self.drop_title.config(text=filename)
        self.file_status.config(text=f"Path: {path}")
        self.result_label.config(text="")
        self.status_label.config(text="Ready")

    def browse_input(self):
        path = filedialog.askopenfilename(
            title="Select PDF Document",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self.set_selected_file(path)

    def _update_quality_label(self, _value=None):
        self.quality_label.config(text=f"{int(round(self.quality.get()))}%")

    def _update_dimension_label(self, _value=None):
        self.dim_label.config(text=f"{int(round(self.max_dimension.get()))} px")

    def apply_preset(self):
        name = self.preset.get()
        if name == "Custom":
            self._set_advanced_state("normal")
            return

        self._set_advanced_state("disabled")
        cfg = PRESETS[name]
        self.quality.set(cfg["quality"])
        self.max_dimension.set(cfg["max_dimension"])
        self._update_quality_label()
        self._update_dimension_label()

    def _set_advanced_state(self, state):
        self.quality_scale.config(state=state)
        self.dim_scale.config(state=state)

    def _set_busy(self, busy):
        self.compress_btn.config(state="disabled" if busy else "normal")
        self.status_label.config(text="Processing..." if busy else "Ready")

    def start_compression(self):
        input_path = self.input_path.get().strip()

        if not input_path or not os.path.isfile(input_path):
            messagebox.showerror(
                "Invalid Input",
                "Please select or drop a valid PDF file before starting.",
            )
            return

        output_path = self.output_path.get().strip()

        self._set_busy(True)
        self.progress["value"] = 0
        self.result_label.config(text="")

        quality = int(round(self.quality.get()))
        max_dimension = int(round(self.max_dimension.get()))

        threading.Thread(
            target=self._run_compression,
            args=(input_path, output_path, quality, max_dimension),
            daemon=True,
        ).start()

    def _set_progress(self, pct):
        self.after(0, lambda: self.progress.configure(value=pct))

    def _show_success(self, text):
        self.progress["value"] = 100
        self.status_label.config(text="Complete")
        self.result_label.config(
            text=text, foreground=self.GOLD, font=("Segoe UI", 9, "bold")
        )
        self._set_busy(False)

    def _show_error(self, error):
        self.status_label.config(text="Failed")
        self.result_label.config(
            text=str(error), foreground=self.ERROR_COLOR, font=("Segoe UI", 9, "bold")
        )
        self._set_busy(False)
        messagebox.showerror("Execution Error", str(error))

    def _run_compression(self, input_path, output_path, quality, max_dimension):
        try:
            original_size = os.path.getsize(input_path)

            compress_pdf(
                input_path,
                output_path,
                quality=quality,
                max_dimension=max_dimension,
                progress_callback=self._set_progress,
            )

            compressed_size = os.path.getsize(output_path)
            reduction = (
                (1 - compressed_size / original_size) * 100
                if original_size
                else 0
            )

            result = (
                f"File compressed successfully.\n"
                f"Size reduced from {original_size / 1024:.0f} KB to "
                f"{compressed_size / 1024:.0f} KB ({reduction:.0f}% saved).\n"
                f"Saved to: {output_path}"
            )

            self.after(0, lambda: self._show_success(result))

        except Exception as e:
            self.after(0, lambda err=e: self._show_error(err))


if __name__ == "__main__":
    app = PDFCompressorApp()
    app.mainloop()