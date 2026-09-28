/* ==========================================================================
   TEST RUNNER

   VS Code loads this into the extension host when it is started with
   --extensionTestsPath (test/vscode_driver.py does), activates the
   extension, and stays up until run() returns. It is not packaged. The
   driver works VS Code through a folder, KVOT_HDF5_TEST_DIR:

     commands.jsonl  what to do, one JSON object a line: {"id", "cmd", ...}
     events.jsonl    what happened: every command's ack, and what the pages
                     and views reported (ready, status, log, saved, failed)

   The Save and open dialogs are native and cannot be clicked from a test, so
   the next answer to each can be given here instead.
   ========================================================================== */

'use strict';

const vscode = require('vscode');
const fs = require('fs');
const path = require('path');

exports.run = async () => {
  const extension = vscode.extensions.getExtension('kvotab.hdf5-browser');
  const { provider, log, viewType } = await extension.activate();
  const dir = process.env.KVOT_HDF5_TEST_DIR;
  const commandsFile = path.join(dir, 'commands.jsonl');
  const eventsFile = path.join(dir, 'events.jsonl');
  const saves = [];
  const picks = [];

  const event = (e) => {
    try {
      fs.appendFileSync(eventsFile, JSON.stringify(Object.assign({ t: Date.now() }, e)) + '\n');
    } catch (_) { /* the test has gone */ }
  };
  // A test never sees a native dialog: a save nobody asked for goes to the
  // test's own folder, and an open dialog nobody answered is cancelled.
  fs.mkdirSync(path.join(dir, 'saved'), { recursive: true });
  provider.testHooks = {
    event,
    takeSave: name => saves.shift() || vscode.Uri.file(path.join(dir, 'saved', name)),
    takePick: () => picks.shift() || []
  };

  const uri = p => vscode.Uri.file(p);
  const commands = {
    // A file opened as VS Code opens it from the Explorer, which puts it into a
    // browser showing in the group; with `own` in a view of its own, as the
    // extension opens one for itself (for a test that is not about where a
    // file goes); with `preview` as a single click opens it.
    async open({ paths, own, preview }) {
      for (const p of paths) {
        const u = uri(p);
        if (own) provider.opening.add(u.toString());
        try {
          await vscode.commands.executeCommand('vscode.openWith', u, viewType, preview ? { preview: true } : undefined);
        } finally {
          if (own) provider.opening.delete(u.toString());
        }
      }
    },
    async closeTab({ label }) {
      const tab = vscode.window.tabGroups.all.flatMap(g => g.tabs).find(t => t.label === label);
      if (tab) await vscode.window.tabGroups.close(tab);
      return !!tab;
    },
    async tabs() {
      return vscode.window.tabGroups.all.flatMap(g => g.tabs.map(t => ({
        group: g.viewColumn, label: t.label, active: t.isActive && g.isActive, preview: t.isPreview,
        custom: t.input instanceof vscode.TabInputCustom ? t.input.viewType : null
      })));
    },
    async together({ paths }) {
      await provider.openTogether(undefined, paths.map(uri));
    },
    async nextSave({ path: p }) {
      saves.push(uri(p));
    },
    async nextPick({ paths }) {
      picks.push(paths.map(uri));
    },
    async setting({ section, key, value }) {
      await vscode.workspace.getConfiguration(section).update(key, value, vscode.ConfigurationTarget.Global);
    },
    async getSetting({ section, key }) {
      return vscode.workspace.getConfiguration(section).get(key);
    },
    async closeAll() {
      await vscode.commands.executeCommand('workbench.action.closeAllEditors');
    },
    async views() {
      return [...provider.views.keys()];
    },
    async quit() {
      // run() returning is what ends the test and closes VS Code.
      setTimeout(finish, 100);
    }
  };
  let finish;
  const finished = new Promise(resolve => { finish = resolve; });

  let done = 0;
  let busy = false;
  const poll = setInterval(async () => {
    if (busy) return;
    let text;
    try {
      text = fs.readFileSync(commandsFile, 'utf8');
    } catch (_) {
      return;
    }
    const lines = text.split('\n').filter(Boolean);
    busy = true;
    try {
      while (done < lines.length) {
        const line = lines[done++];
        let cmd;
        try {
          cmd = JSON.parse(line);
        } catch (e) {
          event({ type: 'ack', error: `not JSON: ${line}` });
          continue;
        }
        try {
          const fn = commands[cmd.cmd];
          if (!fn) throw new Error(`no test command ${cmd.cmd}`);
          event({ type: 'ack', id: cmd.id, result: await fn(cmd) });
        } catch (e) {
          event({ type: 'ack', id: cmd.id, error: String(e && e.message || e) });
        }
      }
    } finally {
      busy = false;
    }
  }, 150);
  log.info(`Test runner on, in ${dir}`);
  event({ type: 'activated', version: vscode.version });
  await finished;
  clearInterval(poll);
};
