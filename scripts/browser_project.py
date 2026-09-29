"""Project regression checks through a real browser and the configured proxy.

python3 scripts/browser_project.py --url http://127.0.0.1:8088 --production --allow-project-writes
Requires agent-browser and Chromium. Uses uniquely named test records; removes only
those records in finally. Never resets a database or reorders existing entries.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:5173')
    parser.add_argument('--production', action='store_true', help='Require production CSP, routing and method restrictions')
    parser.add_argument('--allow-project-writes', action='store_true')
    parser.add_argument('--browser', default=str(ROOT / 'data/browser-tools/node_modules/.bin/agent-browser'))
    args = parser.parse_args()
    if not args.allow_project_writes:
        parser.error('Pass --allow-project-writes to create temporary test entries')
    if urlsplit(args.url).scheme not in ('http', 'https'):
        parser.error('Use an HTTP(S) dashboard URL')
    tag = 'Browser-test-' + uuid4().hex[:12]
    session = 'project-' + uuid4().hex[:8]
    command = [args.browser, '--session', session]
    if os.getenv('DASHBOARD_BROWSER_ARGS'):
        command += ['--args', os.environ['DASHBOARD_BROWSER_ARGS']]

    def browser(*parts):
        result = subprocess.run(command + list(parts), text=True, capture_output=True, timeout=45)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        return result.stdout

    def evaluate(code):
        return browser('eval', '(async () => {' + code + '})()')

    def capture_errors():
        evaluate("window.__regressionErrors = []; window.addEventListener('error', e => window.__regressionErrors.push(e.message)); window.addEventListener('unhandledrejection', e => window.__regressionErrors.push(String(e.reason))); window.__violations = []; document.addEventListener('securitypolicyviolation', e => window.__violations.push(e.violatedDirective))")

    def wait(code):
        browser('wait', '--fn', code)

    def click(name):
        wait(f"[...document.querySelectorAll('button,a')].some(e => (e.getAttribute('aria-label') === {json.dumps(name)} || e.textContent.trim().endsWith({json.dumps(name)})) && !e.disabled)")
        browser('find', 'role', 'link' if name in ('Overview', 'Services', 'Logs', 'Project') else 'button', 'click', '--name', name, '--exact')

    def contains(text):
        return f'document.body.innerText.includes({json.dumps(text)})'

    def fill(label, value):
        # Explicit IDs avoid the CLI label matcher including textarea contents.
        selector = {'Description': '#roadmap-description', 'Title': '#roadmap-title',
                    'Phase': '#roadmap-phase', 'New task': '#new-task'}.get(label)
        if selector:
            wait(f"!!document.querySelector({json.dumps(selector + ':not(:disabled)')})")
            browser('fill', selector, value)
        else:
            browser('find', 'label', label, 'fill', value, '--exact')

    def refresh():
        wait("!![...document.querySelectorAll('button')].find(b => b.textContent === '↻ Refresh' && !b.disabled)")
        click('↻ Refresh')

    opened = False
    try:
        browser('open', args.url)
        opened = True
        click('Project')
        wait("!!document.querySelector('#new-task:not(:disabled)')")
        capture_errors()
        # Real UI create/edit/complete and reload persistence.
        fill('New task', tag)
        click('Add task')
        wait(contains(tag))
        click('Edit task: ' + tag)
        fill('Task title', tag + '-edited')
        click('Save task')
        wait(contains(tag + '-edited'))
        browser('find', 'role', 'checkbox', 'check', '--name', tag + '-edited', '--exact')
        wait(f"[...document.querySelectorAll('.task-done')].some(e => e.textContent === {json.dumps(tag + '-edited')})")
        # Reload creates a new JavaScript realm, so install fresh error listeners.
        browser('reload')
        capture_errors()
        click('Project')
        wait(contains(tag + '-edited'))
        evaluate(f"if (![...document.querySelectorAll('.task-done')].some(e => e.textContent === {json.dumps(tag + '-edited')})) throw new Error('Completion did not persist')")
        browser('find', 'role', 'checkbox', 'click', '--name', tag + '-edited', '--exact')
        wait(f"![...document.querySelectorAll('.task-done')].some(e => e.textContent === {json.dumps(tag + '-edited')})")
        # Keep the dialog visible and explicitly cancel before later confirming.
        click('Remove task: ' + tag + '-edited')
        browser('dialog', 'dismiss')
        wait(contains(tag + '-edited'))
        for suffix in ('-roadmap-a', '-roadmap-b'):
            click('Add item')
            fill('Title', tag + suffix)
            fill('Description', 'Temporary browser verification')
            click('Add roadmap item')
            wait(contains(tag + suffix))
        click('Edit roadmap item: ' + tag + '-roadmap-a')
        fill('Description', 'Updated browser verification')
        click('Save changes')
        wait(contains('Updated browser verification'))
        # Real pointer DnD, confined to the two temporary entries.
        browser('set', 'viewport', '1280', '900')
        evaluate(f"document.querySelector('button[aria-label=' + JSON.stringify({json.dumps('Move roadmap item: ')} + {json.dumps(tag + '-roadmap-b')}) + ']').scrollIntoView({{block:'center',behavior:'instant'}})")
        coordinates = json.loads(browser('--json', 'eval', f"(() => {{ const point = name => {{ const r = [...document.querySelectorAll('button')].find(e => e.getAttribute('aria-label') === name).getBoundingClientRect(); return {{x:r.x+r.width/2,y:r.y+r.height/2}}; }}; return {{from:point({json.dumps('Move roadmap item: ' + tag + '-roadmap-b')}),to:point({json.dumps('Move roadmap item: ' + tag + '-roadmap-a')})}}; }})()"))['data']['result']
        origin, target = coordinates['from'], coordinates['to']
        browser('mouse', 'move', str(round(origin['x'])), str(round(origin['y'])))
        browser('mouse', 'down')
        for step in range(1, 9):
            browser('mouse', 'move', str(round(origin['x'])), str(round(origin['y'] + (target['y'] - origin['y']) * step / 8)))
        wait("!!document.querySelector('.drag-overlay')")
        evaluate("if (![...document.querySelectorAll('.roadmap-card:not(.drag-placeholder)')].some(e => e.style.transform && !e.style.transform.startsWith('translate3d(0px, 0px'))) throw new Error('Other roadmap rows did not shift during drag')")
        browser('screenshot', str(ROOT / 'data/roadmap-drag.png'))
        browser('mouse', 'up')
        wait("!document.querySelector('.drag-overlay') && !document.body.innerText.includes('Saving roadmap…')")
        evaluate(f"const rows = await (await fetch('/api/roadmap')).json(); if (rows.findIndex(r => r.title === {json.dumps(tag + '-roadmap-b')}) >= rows.findIndex(r => r.title === {json.dumps(tag + '-roadmap-a')})) throw new Error('Pointer order not persisted')")
        # Restore the two temporary rows before independently testing keyboard DnD.
        browser('focus', 'button[aria-label=' + json.dumps('Move roadmap item: ' + tag + '-roadmap-a') + ']')
        browser('press', 'Space')
        browser('press', 'ArrowUp')
        browser('press', 'Space')
        wait("!document.body.innerText.includes('Saving roadmap…')")
        # Keyboard DnD swaps only the last two test entries.
        browser('focus', 'button[aria-label=' + json.dumps('Move roadmap item: ' + tag + '-roadmap-b') + ']')
        browser('press', 'Space')
        browser('press', 'ArrowUp')
        browser('press', 'Space')
        wait("![...document.querySelectorAll('p')].some(p => p.textContent === 'Saving roadmap…')")
        evaluate(f"const rows = await (await fetch('/api/roadmap')).json(); if (rows.findIndex(r => r.title === {json.dumps(tag + '-roadmap-b')}) >= rows.findIndex(r => r.title === {json.dumps(tag + '-roadmap-a')})) throw new Error('Roadmap order not saved')")
        # External writes become visible via the global Refresh button.
        evaluate(f"window.__external = await (await fetch('/api/tasks', {{method:'POST', headers:{{'Content-Type':'application/json','X-Dashboard-Request':'tasks'}}, body:JSON.stringify({{title:{json.dumps(tag + '-external')}}})}})).json(); if (!window.__external.id) throw new Error('Proxy POST failed')")
        evaluate(f"const rows = await (await fetch('/api/roadmap')).json(); const row = rows.find(r => r.title === {json.dumps(tag + '-roadmap-a')}); const r = await fetch('/api/roadmap/' + row.id, {{method:'PATCH', headers:{{'Content-Type':'application/json','X-Dashboard-Request':'tasks'}}, body:JSON.stringify({{title:row.title, phase:row.phase, description:'External roadmap update ' + {json.dumps(tag)}}})}}); if (!r.ok) throw new Error('Proxy PATCH failed')")
        refresh()
        wait(contains(tag + '-external'))
        wait(contains('External roadmap update ' + tag))
        # Inject storage failure at the browser boundary, then recover via Refresh.
        evaluate("window.__realFetch = window.fetch; window.fetch = (input, options) => String(input).startsWith('/api/tasks') || String(input).startsWith('/api/roadmap') ? Promise.resolve(new Response(JSON.stringify({detail:'Simulated storage outage'}), {status:503,headers:{'Content-Type':'application/json'}})) : window.__realFetch(input,options)")
        refresh()
        wait(contains('Simulated storage outage'))
        fill('New task', tag + '-failed')
        click('Add task')
        wait(contains('Simulated storage outage'))
        evaluate(f"if ([...document.querySelectorAll('.task-list li')].some(e => e.textContent.includes({json.dumps(tag + '-failed')}))) throw new Error('Failed write was rendered as saved')")
        click('Add item')
        fill('Title', tag + '-failed-roadmap')
        click('Add roadmap item')
        wait(contains('Simulated storage outage'))
        evaluate(f"if ([...document.querySelectorAll('.roadmap-card')].some(e => e.textContent.includes({json.dumps(tag + '-failed-roadmap')}))) throw new Error('Failed roadmap write was rendered as saved'); window.fetch = window.__realFetch")
        click('Cancel')
        refresh()
        wait('!' + contains('Simulated storage outage'))
        # Only our own records are removed, through UI and same-origin proxy.
        click('Remove task: ' + tag + '-edited')
        browser('dialog', 'accept')
        wait('!' + contains(tag + '-edited'))
        click('Remove roadmap item: ' + tag + '-roadmap-a')
        browser('dialog', 'accept')
        wait('!' + contains(tag + '-roadmap-a'))
        if args.production:
            evaluate("const r = await fetch('/'); const csp = r.headers.get('content-security-policy') || ''; if (!csp.includes(\"script-src 'self'\") || csp.includes('unsafe-inline') || csp.includes('unsafe-eval')) throw new Error('Production CSP missing or permissive'); for (const path of ['/api/tasks','/api/roadmap','/api/health']) { const x = await fetch(path); if (!x.ok || !x.headers.get('content-type')?.includes('application/json')) throw new Error('Proxy GET failed: '+path); } const ready = await fetch('/api/ready'); if (![200,503].includes(ready.status) || !(await ready.json()).dependencies) throw new Error('Readiness proxy failed'); for (const path of ['/api/system','/api/health']) {const x = await fetch(path,{method:'POST'}); if (![403,405].includes(x.status)) throw new Error('Proxy permitted monitoring write');}")
        browser('set', 'viewport', '390', '844')
        evaluate("if (document.documentElement.scrollWidth > innerWidth) throw new Error('Mobile horizontal overflow'); if ([...document.querySelectorAll('.project-scroll')].some(e => getComputedStyle(e).overflowY !== 'visible')) throw new Error('Nested mobile scrolling'); if (window.__regressionErrors.length || window.__violations.length) throw new Error(JSON.stringify([window.__regressionErrors,window.__violations]))")
        browser('screenshot', str(ROOT / 'data/project-regression.png'))
        fill('New task', tag + '-mobile')
        click('Add task')
        wait(contains(tag + '-mobile'))
        browser('find', 'role', 'checkbox', 'check', '--name', tag + '-mobile', '--exact')
        wait(f"[...document.querySelectorAll('.task-done')].some(e => e.textContent === {json.dumps(tag + '-mobile')})")
        click('Remove task: ' + tag + '-mobile')
        browser('dialog', 'accept')
        wait('!' + contains(tag + '-mobile'))
        evaluate("window.__goodFetch=window.fetch; window.fetch=(input,options)=>options?.method==='POST'?Promise.resolve(new Response(JSON.stringify({detail:'Cross-origin project writes are not allowed'}),{status:403,headers:{'Content-Type':'application/json'}})):window.__goodFetch(input,options)")
        fill('New task', tag + '-origin-rejected')
        click('Add task')
        wait(contains('same-origin protection'))
        evaluate("window.fetch=window.__goodFetch")
    except Exception:
        if opened:
            browser('screenshot', str(ROOT / 'data/project-regression-failed.png'))
            print(browser('snapshot', '-i'), flush=True)
        raise
    finally:
        if opened:
            try:
                evaluate(f"window.fetch = window.__realFetch || window.fetch; for (const collection of ['tasks','roadmap']) {{ const response = await fetch('/api/' + collection); if (!response.ok) throw new Error('Cleanup read failed'); const rows = await response.json(); for (const row of rows.filter(r => r.title.startsWith({json.dumps(tag)}))) {{ const result = await fetch('/api/' + collection + '/' + row.id, {{method:'DELETE',headers:{{'Content-Type':'application/json','X-Dashboard-Request':'tasks'}}}}); if (!result.ok) throw new Error('Cleanup delete failed: ' + row.id); }} }}")
            finally:
                browser('close')
    # Publish success only after cleanup and browser shutdown both succeed.
    print('PASS: Project CRUD/check/uncheck, persistence, confirmation, pointer/keyboard reordering, Refresh, failure recovery, mobile writes, Origin rejection UI' + (', production proxy and CSP' if args.production else ' (development proxy)'))


if __name__ == '__main__':
    main()
