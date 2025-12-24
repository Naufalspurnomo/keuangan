"""
Convert HTML documentation to PDF using weasyprint
"""
from weasyprint import HTML, CSS
import os

# Paths
html_path = os.path.join(os.path.dirname(__file__), 'documentation.html')
pdf_path = os.path.join(os.path.dirname(__file__), 'Financial_Bot_Documentation.pdf')

print("Converting HTML to PDF...")

# Convert
HTML(filename=html_path).write_pdf(pdf_path)

print(f"✅ PDF created: {pdf_path}")
