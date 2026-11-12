import re, sys
src = open(sys.argv[1]).read()
def rep(a, b, s, count=1):
    assert s.count(a) == count, (a, s.count(a)); return s.replace(a, b)
s = src
# skeleton is added by the host
s = rep('<script src="base/dados.js"></script>\n', '', s)   # a prévia não tem pasta da base
s = rep('<!DOCTYPE html>\n<html lang="pt-BR">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n', '', s)
s = rep('</style>\n</head>\n<body>\n', '</style>\n', s)
s = rep('</script>\n</body>\n</html>\n', '</script>\n', s)
s = rep('.app{display:grid;grid-template-columns:300px minmax(0,1fr);grid-template-rows:58px minmax(0,1fr);height:100vh}',
        '.app{display:grid;grid-template-columns:300px minmax(0,1fr);grid-template-rows:58px minmax(0,1fr);height:100%}', s)
# in-memory routing (the viewer only passes plain #name hashes)
s = rep("const THEME_KEY = 'biblioteca-pn:theme';", "const THEME_KEY = 'biblioteca-pn:theme';\nlet CUR = '#/';\nfunction nav(h) { CUR = h; onRoute(); }", s)
s = rep("const raw = location.hash.replace(/^#\\/?/, '');", "const raw = CUR.replace(/^#\\/?/, '');", s)
s = rep("""  const h = kind ? href(kind, id) : '#/';
  if (location.hash === h) render(); else location.hash = h;""", "  nav(kind ? href(kind, id) : '#/');", s)
s = rep("window.addEventListener('hashchange', () => {", "function onRoute() {", s)
s = rep("  $('#main').scrollTop = 0;\n});", "  $('#main').scrollTop = 0;\n}", s)
s = rep("location.hash = items[srActive].getAttribute('href');", "nav(items[srActive].getAttribute('href'));", s)
s = rep("  if (!b) return;\n  const fn = ACT[b.dataset.act];",
        "  const ln = ev.target.closest('a[href^=\"#/\"]');\n  if (ln && !b) { ev.preventDefault(); nav(ln.getAttribute('href')); return; }\n  if (!b) return;\n  const fn = ACT[b.dataset.act];", s)
# downloads are blocked in the viewer: hide exports
s = re.sub(r'\s*<button data-act="export-html">.*?<hr>', '\n          <button data-act="copy-standalone"><svg viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h8"/></svg><span>Copiar código HTML<small>Para colar no Bloco de Notas e usar em outro PC</small></span></button><hr>', s, count=1, flags=re.S)
s = re.sub(r'\s*<button data-act="connect-base">.*?</button>', '', s, count=1, flags=re.S)   # sem pasta na prévia
s = rep("return window.showDirectoryPicker\n      ? box(", "return false\n      ? box(", s)
s = rep("box('local', 'warn', 'Alterações salvas só neste navegador', 'Clique para salvar um novo HTML e compartilhar.', 'export-html')", "box('local', 'warn', 'Alterações salvas só neste navegador', 'Prévia online: as edições não saem daqui.')", s)
s = rep('Use <b>Dados › Salvar como HTML</b> para compartilhar.', 'Na prévia, as edições ficam só neste navegador.', s)
assert 'data-act="export-html"' not in s.split('<script>')[0]
# --- copy-standalone: the original offline file, with the current data, to the clipboard ---
import json
s = rep("  'import': () => requireUnlock(() => $('#fileInput').click()),", """  'copy-standalone': () => {
    const doc = new DOMParser().parseFromString(JSON.parse($('#standalone-src').textContent), 'text/html');
    doc.getElementById('seed-data').textContent = '\\n' + JSON.stringify(db, null, 1).replace(/</g, '\\\\u003c') + '\\n';
    const code = '<!DOCTYPE html>\\n' + doc.documentElement.outerHTML;
    const steps = '<ol style="margin:0;padding-left:20px;line-height:1.7"><li>Abra o <b>Bloco de Notas</b> e cole (<b>Ctrl+V</b>).</li><li><b>Arquivo › Salvar como</b>.</li><li>Nome: <b class="mono">Biblioteca_PN.html</b></li><li>Tipo: <b>Todos os arquivos (*.*)</b></li><li>Codificação: <b>UTF-8</b></li><li>Dê duplo clique no arquivo salvo.</li></ol>';
    const manual = () => openForm({title: 'Copie o código', submit: 'Fechar', fields: [{type: 'info', html:
      '<p style="margin:0 0 8px">O navegador não deixou copiar sozinho. Clique na caixa, aperte <b>Ctrl+A</b> e depois <b>Ctrl+C</b>.</p><textarea id="codeBox" readonly style="width:100%;height:150px;font:11px var(--mono);border:1px solid var(--border-strong);border-radius:8px;padding:8px;background:var(--surface-2);color:var(--text)">' + esc(code) + '</textarea><p style="margin:12px 0 6px"><b>Depois:</b></p>' + steps}], onSubmit: () => {}});
    let p;
    try { p = navigator.clipboard.writeText(code); } catch (_) { p = Promise.reject(); }
    p.then(() => openForm({title: 'Código copiado', submit: 'Entendi', fields: [{type: 'info', html:
      '<p style="margin:0 0 10px">O código da biblioteca, com os dados atuais, está na área de transferência.</p>' + steps}], onSubmit: () => {}}),
      () => { manual(); const t = $('#codeBox'); if (t) { t.focus(); t.select(); } });
  },
  'import': () => requireUnlock(() => $('#fileInput').click()),""", s)

s = rep('<script>\n(() => {', '<script id="standalone-src" type="application/json">' + json.dumps(src).replace('<', '\\u003c') + '</script>\n<script>\n(() => {', s)
open(sys.argv[2], 'w').write(s)
