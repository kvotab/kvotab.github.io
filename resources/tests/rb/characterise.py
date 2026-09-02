"""Characterisation test for rb.html.

Drives the page through its whole feature surface and prints a deterministic
fingerprint. Run before a refactor, run after, diff the two: any difference is
a behaviour change.
"""
import asyncio
import json
import sys
import urllib.request

import websockets

from driver import open_page, load_samples

GROUP = '/biosphere/1BLA/drained_mire/total'

# Every step returns a JSON-able value that goes into the fingerprint.
STEPS = [
    ('dom.inventory', """(() => ({
      controlIds: [...document.querySelectorAll('[id]')].map(e => e.id).sort(),
      inputs: [...document.querySelectorAll('input,select,button')].length,
      dialogs: [...document.querySelectorAll('.url-dialog-overlay, .preset-overlay')].map(d => d.id).sort(),
      treePlaceholder: document.getElementById('tree').textContent.trim().slice(0, 60),
      chartControlLabels: [...document.querySelectorAll('.chart-controls label')].map(l => l.textContent.trim().replace(/\\s+/g,' ')),
      hiddenAtStart: [...document.querySelectorAll('[style*="display: none"], [style*="display:none"]')].map(e => e.id || e.className).sort()
    }))()"""),

    ('globals.present', """(() => {
      const names = ['loadedFiles','fileStates','fileOrder','loadedFileBuffers','selectedDatasetPath',
        'selectedFileKey','selectedDatasets','multiSelectMode','selectedIsRadionuclidesGroup',
        'currentChartData','currentSearchTerm'];
      const fns = ['handleFile','removeFile','toggleFileState','updateTabs','refreshTreeStructure','buildTree',
        'selectDataset','toggleGroup','toggleGroupExpansion','filterTree','createPlotlyChart',
        'createMultiDatasetChart','createRadionuclidesChart','downloadChartData','downloadChartDataAsExcel',
        'openUrlDialog','closeUrlDialog','loadFromUrl','openSampleDataDialog','closeSampleDataDialog',
        'loadSelectedSampleData','openPresetManager','closePresetManager','toggleDynamicLegend',
        'toggleShowTotal','toggleShowRatio','toggleShowMax','toggleShowCI','toggleShowSDOM',
        'toggleShowIteration','toggleBackgroundOverlay','toggleAxesLock','applySelectedPreset',
        'saveCurrentAsPreset','redrawHistogram','cancelTreeRefresh','getEnabledFiles','getTreeMode',
        'releaseLoadedFile','findTreeItem','getPathChildIndex','getRealizationStride'];
      return {
        globals: names.map(n => n + '=' + (typeof window[n])),
        functions: fns.map(n => n + '=' + (typeof window[n])).sort()
      };
    })()"""),

    ('load.two.files', """(async () => {
      await waitForH5Wasm();
      const { FS, File } = window.h5wasm;
      for (const name of ['SFR_FSAR_CCP14.h5', 'SFR_FSAR_CCP26.h5']) {
        const buf = await (await fetch('./resources/data/' + name)).arrayBuffer();
        loadedFileBuffers[name] = buf;
        const internal = '/b_' + name.replace(/[^a-z0-9]/gi,'') + '.h5';
        try { FS.unlink(internal); } catch (e) {}
        FS.writeFile(internal, new Uint8Array(buf));
        loadedFiles[name] = new File(internal, 'r');
        fileStates[name] = true;
        if (!fileOrder.includes(name)) fileOrder.push(name);
      }
      await updateTabs(true);
      return {
        order: fileOrder.slice(),
        enabled: getEnabledFiles(),
        tabs: [...document.querySelectorAll('.file-tab')].map(t => t.getAttribute('data-file')),
        treeRows: document.querySelectorAll('#tree .tree-item').length,
        searchVisible: document.querySelector('.search-container').classList.contains('visible'),
        modeToggleShown: document.getElementById('treeModeContainer').style.display
      };
    })()"""),

    ('tree.expand', """(async () => {
      await expandAndLoadPath('SFR_FSAR_CCP14.h5', %s);
      await new Promise(r => setTimeout(r, 900));
      const rows = [...document.querySelectorAll('#tree .tree-item')];
      return {
        rows: rows.length,
        classes: [...new Set(rows.map(r => r.className))].sort(),
        firstTenPaths: rows.slice(0, 10).map(r => r.getAttribute('data-path'))
      };
    })()""" % json.dumps(GROUP)),

    ('select.dataset', """(async () => {
      const ds = findTreeItem(%s, { extra: '.dataset' });
      ds.click();
      await new Promise(r => setTimeout(r, 2500));
      const plot = document.getElementById('plotlyChart');
      return {
        selectedPath: selectedDatasetPath,
        isGroup: selectedIsRadionuclidesGroup,
        domSelected: document.querySelectorAll('#tree .tree-item.selected').length,
        traces: (plot.data || []).length,
        traceNames: (plot.data || []).map(t => t.name),
        firstY: (plot.data || [])[0] ? (plot.data[0].y || []).slice(0, 4) : null,
        xTitle: plot.layout && plot.layout.xaxis ? plot.layout.xaxis.title : null,
        infoHeadingShown: document.getElementById('datasetInfoHeading').style.display
      };
    })()""" % json.dumps(GROUP + '/Ac-227')),

    ('select.group', """(async () => {
      findTreeItem(%s, { extra: '.group' }).click();
      await new Promise(r => setTimeout(r, 4000));
      const plot = document.getElementById('plotlyChart');
      return {
        selectedPath: selectedDatasetPath,
        isGroup: selectedIsRadionuclidesGroup,
        traces: (plot.data || []).length,
        firstFiveNames: (plot.data || []).slice(0, 5).map(t => t.name),
        showTotalVisible: document.getElementById('showTotalLabel').style.display,
        showMaxVisible: document.getElementById('showMaxLabel').style.display
      };
    })()""" % json.dumps(GROUP)),

    ('chart.toggles', """(async () => {
      const out = {};
      const plot = () => (document.getElementById('plotlyChart').data || []).length;
      const total = document.getElementById('showTotal');
      total.checked = !total.checked; toggleShowTotal();
      await new Promise(r => setTimeout(r, 2000)); out.afterTotalToggle = plot();
      const mx = document.getElementById('showMax');
      mx.checked = true; toggleShowMax();
      await new Promise(r => setTimeout(r, 2000)); out.afterMax = plot();
      out.legendHasMax = (document.getElementById('plotlyChart').data || [])
        .slice(0, 3).map(t => /max/i.test(t.name || ''));
      const dl = document.getElementById('dynamicLegend');
      dl.checked = false; toggleDynamicLegend();
      await new Promise(r => setTimeout(r, 800)); out.afterDynamicLegendOff = plot();
      out.legendStatus = document.getElementById('legendStatus').textContent;
      return out;
    })()"""),

    ('chart.scales', """(async () => {
      const out = {};
      document.querySelector('#xScaleToggle button[data-value="log"]').click();
      await new Promise(r => setTimeout(r, 1200));
      out.xType = document.getElementById('plotlyChart').layout.xaxis.type;
      document.querySelector('#yScaleToggle button[data-value="log"]').click();
      await new Promise(r => setTimeout(r, 1200));
      out.yType = document.getElementById('plotlyChart').layout.yaxis.type;
      out.activeButtons = [...document.querySelectorAll('.scale-toggle button.active')]
        .map(b => b.dataset.axis + ':' + b.dataset.value);
      document.querySelector('#xScaleToggle button[data-value="linear"]').click();
      document.querySelector('#yScaleToggle button[data-value="linear"]').click();
      await new Promise(r => setTimeout(r, 1200));
      return out;
    })()"""),

    ('multi.select', """(async () => {
      const rows = [...document.querySelectorAll('#tree .tree-item.dataset')].slice(0, 4);
      for (const r of rows) {
        r.dispatchEvent(new MouseEvent('click', { bubbles: true, ctrlKey: true }));
        await new Promise(res => setTimeout(res, 150));
      }
      await new Promise(r => setTimeout(r, 2500));
      const plot = document.getElementById('plotlyChart');
      return {
        multiMode: multiSelectMode,
        selectedCount: selectedDatasets.length,
        domMarked: document.querySelectorAll('#tree .tree-item.dataset.selected').length,
        traces: (plot.data || []).length
      };
    })()"""),

    ('search', """(async () => {
      const out = {};
      const inp = document.getElementById('treeSearch');
      for (const term of ['Am', 'Am-241', 'Am*1', 'biosphere/1BLA', 'zzz-no-match']) {
        inp.value = term;
        filterTree(term);
        await new Promise(r => setTimeout(r, 250));
        out[term] = {
          matches: document.querySelectorAll('#tree .tree-item.search-match').length,
          hidden: document.querySelectorAll('#tree .tree-item.search-hidden').length,
          pathSearch: isPathSearchTerm(term)
        };
      }
      inp.value = ''; filterTree('');
      await new Promise(r => setTimeout(r, 250));
      out.afterClear = {
        matches: document.querySelectorAll('#tree .tree-item.search-match').length,
        hidden: document.querySelectorAll('#tree .tree-item.search-hidden').length
      };
      return out;
    })()"""),

    ('tree.modes', """(async () => {
      const out = {};
      for (const mode of ['intersect', 'union', 'separated']) {
        document.querySelector('#treeModeContainer button[data-value="' + mode + '"]').click();
        await new Promise(r => setTimeout(r, 7000));
        out[mode] = {
          reported: getTreeMode(),
          rows: document.querySelectorAll('#tree .tree-item').length,
          intersected: window._currentIntersectedPaths ? window._currentIntersectedPaths.size : null,
          activeButton: document.querySelector('#treeModeContainer button.active').dataset.value
        };
      }
      return out;
    })()"""),

    ('dialogs', """(() => {
      const state = id => document.getElementById(id).style.display;
      const out = {};
      openUrlDialog();  out.urlOpen = state('urlDialog');
      out.urlInputValue = document.getElementById('urlInput').value;
      closeUrlDialog(); out.urlClosed = state('urlDialog');
      openPresetManager(); out.presetOpen = state('presetManagerOverlay');
      out.presetRows = document.querySelectorAll('#presetManagerList *').length > 0;
      closePresetManager(); out.presetClosed = state('presetManagerOverlay');
      out.presetOptions = [...document.getElementById('presetSelect').options].map(o => o.value);
      return out;
    })()"""),

    ('exports', """(async () => {
      const out = {};
      await expandAndLoadPath('SFR_FSAR_CCP14.h5', %s);
      await new Promise(r => setTimeout(r, 900));
      findTreeItem(%s, { extra: '.dataset' }).click();
      await new Promise(r => setTimeout(r, 2500));
      try { downloadChartData(); out.csv = 'ok'; } catch (e) { out.csv = 'threw: ' + e.message; }
      try { await downloadChartDataAsExcel(); out.excel = 'ok'; } catch (e) { out.excel = 'threw: ' + e.message; }
      return out;
    })()""" % (json.dumps(GROUP), json.dumps(GROUP + '/Ac-227'))),

    ('file.toggle.remove', """(async () => {
      const out = {};
      toggleFileState('SFR_FSAR_CCP26.h5');
      await new Promise(r => setTimeout(r, 4000));
      out.afterDisable = { enabled: getEnabledFiles(), rows: document.querySelectorAll('#tree .tree-item').length };
      toggleFileState('SFR_FSAR_CCP26.h5');
      await new Promise(r => setTimeout(r, 4000));
      out.afterEnable = { enabled: getEnabledFiles(), rows: document.querySelectorAll('#tree .tree-item').length };
      const memBefore = window.h5wasm.FS.readdir('/').filter(n => n.endsWith('.h5')).length;
      await removeFile('SFR_FSAR_CCP26.h5');
      await new Promise(r => setTimeout(r, 3000));
      out.afterRemove = {
        enabled: getEnabledFiles(),
        loadedKeys: Object.keys(loadedFiles),
        memfsBefore: memBefore,
        memfsAfter: window.h5wasm.FS.readdir('/').filter(n => n.endsWith('.h5')).length
      };
      return out;
    })()"""),

    ('bad.input', """(async () => {
      const out = {};
      // A non-HDF5 payload must be rejected by the validator, not crash.
      const junk = new ArrayBuffer(64);
      out.validatorRejects = validateHdf5Buffer(junk);
      out.validatorRejectsEmpty = validateHdf5Buffer(new ArrayBuffer(0));
      const html = new TextEncoder().encode('<!doctype html><html>oops</html>').buffer;
      out.validatorRejectsHtml = validateHdf5Buffer(html);
      const lfs = new TextEncoder().encode('version https://git-lfs.github.com/spec/v1\\noid sha256:x').buffer;
      out.validatorRejectsLfs = validateHdf5Buffer(lfs);
      // A missing path must return null rather than throw.
      out.missingPath = checkIfPathExistsInFile('SFR_FSAR_CCP14.h5', '/does/not/exist');
      out.missingFile = checkIfPathExistsInFile('nope.h5', '/time');
      return out;
    })()"""),
]


async def main():
    label = sys.argv[1] if len(sys.argv) > 1 else 'baseline'
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=300 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=8)
        fingerprint = {}
        for name, expr in STEPS:
            try:
                value = await page.ev(expr, timeout=180)
            except Exception as exc:
                value = 'HARNESS ERROR: %s' % exc
            fingerprint[name] = value
            head = json.dumps(value, sort_keys=True)[:110] if not isinstance(value, str) else value[:110]
            print('  %-22s %s' % (name, head))

        fingerprint['_console'] = [
            '%s: %s' % (k, m[:150]) for k, m in page.logs
            if 'favicon' not in m.lower()
        ]
        out = '%s.json' % label
        with open(out, 'w') as fh:
            json.dump(fingerprint, fh, indent=1, sort_keys=True)
        print('\nwrote %s   console entries: %d' % (out, len(fingerprint['_console'])))
        for line in fingerprint['_console'][:8]:
            print('   ', line)
        await bws.send(json.dumps({'id': 99, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))

asyncio.run(main())
