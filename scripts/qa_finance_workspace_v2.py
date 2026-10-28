#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = 'http://127.0.0.1:4173/'
OUT = Path('artifacts/qa-finance-v2')
OUT.mkdir(parents=True, exist_ok=True)
VIEWPORTS = [
    ('mobile-390', 390, 844),
    ('tablet-768', 768, 1024),
    ('laptop-1024', 1024, 768),
    ('desktop-1440', 1440, 900),
    ('macbook-1512', 1512, 982),
]


def dispatch(locator):
    locator.evaluate("e=>e.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}))")


def wait_shell(page):
    page.locator('.finance-workspace-shell').wait_for(timeout=30_000)


def assert_geometry(page, label):
    page.wait_for_timeout(300)
    metrics = page.evaluate("""() => {
      const controls = [...document.querySelectorAll('button,input,select,textarea,a')]
        .filter(e => e.offsetParent !== null).map(e => { const r=e.getBoundingClientRect(); let p=e.parentElement, scrollable=false; while(p){const s=getComputedStyle(p); if(['auto','scroll'].includes(s.overflowX)){scrollable=true;break} p=p.parentElement} return {label:e.getAttribute('aria-label')||e.textContent?.trim()?.slice(0,40),x:r.x,y:r.y,w:r.width,h:r.height,scrollable,sidebar:Boolean(e.closest('aside'))} })
      return {inner:innerWidth, scroll:document.documentElement.scrollWidth, controls}
    }""")
    assert metrics['scroll'] <= metrics['inner'] + 1, f"{label}: horizontal overflow inner={metrics['inner']} scroll={metrics['scroll']}"
    visible = [c for c in metrics['controls'] if c['y'] < page.viewport_size['height'] and c['y'] + c['h'] > 0 and c['x'] < metrics['inner'] and c['x'] + c['w'] > 0]
    undersized = [c for c in visible if c['h'] < 35 and c['w'] < 35]
    assert not undersized, f'{label}: undersized visible controls {undersized[:8]}'
    clipped = [c for c in visible if not c['sidebar'] and not c['scrollable'] and c['x'] + c['w'] > 1 and c['x'] < metrics['inner'] - 1 and (c['x'] < -1 or c['x'] + c['w'] > metrics['inner'] + 1)]
    assert not clipped, f'{label}: clipped visible controls {clipped[:8]}'
    return metrics


def goto_page(page, name):
    dispatch(page.get_by_role('navigation', name='Menu utama').get_by_role('button', name=re.compile(f'^{re.escape(name)}')))
    page.wait_for_timeout(100)


def matrix(browser):
    results=[]
    for name,width,height in VIEWPORTS:
        page=browser.new_page(viewport={'width':width,'height':height}, locale='id-ID')
        errors=[]
        page.on('console', lambda msg: errors.append(f'console:{msg.type}:{msg.text}') if msg.type=='error' else None)
        page.on('pageerror', lambda err: errors.append(f'page:{err}'))
        page.goto(URL, wait_until='domcontentloaded', timeout=60_000)
        wait_shell(page)
        for nav in ['Ringkasan','Arus Kas','Dompet','Transaksi','Proyek','Operasional Kantor','Hutang Internal','Laporan']:
            if width <= 900:
                dispatch(page.get_by_role('button', name='Buka navigasi'))
                page.wait_for_timeout(50)
            goto_page(page,nav)
            assert_geometry(page,f'{name}:{nav}')
        page.screenshot(path=str(OUT/f'{name}-reports.png'))
        assert not errors, f'{name}: {errors}'
        results.append({'viewport':name,'pages':8,'errors':0})
        page.close()
    return results


