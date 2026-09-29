"""Browser verification for Logs / Alerts navigation and its shared viewer.

Real endpoints are checked first. Empty and unavailable responses are then
simulated only inside the browser so no host logs or project data are changed.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:5173')
    parser.add_argument('--production', action='store_true')
    args = parser.parse_args()
    command = [str(ROOT / 'data/browser-tools/node_modules/.bin/agent-browser'),
               '--session', 'monitoring-' + uuid4().hex[:8]]
    if os.getenv('DASHBOARD_BROWSER_ARGS'):
        command += ['--args', os.environ['DASHBOARD_BROWSER_ARGS']]

    def browser(*parts):
        result = subprocess.run(command + list(parts), capture_output=True, text=True, timeout=45)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        return result.stdout

    def evaluate(code):
        return browser('eval', '(async () => {' + code + '})()')

    def evaluate_json(code):
        output = browser('--json', 'eval', '(async () => {' + code + '})()')
        return json.loads(output)['data']['result']

    def wait(code):
        browser('wait', '--fn', code)

    def click(name, role='button'):
        browser('find', 'role', role, 'click', '--name', name, '--exact')

    opened = False
    try:
        browser('open', args.url + '/#/overview')
        opened = True
        wait("document.body.innerText.includes('Your server, at a glance.')")
        browser('snapshot', '-i')
        evaluate("window.__errors=[]; window.addEventListener('error',e=>window.__errors.push(e.message)); window.addEventListener('unhandledrejection',e=>window.__errors.push(String(e.reason))); document.addEventListener('securitypolicyviolation',e=>window.__errors.push(e.violatedDirective))")
        if args.production:
            evaluate("const r=await fetch('/'); const csp=r.headers.get('content-security-policy')||''; if(!csp.includes(\"script-src 'self'\") || csp.includes('unsafe-inline') || csp.includes('unsafe-eval')) throw Error('Strict production CSP missing')")

        parent = "document.querySelector('button[aria-controls=logs-alerts-menu]')"
        evaluate(f"if(!{parent} || {parent}.getAttribute('aria-expanded')!=='false') throw Error('Collapsed Logs / Alerts parent missing')")
        click('Logs / Alerts')
        wait("!!document.querySelector('#logs-alerts-menu')")
        evaluate("const labels=[...document.querySelectorAll('#logs-alerts-menu a')].map(e=>e.textContent.trim()); if(JSON.stringify(labels)!==JSON.stringify(['General','Server','Samba'])) throw Error('Nested log navigation is incorrect')")

        click('General', 'link')
        wait("location.hash==='#/logs/general' && !!document.querySelector('.provider-logs-table')")
        wait("![...document.querySelectorAll('button')].some(e=>e.textContent.includes('Refreshing…'))")
        evaluate("const active=document.querySelector('#logs-alerts-menu a[aria-current=page]'); if(active?.textContent.trim()!=='General') throw Error('General active state missing')")

        real = evaluate_json("""
          const paths=[
            ['/api/logs/general?limit=10','general'],
            ['/api/logs/server?category=all&limit=10','server'],
            ['/api/logs/server?category=kernel&severity=warning&limit=10','server'],
            ['/api/logs/server?category=authentication&limit=10','server'],
            ['/api/logs/server?category=current_boot&limit=10','server'],
            ['/api/logs/server?category=warnings&limit=10','server'],
            ['/api/logs/server?category=errors&limit=10','server'],
            ['/api/logs/general?category=alerts&limit=200','general'],
            ['/api/logs/samba?category=all&limit=10','samba'],
            ['/api/logs/samba?limit=10','samba']
          ];
          const counts={};
          for(const [path,provider] of paths){
            const response=await fetch(path);
            if(!response.ok) throw Error(path+' returned '+response.status);
            const body=await response.json();
            if(body.provider!==provider || !Array.isArray(body.entries) || body.entries.length>body.limit) throw Error('Bad bounded response: '+path);
            for(const row of body.entries){
              if(!row.timestamp || !['info','warning','error'].includes(row.severity) || !row.source || !row.message) throw Error('Bad log row: '+path);
            }
            counts[path]=body.entries.length;
          }
          return counts;
        """)

        evaluate("window.__realFetch=window.fetch; window.__logRequests=[]; window.fetch=(input,options)=>{const value=String(input); if(value.startsWith('/api/logs/')) window.__logRequests.push(value); return window.__realFetch(input,options)}")
        click('↻ Refresh logs')
        wait("window.__logRequests.some(value=>value.startsWith('/api/logs/general')) && !document.body.innerText.includes('Refreshing…')")
        click('Alert history')
        wait("window.__logRequests.some(value=>value.includes('category=alerts'))")
        browser('select', '#general-log-severity', 'warning')
        wait("window.__logRequests.some(value=>value.includes('category=alerts')&&value.includes('severity=warning'))")
        browser('select', '#general-log-limit', '25')
        wait("window.__logRequests.some(value=>value.includes('limit=25'))")
        browser('fill', '.log-viewer-search input', 'samba')
        click('Apply search')
        wait("window.__logRequests.some(value=>value.includes('search=samba'))")
        wait("!document.body.innerText.includes('Loading the selected view')")
        evaluate("if([...document.querySelectorAll('.provider-logs-table tbody tr')].some(e=>!e.textContent.toLowerCase().includes('samba') || !e.querySelector('.severity-warning'))) throw Error('Search/severity rendered incorrect rows')")
        click('Clear filters')
        wait("window.__logRequests.at(-1).includes('category=timeline') && !document.body.innerText.includes('Loading the selected view')")
        evaluate("if(document.querySelector('.log-viewer-search input').value || document.querySelector('#general-log-severity').value!=='all' || document.querySelector('#general-log-limit').value!=='50') throw Error('Clear did not reset all controls')")
        # Submitting an unchanged query or active category must not leave Refresh disabled.
        click('Apply search')
        wait("!document.body.innerText.includes('Loading the selected view')")
        click('Timeline')
        wait("!document.body.innerText.includes('Loading the selected view')")

        click('Server', 'link')
        wait("location.hash==='#/logs/server' && document.body.innerText.includes('Server logs')")
        click('Current boot')
        wait("window.__logRequests.some(value=>value.includes('category=current_boot')) && !document.body.innerText.includes('Loading the selected view')")
        evaluate("if(!document.body.innerText.includes('not just startup events')) throw Error('Current boot explanation missing')")
        click('Kernel')
        wait("window.__logRequests.some(value=>value.includes('/api/logs/server')&&value.includes('category=kernel'))")
        browser('reload')
        wait("location.hash==='#/logs/server' && document.body.innerText.includes('Server logs')")
        evaluate("window.__errors=[]; window.addEventListener('error',e=>window.__errors.push(e.message)); window.addEventListener('unhandledrejection',e=>window.__errors.push(String(e.reason)))")
        click('Kernel')
        browser('select', '#server-log-severity', 'warning')
        wait("!document.body.innerText.includes('Loading the selected view')")
        evaluate("if([...document.querySelectorAll('.provider-logs-table tbody tr')].some(e=>!e.querySelector('.severity-warning'))) throw Error('Kernel severity filter failed')")
        browser('screenshot', str(ROOT / 'data/logs-review-kernel.png'))
        click('Clear filters')
        wait("!document.body.innerText.includes('Loading the selected view')")
        evaluate("if(document.querySelector('.log-category-filters button[aria-pressed=true]').textContent!=='All') throw Error('Server reset category incorrect')")

        click('Samba', 'link')
        wait("location.hash==='#/logs/samba' && document.body.innerText.includes('Samba logs')")
        browser('back')
        wait("location.hash==='#/logs/server' && document.querySelector('#logs-alerts-menu a[aria-current=page]')?.textContent==='Server'")
        browser('forward')
        wait("location.hash==='#/logs/samba' && document.querySelector('#logs-alerts-menu a[aria-current=page]')?.textContent==='Samba'")
        wait("![...document.querySelectorAll('button')].some(e=>e.textContent.includes('Refreshing…'))")
        evaluate("if(document.querySelector('.log-category-filters button[aria-pressed=true]').textContent!=='Operational') throw Error('Samba default incorrect'); if([...document.querySelectorAll('.provider-logs-table tbody tr')].some(e=>e.textContent.includes('pam_unix(samba:session): session opened'))) throw Error('Routine Samba rows in default')")
        click('All')
        wait("!document.body.innerText.includes('Loading the selected view')")
        browser('fill', '.log-viewer-search input', 'no-match-browser-review-837162')
        click('Apply search')
        wait("document.body.innerText.includes('No entries match the current search')")
        click('Clear filters')
        wait("!document.body.innerText.includes('Loading the selected view')")
        evaluate("if(document.querySelector('.log-category-filters button[aria-pressed=true]').textContent!=='Operational') throw Error('Samba reset incorrect')")
        evaluate("window.__hostFetch=window.fetch; window.fetch=(input,options)=>String(input).startsWith('/api/logs/samba')?Promise.resolve(new Response(JSON.stringify({provider:'samba',generated_at:new Date().toISOString(),entries:[],returned:0,limit:50,sources:['Browser-only empty-state fixture'],detail:'No matching real records.'}),{status:200,headers:{'Content-Type':'application/json'}})):window.__hostFetch(input,options)")
        click('↻ Refresh logs')
        wait("document.body.innerText.includes('No real events were found')")
        evaluate("window.fetch=(input,options)=>String(input).startsWith('/api/logs/samba')?Promise.resolve(new Response(JSON.stringify({detail:'Browser-only unavailable-source fixture'}),{status:503,headers:{'Content-Type':'application/json'}})):window.__hostFetch(input,options)")
        click('↻ Refresh logs')
        wait("document.body.innerText.includes('Browser-only unavailable-source fixture') && document.body.innerText.includes('may be stale')")
        evaluate("window.fetch=(input,options)=>String(input).startsWith('/api/logs/samba')?Promise.reject(new TypeError('Browser-only backend unavailable')):window.__hostFetch(input,options)")
        click('↻ Refresh logs')
        wait("document.body.innerText.includes('Browser-only backend unavailable')")
        evaluate("window.fetch=window.__hostFetch")
        click('Clear filters')
        wait("!document.body.innerText.includes('Loading the selected view') && !document.body.innerText.includes('Browser-only backend unavailable')")

        click('Logs / Alerts')
        wait("!document.querySelector('#logs-alerts-menu')")
        click('Logs / Alerts')
        wait("document.querySelector('#logs-alerts-menu a[aria-current=page]')?.textContent.trim()==='Samba'")
        click('Services', 'link')
        wait("location.hash==='#/services' && document.body.innerText.includes('One home for your services.')")
        click('Project', 'link')
        wait("location.hash==='#/project' && !!document.querySelector('#new-task')")
        click('Overview', 'link')
        wait("location.hash==='#/overview' && document.body.innerText.includes('Your server, at a glance.')")

        evaluate("const parent=document.querySelector('button[aria-controls=logs-alerts-menu]'); if(parent.getAttribute('aria-expanded')==='false') parent.click()")
        wait("!!document.querySelector('#logs-alerts-menu')")
        click('General', 'link')
        wait("location.hash==='#/logs/general' && document.body.innerText.includes('General events')")
        click('Alert history')
        wait("!document.body.innerText.includes('Loading the selected view')")
        evaluate("if(document.querySelector('.provider-logs-table').textContent.includes('Startup: Service check: unknown')) throw Error('Startup incident remains in alert history')")
        click('Clear filters')
        wait("!document.body.innerText.includes('Loading the selected view')")
        evaluate("window.__csv=''; const original=URL.createObjectURL.bind(URL); URL.createObjectURL=blob=>{blob.text().then(text=>window.__csv=text);return original(blob)}")
        click('Download CSV')
        wait("window.__csv.includes('Date,Name,Details')")
        click('Switch to light mode')
        wait("!!document.querySelector('[aria-label=\"Switch to dark mode\"]')")
        browser('set', 'viewport', '390', '844')
        evaluate("if(document.documentElement.scrollWidth>innerWidth) throw Error('Mobile page overflow')")
        evaluate("if(getComputedStyle(document.querySelector('.desktop-log-table')).display!=='none') throw Error('Desktop log table visible on mobile'); const cards=[...document.querySelectorAll('.mobile-log-cards>li')]; if(!cards.length || cards.some(e=>!e.querySelector('time')||!e.querySelector('.severity-badge')||!e.querySelector('.log-card-source')||!e.querySelector('p')||e.scrollWidth>e.clientWidth)) throw Error('Unreadable mobile log card')")
        browser('screenshot', str(ROOT / 'data/logs-alerts-mobile.png'))
        click('Overview', 'link')
        wait("!!document.querySelector('.overview-attention')")
        evaluate("const r=document.querySelector('.overview-attention').getBoundingClientRect(); if(r.top<0 || r.bottom>innerHeight) throw Error('Attention summary outside first mobile viewport')")
        browser('screenshot', str(ROOT / 'data/overview-mobile.png'))
        click('General', 'link')
        wait("!!document.querySelector('.mobile-log-cards>li')")
        click('Switch to dark mode')
        browser('set', 'viewport', '1280', '900')
        evaluate("if(getComputedStyle(document.querySelector('.mobile-log-cards')).display!=='none' || getComputedStyle(document.querySelector('.desktop-log-table')).display==='none') throw Error('Desktop accessible table missing')")
        browser('screenshot', str(ROOT / 'data/logs-alerts-desktop.png'))
        evaluate("if((window.__errors||[]).length) throw Error(JSON.stringify(window.__errors))")
        errors = browser('errors').strip()
        if errors:
            raise RuntimeError(errors)
    except Exception:
        if opened:
            browser('screenshot', str(ROOT / 'data/logs-alerts-failed.png'))
            print(browser('snapshot', '-i'), flush=True)
        raise
    finally:
        if opened:
            browser('close')
    print('PASS: nested Logs / Alerts navigation, deep links/reload, real bounded APIs ' +
          json.dumps(real, sort_keys=True) +
          ', back/forward, Current boot, clear filters, repeat queries, refresh/category/severity/search/limit controls, empty/error/stale states, CSV, existing navigation, themes and mobile')


if __name__ == '__main__':
    main()
