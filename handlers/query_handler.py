"""
Smart Query Handler - AI dengan akses ke data Spreadsheet
"""

import logging
from sheets_helper import format_data_for_ai
from ai_helper import groq_client

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
    
    # 1. Fetch relevant data dari Spreadsheet via centralized helper
    # Uses 30 days default context
    formatted_context = format_data_for_ai(days=30)
    
    if "Tidak ada data transaksi" in formatted_context:
        return "📊 Belum ada data transaksi yang ditemukan."
    
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
{formatted_context}

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
        return "❌ Maaf, terjadi kesalahan saat menganalisis data AI."