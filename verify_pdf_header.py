
import os
import sys

# Ensure current dir is in path
sys.path.append(os.getcwd())

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from pdf_report import _draw_header_monthly, UI, THEME, register_fonts

def main():
    filename = "final_header_test.pdf"
    c = canvas.Canvas(filename, pagesize=A4)
    w, h = A4
    
    # Setup UI
    fonts = register_fonts()
    ui = UI(fonts=fonts)
    
    # Mock Context
    ctx = {
        "period_label": "JAN 26",
        "generated_on": "03 Feb 26"
    }
    
    # Run the function
    print("Generating header test...")
    try:
        # Try to find a logo if possible, or pass None
        logo_path = os.getenv("HOLLAWALL_LOGO_PATH", "assets/logo.png")
        if not os.path.exists(logo_path):
             logo_path = None
             
        _draw_header_monthly(c, ui, ctx, w, h, logo_path=logo_path)
    except Exception as e:
        print(f"Error drawing header: {e}")
        import traceback
        traceback.print_exc()
        return

    c.showPage()
    c.save()
    print(f"{filename} generated successfully.")

if __name__ == "__main__":
    main()
