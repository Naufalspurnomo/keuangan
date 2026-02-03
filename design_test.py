
import os
import datetime
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from dataclasses import dataclass
from typing import Dict, Optional, List

# --- MOCKS ---
@dataclass
class UI:
    fonts: Dict[str, str]
    margin: float = 40
    radius: float = 18
    shadow_dx: float = 0
    shadow_dy: float = -3
    shadow_alpha: float = 0.05

THEME = {
    "bg": colors.HexColor("#F9FAFB"),
    "card": colors.white,
    "teal": colors.HexColor("#0EA5E9"),
    "white": colors.white,
    "muted2": colors.HexColor("#9CA3AF"),
    "text": colors.HexColor("#111827"),
}

# --- HELPERS ---
def _set_alpha(c: canvas.Canvas, fill: Optional[float] = None, stroke: Optional[float] = None):
    if fill is not None and hasattr(c, "setFillAlpha"):
        try: c.setFillAlpha(fill)
        except Exception: pass
    if stroke is not None and hasattr(c, "setStrokeAlpha"):
        try: c.setStrokeAlpha(stroke)
        except Exception: pass

def _draw_text(c: canvas.Canvas, font: str, size: float, color, x: float, y: float, text: str, align: str = "left"):
    c.setFont(font, size)
    c.setFillColor(color)
    if align == "right": c.drawRightString(x, y, text)
    elif align == "center": c.drawCentredString(x, y, text)
    else: c.drawString(x, y, text)

# --- DESIGNS ---

def draw_header_original(c: canvas.Canvas, ui: UI, width: float, height: float):
    # Current implementation logic
    header_h = 190
    left_w = 427
    
    # Background
    c.saveState()
    c.setFillColor(THEME["teal"])
    c.rect(0, height - header_h, left_w, header_h, fill=1, stroke=0)
    
    # Circles
    _set_alpha(c, fill=0.08)
    c.setFillColor(colors.white)
    c.circle(left_w - 60, height - 40, 36, stroke=0, fill=1)
    c.circle(left_w - 120, height - 90, 22, stroke=0, fill=1)
    c.restoreState()
    
    # Text
    _draw_text(c, ui.fonts["italic"], 10.5, THEME["white"], 140, height - 30, "Generated on 03 Feb 26")
    _draw_text(c, ui.fonts["bold"], 32, THEME["white"], 140, height - 74, "Financial")
    _draw_text(c, ui.fonts["bold"], 32, THEME["white"], 140, height - 114, "Report")
    
    # Date
    _draw_text(c, ui.fonts["bold"], 36, THEME["teal"], left_w + 18, height - 74, "JAN")
    _draw_text(c, ui.fonts["bold"], 36, THEME["teal"], left_w + 18, height - 114, "26")
    
    # Label
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.black)
    c.drawString(20, height - 210, "Original Design")

def draw_header_refined(c: canvas.Canvas, ui: UI, width: float, height: float):
    # Refined implementation
    header_h = 220 # Increased height for more breathing room
    left_w = width * 0.65 # Use percentage for better scale (approx 386 on A4 approx 595) -> 386 is < 427. 
    # Let's keep left_w similar or adjust. A4 width is 595.28 points.
    # 427 is ~71%.
    left_w = 420
    
    # Background
    c.saveState()
    c.setFillColor(THEME["teal"])
    c.rect(0, height - header_h, left_w, header_h, fill=1, stroke=0)
    
    # Decorative Circles (adjusted positions)
    _set_alpha(c, fill=0.1)
    c.setFillColor(colors.white)
    # Move circles to interact better or be more subtle
    c.circle(left_w - 50, height - 50, 60, stroke=0, fill=1)
    c.circle(left_w - 140, height - 100, 30, stroke=0, fill=1)
    c.restoreState()
    
    # Content Vars
    start_x = 40 # Standard margin
    text_x = 140     # Keeping existing indentation for logo placeholder
    
    # Generated On - Make it cleaner, maybe upper right of the blue area?
    # Or keep it consistent.
    _draw_text(c, ui.fonts["italic"], 10, THEME["white"].clone(alpha=0.9), text_x, height - 40, "Generated on 03 Feb 26")
    
    # Title - Bigger, Bolder
    # Use 48pt
    title_start_y = height - 90
    _draw_text(c, ui.fonts["bold"], 48, THEME["white"], text_x, title_start_y, "Financial")
    _draw_text(c, ui.fonts["bold"], 48, THEME["white"], text_x, title_start_y - 50, "Report") # Tighter spacing (50pt step for 48pt font)
    
    # Date Section
    # Center it vertically relative to the title block
    # Title block center y approx: title_start_y - 25
    center_y = title_start_y - 25
    
    # Month/Year
    date_x = left_w + 25
    _draw_text(c, ui.fonts["bold"], 48, THEME["teal"], date_x, title_start_y, "JAN")
    _draw_text(c, ui.fonts["regular"], 48, THEME["teal"], date_x, title_start_y - 50, "26")
    
    # Label
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.black)
    c.drawString(20, height - 240, "Refined Design")

def main():
    pdf_file = "header_design_test.pdf"
    c = canvas.Canvas(pdf_file, pagesize=A4)
    w, h = A4
    
    # Mock Font Registration (fallback)
    # In a real run, we'd load fonts. Here we use standard fonts if custom not found.
    # But since we want to see the "look", we'll just map to Helvetica for this test script if Inter not available.
    # We will try to map to Helvetica-Bold etc.
    
    ui = UI(fonts={
        "regular": "Helvetica",
        "semibold": "Helvetica-Bold",
        "bold": "Helvetica-Bold",
        "italic": "Helvetica-Oblique",
    })
    
    # Page 1: Original
    draw_header_original(c, ui, w, h)
    
    # Draw refined on same page below? No, separate page or below.
    # Let's draw below.
    
    c.translate(0, -300)
    draw_header_refined(c, ui, w, h)
    
    c.showPage()
    c.save()
    print(f"Generated {pdf_file}")

if __name__ == "__main__":
    main()
