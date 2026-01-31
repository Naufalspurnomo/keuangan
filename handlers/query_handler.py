"""
Smart Query Handler - AI dengan akses ke data Spreadsheet
Version: Simplified & Robust
"""

import logging
from datetime import datetime, timedelta
from sheets_helper import get_sheet
from ai_helper import groq_client
from security import now_wib

logger = logging.getLogger(__name__)


def handle_query_command(query: str, user_id: str, chat_id: str) -> str:
    """
    Handle /tanya command dengan inject data dari Spreadsheet.
    """
    
    try:
        # 1. Fetch data
        context_data = fetch_financial_summary()
        
        if not context_data:
            return "📊 Belum ada data transaksi yang bisa dianalisis."
        
        # 2. Build AI prompt
        system_prompt = """Anda adalah asisten keuangan untuk perusahaan seni/mural.
Jawab pertanyaan user tentang keuangan berdasarkan data yang diberikan.

Gunakan:
- Emoji untuk readability
- Format angka dengan titik sebagai separator ribuan
- Bahasa yang friendly tapi profesional

Jangan mengarang data yang tidak tersedia."""

        user_prompt = f"""Pertanyaan: {query}

DATA KEUANGAN:
{context_data}

Jawab pertanyaan berdasarkan data di atas."""

        # 3. Call AI
        response = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=512
        )
        
        answer = response.choices[0].message.content
        return answer.strip()
        
    except Exception as e:
        logger.error(f"Query handler error: {e}", exc_info=True)
        raise  # Re-raise untuk di-catch di main.py


def fetch_financial_summary() -> str:
    """
    Fetch simplified financial summary dari semua dompet.
    Returns formatted string untuk AI context.
    """
    
    dompet_names = ['CV HB (101)', 'TX SBY(216)', 'TX BALI(087)']
    
    summary_lines = []
    summary_lines.append("💼 RINGKASAN KEUANGAN\n")
    
    total_all_pemasukan = 0
    total_all_pengeluaran = 0
    
    for dompet_name in dompet_names:
        try:
            sh = get_sheet(dompet_name)
            if not sh:
                summary_lines.append(f"❌ {dompet_name}: Data tidak tersedia\n")
                continue
            
            # Strategy: Cari section PEMASUKAN dan PENGELUARAN
            # Lalu sum semua angka di kolom Jumlah
            
            all_values = sh.get_all_values()
            
            pemasukan_total = 0
            pengeluaran_total = 0
            in_pemasukan_section = False
            in_pengeluaran_section = False
            
            for row in all_values:
                # Detect section headers
                if len(row) > 0:
                    first_cell = str(row[0]).upper()
                    
                    if 'PEMASUKAN' in first_cell:
                        in_pemasukan_section = True
                        in_pengeluaran_section = False
                        continue
                    
                    if 'PENGELUARAN' in first_cell:
                        in_pengeluaran_section = True
                        in_pemasukan_section = False
                        continue
                
                # Parse jumlah from row
                # Usually column 3 or 4 (index 2 or 3)
                for i, cell in enumerate(row):
                    if i < 2:  # Skip No and Waktu columns
                        continue
                    
                    # Try to parse as number
                    cell_str = str(cell).replace('Rp', '').replace('.', '').replace(',', '').replace(' ', '').strip()
                    
                    if cell_str.isdigit():
                        amount = int(cell_str)
                        
                        if amount > 0:  # Valid amount
                            if in_pemasukan_section:
                                pemasukan_total += amount
                            elif in_pengeluaran_section:
                                pengeluaran_total += amount
                        
                        break  # Only parse first valid number in row
            
            saldo = pemasukan_total - pengeluaran_total
            
            summary_lines.append(f"📊 {dompet_name}:")
            summary_lines.append(f"  💰 Pemasukan: Rp {pemasukan_total:,}".replace(',', '.'))
            summary_lines.append(f"  💸 Pengeluaran: Rp {pengeluaran_total:,}".replace(',', '.'))
            summary_lines.append(f"  💵 Saldo: Rp {saldo:,}".replace(',', '.'))
            summary_lines.append("")
            
            total_all_pemasukan += pemasukan_total
            total_all_pengeluaran += pengeluaran_total
            
        except Exception as e:
            logger.error(f"Error processing {dompet_name}: {e}")
            summary_lines.append(f"⚠️ {dompet_name}: Error membaca data\n")
    
    # Grand total
    grand_saldo = total_all_pemasukan - total_all_pengeluaran
    summary_lines.append("=" * 40)
    summary_lines.append("📈 TOTAL KESELURUHAN:")
    summary_lines.append(f"  💰 Total Pemasukan: Rp {total_all_pemasukan:,}".replace(',', '.'))
    summary_lines.append(f"  💸 Total Pengeluaran: Rp {total_all_pengeluaran:,}".replace(',', '.'))
    summary_lines.append(f"  💵 Saldo Akhir: Rp {grand_saldo:,}".replace(',', '.'))
    
    return '\n'.join(summary_lines)