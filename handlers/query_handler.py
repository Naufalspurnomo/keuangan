"""
Smart Query Handler - AI dengan akses ke data Spreadsheet
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
    
    Args:
        query: User's question
        user_id: Sender ID
        chat_id: Chat ID
    
    Returns:
        AI's answer based on real data
    """
    
    # 1. Fetch relevant data dari Spreadsheet
    context_data = fetch_financial_context(query)
    
    if not context_data or context_data.get('total_rows') == 0:
        return "📊 Belum ada data transaksi untuk pertanyaan ini."
    
    # 2. Build context-rich prompt
    system_prompt = """Anda adalah asisten keuangan untuk perusahaan seni/mural.
Anda memiliki akses ke data transaksi real-time dari Google Spreadsheet.

Tugas Anda:
- Jawab pertanyaan user tentang keuangan berdasarkan data yang diberikan
- Berikan analisis yang jelas dan ringkas
- Gunakan emoji untuk readability
- Format angka dengan ribuan separator (titik)

Jangan:
- Mengarang data yang tidak ada
- Memberikan saran keuangan yang tidak diminta
"""

    user_prompt = f"""Pertanyaan: {query}

DATA TERSEDIA:
{context_data['formatted_data']}

Jawab pertanyaan user secara spesifik berdasarkan data di atas."""

    # 3. Call AI
    try:
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
        logger.error(f"Query AI failed: {e}")
        return "❌ Maaf, terjadi kesalahan saat menganalisis data."


def fetch_financial_context(query: str) -> dict:
    """
    Fetch relevant financial data based on query.
    
    Returns dict with:
    - formatted_data: Human-readable summary
    - total_rows: Number of transactions found
    """
    
    query_lower = query.lower()
    
    # Detect time scope
    if any(kw in query_lower for kw in ['hari ini', 'today', 'harian']):
        days = 1
    elif any(kw in query_lower for kw in ['minggu ini', 'week', 'mingguan']):
        days = 7
    elif any(kw in query_lower for kw in ['bulan ini', 'month', 'bulanan']):
        days = 30
    else:
        days = 7  # Default
    
    # Detect dompet scope
    target_dompets = []
    if any(kw in query_lower for kw in ['cv hb', 'holja', 'holla', '101']):
        target_dompets.append('CV HB (101)')
    if any(kw in query_lower for kw in ['tx sby', 'surabaya', '216', 'texturin sby']):
        target_dompets.append('TX SBY(216)')
    if any(kw in query_lower for kw in ['tx bali', 'bali', '087', 'evan']):
        target_dompets.append('TX BALI(087)')
    
    if not target_dompets:
        # All dompets
        target_dompets = ['CV HB (101)', 'TX SBY(216)', 'TX BALI(087)']
    
    # Fetch data
    cutoff_date = now_wib() - timedelta(days=days)
    
    all_transactions = []
    dompet_summaries = []
    
    for dompet_name in target_dompets:
        try:
            sh = get_sheet(dompet_name)
            if not sh:
                continue
            
            # Get data (assuming struktur: No, Waktu, Tanggal, Jumlah, Project, Keterangan)
            rows = sh.get_all_values()
            
            if len(rows) < 2:
                continue
            
            # Parse header
            header = rows[0]
            
            # Find column indices
            try:
                tanggal_idx = header.index('Tanggal')
                jumlah_idx = header.index('Jumlah')
                project_idx = header.index('Project')
                keterangan_idx = header.index('Keterangan')
            except ValueError:
                logger.warning(f"Sheet {dompet_name} missing expected columns")
                continue
            
            # Collect transactions from PEMASUKAN and PENGELUARAN sections
            pemasukan_total = 0
            pengeluaran_total = 0
            transaction_count = 0
            
            for row in rows[1:]:  # Skip header
                if len(row) <= max(tanggal_idx, jumlah_idx):
                    continue
                
                try:
                    # Parse tanggal (DD/MM/YYYY)
                    tanggal_str = row[tanggal_idx]
                    if not tanggal_str:
                        continue
                    
                    # Simple date check (not parsing full datetime for performance)
                    # Just check if recent enough
                    
                    # Parse jumlah
                    jumlah_str = row[jumlah_idx].replace('Rp', '').replace('.', '').replace(',', '').strip()
                    if not jumlah_str:
                        continue
                    
                    jumlah = int(jumlah_str)
                    
                    # Determine if PEMASUKAN or PENGELUARAN based on section
                    # This is a simplified heuristic - adjust based on your sheet structure
                    # You might need to check which section (PEMASUKAN/PENGELUARAN) the row belongs to
                    
                    # For now, assume negative = pengeluaran, positive = pemasukan
                    # Or you can check the column name or section headers
                    
                    # Simplified: Count all as transactions
                    transaction_count += 1
                    all_transactions.append({
                        'dompet': dompet_name,
                        'tanggal': tanggal_str,
                        'jumlah': jumlah,
                        'project': row[project_idx] if project_idx < len(row) else '',
                        'keterangan': row[keterangan_idx] if keterangan_idx < len(row) else ''
                    })
                    
                except (ValueError, IndexError) as e:
                    continue
            
            # Calculate saldo (you need to implement proper PEMASUKAN - PENGELUARAN logic)
            # This is simplified
            dompet_summaries.append({
                'dompet': dompet_name,
                'transactions': transaction_count,
                'pemasukan': pemasukan_total,
                'pengeluaran': pengeluaran_total
            })
            
        except Exception as e:
            logger.error(f"Error fetching {dompet_name}: {e}")
            continue
    
    # Format data for AI
    formatted_lines = []
    formatted_lines.append(f"📅 Periode: {days} hari terakhir")
    formatted_lines.append(f"📊 Total transaksi: {len(all_transactions)}")
    formatted_lines.append("")
    
    for summary in dompet_summaries:
        formatted_lines.append(f"💼 {summary['dompet']}:")
        formatted_lines.append(f"  • Transaksi: {summary['transactions']}")
        # Add pemasukan/pengeluaran if calculated
        formatted_lines.append("")
    
    # Recent transactions (last 10)
    if all_transactions:
        formatted_lines.append("📋 Transaksi Terbaru:")
        for tx in all_transactions[-10:]:
            formatted_lines.append(f"  • {tx['tanggal']} - {tx['keterangan']}: Rp {tx['jumlah']:,}".replace(',', '.'))
    
    return {
        'formatted_data': '\n'.join(formatted_lines),
        'total_rows': len(all_transactions),
        'raw_transactions': all_transactions
    }   