def journeys(browser):
    context=browser.new_context(viewport={'width':1440,'height':900},accept_downloads=True,locale='id-ID')
    page=context.new_page(); errors=[]
    page.on('console', lambda msg: errors.append(f'console:{msg.type}:{msg.text}') if msg.type=='error' else None)
    page.on('pageerror', lambda err: errors.append(f'page:{err}'))
    page.goto(URL,wait_until='domcontentloaded',timeout=60_000); wait_shell(page)

    goto_page(page,'Proyek')
    assert page.get_by_role('button',name='2024, 120 selesai dari 120 proyek').count()==1
    assert page.get_by_role('button',name='2025, 40 selesai dari 74 proyek').count()==1
    assert page.get_by_role('button',name='2026, 7 selesai dari 28 proyek').count()==1
    dispatch(page.get_by_role('button',name='Tahun sebelumnya')); page.wait_for_timeout(100)
    assert 'Tingkat selesai · 40/74' in page.locator('.project-year-stats').inner_text()
    dispatch(page.get_by_role('button',name='Tahun berikutnya')); page.wait_for_timeout(100)

    dispatch(page.get_by_role('button',name='Tambah proyek').first)
    dialog=page.get_by_role('dialog')
    dialog.get_by_label('Nama proyek *').fill('QA Project CRUD')
    dialog.get_by_label('Klien').fill('QA Client')
    dialog.get_by_label('Nilai kontrak').fill('12500000')
    dispatch(dialog.get_by_role('button',name='Tambah proyek'))
    page.wait_for_timeout(150)
    assert page.get_by_text('QA Project CRUD',exact=True).count()>=1
    stored=json.loads(page.evaluate("localStorage.getItem('hollawall-finance-demo-v2')"))
    project=next(row for row in stored['projects'] if row['name']=='QA Project CRUD')
    assert project['wallet']=='CV HB' and stored['audit'][-1]['action']=='create'

    dispatch(page.get_by_role('button',name='Ubah QA Project CRUD'))
    dialog=page.get_by_role('dialog'); dialog.get_by_label('Perusahaan *').select_option(label='Texturin Bali')
    dialog.get_by_label('Nama proyek *').fill('QA Project CRUD Updated')
    dispatch(dialog.get_by_role('button',name='Simpan perubahan')); page.wait_for_timeout(150)
    stored=json.loads(page.evaluate("localStorage.getItem('hollawall-finance-demo-v2')"))
    project=next(row for row in stored['projects'] if row['name']=='QA Project CRUD Updated')
    assert project['wallet']=='TX Bali' and stored['audit'][-1]['action']=='update'

    page.once('dialog',lambda prompt: prompt.accept())
    dispatch(page.get_by_role('button',name='Hapus QA Project CRUD Updated')); page.wait_for_timeout(150)
    stored=json.loads(page.evaluate("localStorage.getItem('hollawall-finance-demo-v2')"))
    assert all(row['name']!='QA Project CRUD Updated' for row in stored['projects']) and stored['audit'][-1]['action']=='delete'

    goto_page(page,'Operasional Kantor')
    dispatch(page.get_by_role('button',name='Biaya kantor').first)
    dialog=page.get_by_role('dialog'); dialog.get_by_label('Dompet *').select_option('TX Bali'); dialog.get_by_label('Jumlah *').fill('500000'); dialog.get_by_label('Keterangan *').fill('QA listrik 500 ribu')
    dispatch(dialog.get_by_role('button',name='Simpan transaksi')); page.wait_for_timeout(150)
    assert page.get_by_text('QA listrik 500 ribu',exact=True).count()==1
    stored=json.loads(page.evaluate("localStorage.getItem('hollawall-finance-demo-v2')"))
    office=next(row for row in stored['transactions'] if row['notes']=='QA listrik 500 ribu')
    assert office['scope']=='office' and office['wallet']=='TX Bali' and office['project_id'] is None and office['amount']==500000

    goto_page(page,'Hutang Internal')
    dispatch(page.get_by_role('button',name='Tambah hutang').first)
    dialog=page.get_by_role('dialog'); dialog.get_by_label('Jumlah hutang *').fill('7000000'); dialog.get_by_label('Keterangan *').fill('QA antar dompet')
    dispatch(dialog.get_by_role('button',name='Simpan hutang')); page.wait_for_timeout(150)
    stored=json.loads(page.evaluate("localStorage.getItem('hollawall-finance-demo-v2')"))
    debt=next(row for row in stored['debts'] if row['notes']=='QA antar dompet')
    assert debt['borrower']!=debt['lender'] and debt['amount']==7000000

    page.reload(wait_until='domcontentloaded',timeout=60_000); wait_shell(page)
    stored2=json.loads(page.evaluate("localStorage.getItem('hollawall-finance-demo-v2')"))
    assert any(row['notes']=='QA listrik 500 ribu' for row in stored2['transactions'])
    assert any(row['notes']=='QA antar dompet' for row in stored2['debts'])

    goto_page(page,'Laporan')
    page.get_by_label('Aktivitas').select_option('office'); page.get_by_label('Dompet').select_option('TX Bali'); page.wait_for_timeout(100)
    chips=page.locator('.preview-scope span').all_inner_texts(); assert len(chips)==7 and 'Operasional Kantor' in chips and 'TX Bali' in chips
    with page.expect_download(timeout=30_000) as info:
        dispatch(page.get_by_role('button',name='Ekspor PDF'))
    download=info.value; pdf=OUT/'hollawall-report.pdf'; download.save_as(pdf)
    data=pdf.read_bytes(); assert data[:5]==b'%PDF-' and len(data)>10_000
    page.screenshot(path=str(OUT/'journey-report.png'))
    assert not errors, errors
    context.close()
    return {'project_crud':True,'office_wallet':True,'debt':True,'persistence':True,'report_pdf_bytes':len(data),'errors':0}


def main():
    with sync_playwright() as p:
        webkit=p.webkit.launch(headless=True)
        result={'webkit_matrix':matrix(webkit),'journeys':journeys(webkit)}
        webkit.close()
        chromium=p.chromium.launch(headless=True,executable_path='/snap/bin/chromium',args=['--no-sandbox'])
        result['chromium_matrix']=matrix(chromium)
        chromium.close()
    (OUT/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))

if __name__=='__main__': main()
