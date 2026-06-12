// Gamentic setup wizard, the static face. Everything a user is asked comes from
// window.GAMENTIC_SETUP_SCHEMA (schema.js); this file carries zero setting
// knowledge of its own. Plain script on purpose: it must run from file:// with
// no server, no build step and no network. The pure helpers live on
// window.GamenticSetup so the test suite can drive them directly.
(function () {
  "use strict";

  function el(tag, className, text) {
    var n = document.createElement(tag);
    if (className) n.className = className;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  // ---------- pure helpers ----------

  // KEY=value lines -> { KEY: value }. Tolerates comments, blank lines, an
  // optional `export ` prefix and surrounding quotes. Anything else is skipped.
  function parseEnv(text) {
    var values = {};
    String(text || "").split(/\r?\n/).forEach(function (raw) {
      var line = raw.trim();
      if (!line || line.charAt(0) === "#") return;
      var m = /^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/.exec(line);
      if (!m) return;
      var v = m[2].trim();
      if (v.length >= 2 && ((v.charAt(0) === '"' && v.charAt(v.length - 1) === '"') ||
                            (v.charAt(0) === "'" && v.charAt(v.length - 1) === "'"))) {
        v = v.slice(1, -1);
      }
      values[m[1]] = v;
    });
    return values;
  }

  function wrapComment(text, width) {
    width = width || 96;
    var lines = [];
    var line = "";
    String(text).split(/\s+/).forEach(function (word) {
      if (line && (line + " " + word).length > width) {
        lines.push(line);
        line = word;
      } else {
        line = line ? line + " " + word : word;
      }
    });
    if (line) lines.push(line);
    return lines;
  }

  // The complete .env: every schema setting (answer or default), grouped and
  // documented with the schema help verbatim, then the constants verbatim, then
  // any unknown lines preserved under a labeled unmanaged section.
  function serializeEnv(answers, schema, unknownLines) {
    var out = [
      "# Gamentic stack config (" + schema.envFile + "). Generated from infra/setup/schema.js by the",
      "# setup wizard. Re-run setup.html (or gamentic-setup) to change managed keys; hand",
      "# edits to them are overwritten. Keys the schema does not know survive in the",
      "# unmanaged section at the end.",
    ];
    schema.groups.forEach(function (group) {
      var settings = schema.settings.filter(function (s) { return s.group === group.id; });
      if (!settings.length) return;
      out.push("");
      out.push("# --- " + group.label + " ---");
      settings.forEach(function (s) {
        wrapComment(s.help).forEach(function (l) { out.push("# " + l); });
        var v = answers[s.key] !== undefined ? answers[s.key] : s.default;
        out.push(s.key + "=" + v);
      });
    });
    (schema.constants || []).forEach(function (c) {
      out.push("");
      wrapComment(c.comment).forEach(function (l) { out.push("# " + l); });
      out.push(c.key + "=" + c.value);
    });
    if (unknownLines && unknownLines.length) {
      out.push("");
      out.push("# --- unmanaged: keys this setup does not know, preserved verbatim from your previous " + schema.envFile + " ---");
      unknownLines.forEach(function (l) { out.push(l); });
    }
    return out.join("\n") + "\n";
  }

  // The settings actually ASKED in a mode, in group order then schema order:
  // the group must be visible in the mode, advanced is custom-only, and a
  // setting the mode answers itself (setByMode) is never asked.
  function visibleSettings(schema, mode) {
    var asked = [];
    schema.groups.forEach(function (group) {
      if (group.modes.indexOf(mode) === -1) return;
      schema.settings.forEach(function (s) {
        if (s.group !== group.id) return;
        if (s.advanced && mode !== "custom") return;
        if (s.setByMode && s.setByMode[mode] !== undefined) return;
        asked.push(s);
      });
    });
    return asked;
  }

  // null when the value is acceptable, a short message when it is not.
  function validate(setting, value) {
    var v = String(value === undefined || value === null ? "" : value).trim();
    switch (setting.type) {
      case "bool":
        return v === "true" || v === "false" ? null : "must be exactly true or false (lowercase)";
      case "int":
        return /^\d+$/.test(v) ? null : "must be a whole number";
      case "port":
        return /^\d+$/.test(v) && Number(v) >= 1 && Number(v) <= 65535 ? null : "must be a port number between 1 and 65535";
      case "choice":
        return setting.choices.indexOf(v) !== -1 ? null : "must be one of: " + setting.choices.join(", ");
      case "path":
      case "path-relative":
        return v !== "" ? null : "cannot be empty";
      default:
        return null; // string and secret accept anything, including blank
    }
  }

  // ---------- saving ----------

  // Chromium writes the file where the user points; everything else gets a
  // download. A user cancelling the picker is a cancel, not a failure.
  function browserSave(text) {
    var picker = typeof window.showSaveFilePicker === "function"
      ? window.showSaveFilePicker({ suggestedName: ".env" }).then(function (handle) {
          return handle.createWritable().then(function (writable) {
            return writable.write(text).then(function () { return writable.close(); });
          });
        }).then(function () { return "picker"; }, function (err) {
          if (err && err.name === "AbortError") return "cancelled";
          return "download";
        })
      : Promise.resolve("download");
    return picker.then(function (method) {
      if (method !== "download") return method;
      var url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
      var a = document.createElement("a");
      a.href = url;
      a.download = ".env";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      return "download";
    });
  }

  // ---------- the wizard ----------

  function mount(rootEl, schema, opts) {
    opts = opts || {};
    var save = opts.save || browserSave;
    var settingByKey = {};
    schema.settings.forEach(function (s) { settingByKey[s.key] = s; });
    var constantKeys = {};
    (schema.constants || []).forEach(function (c) { constantKeys[c.key] = true; });

    var state = {
      step: "welcome", // welcome | mode | ask | review | done
      mode: null,
      groupIdx: 0,
      answers: {},
      unknownLines: [],
      loaded: false,
      loadedCount: 0,
      loadedName: "",
      saveMethod: "",
    };

    // Known keys from an existing .env prefill the answers (so re-running keeps
    // earlier choices); unknown keys are kept aside for the unmanaged section.
    function applyEnvText(text, name) {
      var parsed = parseEnv(text);
      state.unknownLines = [];
      state.loadedCount = 0;
      Object.keys(parsed).forEach(function (k) {
        if (settingByKey[k]) {
          state.answers[k] = parsed[k];
          state.loadedCount += 1;
        } else if (!constantKeys[k]) {
          state.unknownLines.push(k + "=" + parsed[k]);
        }
      });
      state.loaded = true;
      state.loadedName = name || "";
    }

    function askGroups() {
      var asked = visibleSettings(schema, state.mode);
      return schema.groups.filter(function (g) {
        return asked.some(function (s) { return s.group === g.id; });
      });
    }

    function chooseMode(modeId) {
      state.mode = modeId;
      schema.settings.forEach(function (s) {
        if (s.setByMode && s.setByMode[modeId] !== undefined) state.answers[s.key] = s.setByMode[modeId];
      });
      state.groupIdx = 0;
      state.step = askGroups().length ? "ask" : "review";
      render();
    }

    function answerOf(s) {
      return state.answers[s.key] !== undefined ? state.answers[s.key] : s.default;
    }

    function maskedValue(s, v) {
      if (s.type === "secret") return v ? "••••••••" : "(blank)";
      return v === "" ? "(blank)" : v;
    }

    // ---------- views ----------

    function navRow(buttons) {
      var row = el("div", "setup-nav");
      buttons.forEach(function (b) { row.appendChild(b); });
      return row;
    }

    function button(label, primary, onClick) {
      var b = el("button", primary ? "setup-btn setup-btn-primary" : "setup-btn", label);
      b.type = "button";
      b.addEventListener("click", onClick);
      return b;
    }

    function welcomeView() {
      var panel = el("section", "setup-panel");
      panel.appendChild(el("h2", "setup-h2", "Welcome"));
      panel.appendChild(el("p", "setup-intro",
        "This wizard writes the one config file the stack reads: " + schema.envFile + ". " +
        "It runs entirely from this file on your machine: no server, no build step, no network " +
        "requests, nothing uploaded. Keys you type never leave the page."));

      var zone = el("button", "setup-dropzone",
        "Load an existing " + schema.envFile + " (optional): drop it here or click to browse. " +
        "Its values prefill the questions; keys this setup does not know are preserved.");
      zone.type = "button";
      var file = document.createElement("input");
      file.type = "file";
      file.hidden = true;
      function loadFile(f) {
        if (!f) return;
        f.text().then(function (text) {
          applyEnvText(text, f.name);
          render();
        });
      }
      zone.addEventListener("click", function () { file.click(); });
      zone.addEventListener("dragover", function (e) { e.preventDefault(); zone.classList.add("setup-dropzone-over"); });
      zone.addEventListener("dragleave", function () { zone.classList.remove("setup-dropzone-over"); });
      zone.addEventListener("drop", function (e) {
        e.preventDefault();
        zone.classList.remove("setup-dropzone-over");
        loadFile(e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]);
      });
      file.addEventListener("change", function () { loadFile(file.files && file.files[0]); });
      panel.appendChild(zone);
      panel.appendChild(file);

      if (state.loaded) {
        var note = "Loaded " + state.loadedCount + " known values" +
          (state.loadedName ? " from " + state.loadedName : "") + ".";
        if (state.unknownLines.length) {
          note += " " + state.unknownLines.length + " unfamiliar key(s) will be kept in the unmanaged section at the end of the new file.";
        }
        panel.appendChild(el("p", "setup-loaded", note));
      }

      panel.appendChild(navRow([button("Start", true, function () { state.step = "mode"; render(); })]));
      return panel;
    }

    function modeView() {
      var panel = el("section", "setup-panel");
      panel.appendChild(el("h2", "setup-h2", "Pick a mode"));
      schema.modes.forEach(function (m) {
        var card = el("button", "setup-mode-card");
        card.type = "button";
        card.appendChild(el("strong", "setup-mode-label", m.label));
        card.appendChild(el("p", "setup-mode-help", m.help));
        card.addEventListener("click", function () { chooseMode(m.id); });
        panel.appendChild(card);
      });
      panel.appendChild(navRow([button("Back", false, function () { state.step = "welcome"; render(); })]));
      return panel;
    }

    function fieldView(s) {
      var current = answerOf(s);
      var field = el("div", "setup-field");
      field.dataset.key = s.key;

      var head = el("div", "setup-field-head");
      var id = "setup-f-" + s.key;
      if (s.type === "bool") {
        head.appendChild(el("span", "setup-prompt", s.prompt));
      } else {
        var label = el("label", "setup-prompt", s.prompt);
        label.htmlFor = id;
        head.appendChild(label);
      }
      var help = el("p", "setup-help", s.help);
      help.hidden = true;
      var helpBtn = el("button", "setup-help-btn", "?");
      helpBtn.type = "button";
      helpBtn.setAttribute("aria-label", "help: " + s.prompt);
      helpBtn.setAttribute("aria-expanded", "false");
      helpBtn.addEventListener("click", function () {
        help.hidden = !help.hidden;
        helpBtn.setAttribute("aria-expanded", String(!help.hidden));
      });
      head.appendChild(helpBtn);
      field.appendChild(head);

      if (s.type === "choice") {
        var sel = document.createElement("select");
        sel.id = id;
        sel.className = "setup-input";
        s.choices.forEach(function (c) {
          var o = document.createElement("option");
          o.value = c;
          o.textContent = c;
          if (c === current) o.selected = true;
          sel.appendChild(o);
        });
        field.appendChild(sel);
      } else if (s.type === "bool") {
        var row = el("div", "setup-bool");
        ["true", "false"].forEach(function (v) {
          var lab = el("label", "setup-bool-option");
          var r = document.createElement("input");
          r.type = "radio";
          r.name = "setup-r-" + s.key;
          r.value = v;
          r.checked = current === v;
          lab.appendChild(r);
          lab.appendChild(document.createTextNode(v === "true" ? " yes" : " no"));
          row.appendChild(lab);
        });
        field.appendChild(row);
      } else {
        var input = document.createElement("input");
        input.id = id;
        input.className = "setup-input";
        input.type = s.type === "secret" ? "password" : "text";
        input.value = current;
        input.autocomplete = "off";
        input.spellcheck = false;
        if (s.type === "secret") {
          var wrap = el("div", "setup-secret");
          wrap.appendChild(input);
          var show = el("button", "setup-show-btn", "show");
          show.type = "button";
          show.addEventListener("click", function () {
            var showing = input.type === "text";
            input.type = showing ? "password" : "text";
            show.textContent = showing ? "show" : "hide";
          });
          wrap.appendChild(show);
          field.appendChild(wrap);
        } else {
          field.appendChild(input);
        }
      }

      field.appendChild(help);
      var err = el("p", "setup-error");
      err.hidden = true;
      field.appendChild(err);
      return field;
    }

    // Store everything typed in this step; with check=true also validate and
    // surface per-field errors. Returns false when something blocks the advance.
    function commitStep(panel, check) {
      var ok = true;
      var fields = panel.querySelectorAll(".setup-field");
      for (var i = 0; i < fields.length; i++) {
        var fieldEl = fields[i];
        var s = settingByKey[fieldEl.dataset.key];
        var v;
        if (s.type === "bool") {
          var checked = fieldEl.querySelector("input:checked");
          v = checked ? checked.value : "";
        } else {
          v = fieldEl.querySelector("select, input").value.trim();
        }
        state.answers[s.key] = v;
        if (!check) continue;
        var msg = validate(s, v);
        var err = fieldEl.querySelector(".setup-error");
        err.textContent = msg || "";
        err.hidden = !msg;
        fieldEl.classList.toggle("setup-field-invalid", !!msg);
        if (msg) ok = false;
      }
      return ok;
    }

    function askView() {
      var groups = askGroups();
      var group = groups[state.groupIdx];
      var panel = el("section", "setup-panel");
      panel.appendChild(el("p", "setup-step-caption", "Step " + (state.groupIdx + 1) + " of " + groups.length));
      panel.appendChild(el("h2", "setup-h2", group.label));
      visibleSettings(schema, state.mode).forEach(function (s) {
        if (s.group === group.id) panel.appendChild(fieldView(s));
      });
      panel.appendChild(navRow([
        button("Back", false, function () {
          commitStep(panel, false);
          if (state.groupIdx > 0) state.groupIdx -= 1;
          else state.step = "mode";
          render();
        }),
        button("Next", true, function () {
          if (!commitStep(panel, true)) return;
          if (state.groupIdx + 1 < groups.length) state.groupIdx += 1;
          else state.step = "review";
          render();
        }),
      ]));
      return panel;
    }

    // Review shows what the user decided plus what the mode decided for them;
    // everything else lands in the file with its schema default.
    function reviewView() {
      var panel = el("section", "setup-panel");
      panel.appendChild(el("h2", "setup-h2", "Review"));
      var asked = visibleSettings(schema, state.mode);
      schema.groups.forEach(function (group) {
        var shown = schema.settings.filter(function (s) {
          if (s.group !== group.id) return false;
          if (s.setByMode && s.setByMode[state.mode] !== undefined) return true;
          return asked.indexOf(s) !== -1;
        });
        if (!shown.length) return;
        panel.appendChild(el("h3", "setup-h3", group.label));
        shown.forEach(function (s) {
          var row = el("div", "setup-review-row");
          row.appendChild(el("span", "setup-review-key", s.key));
          row.appendChild(el("span", "setup-review-value", maskedValue(s, answerOf(s))));
          panel.appendChild(row);
        });
      });
      var note = "Everything not shown here is written to " + schema.envFile +
        " with its schema default, plus the COMPOSE_PROFILES constant.";
      if (state.unknownLines.length) {
        note += " " + state.unknownLines.length + " unfamiliar key(s) from your loaded file are preserved at the end.";
      }
      panel.appendChild(el("p", "setup-review-note", note));
      var groups = askGroups();
      var saveBtn = button("Save " + schema.envFile, true, function () {
        saveBtn.disabled = true;
        var text = serializeEnv(state.answers, schema, state.unknownLines);
        Promise.resolve(save(text)).then(function (method) {
          saveBtn.disabled = false;
          if (method === "cancelled") return;
          state.saveMethod = method;
          state.step = "done";
          render();
        }, function () {
          saveBtn.disabled = false;
        });
      });
      panel.appendChild(navRow([
        button("Back", false, function () {
          if (groups.length) {
            state.groupIdx = groups.length - 1;
            state.step = "ask";
          } else {
            state.step = "mode";
          }
          render();
        }),
        saveBtn,
      ]));
      return panel;
    }

    function doneView() {
      var panel = el("section", "setup-panel");
      panel.appendChild(el("h2", "setup-h2", "Done"));
      panel.appendChild(el("p", "setup-done-message", schema.doneMessage));
      if (state.saveMethod === "download") {
        panel.appendChild(el("p", "setup-done-note",
          'Your browser downloaded the file. If it is named "env" or "env.txt" instead of ".env", ' +
          'rename it to exactly ".env" and move it into the gamentic folder (the one that contains docker-compose.yml).'));
      } else {
        panel.appendChild(el("p", "setup-done-note",
          'Saved. Make sure the file is named exactly ".env" and sits in the gamentic folder ' +
          "(the one that contains docker-compose.yml)."));
      }
      if (state.mode === "anna") {
        var m = null;
        schema.modes.forEach(function (x) { if (x.id === "anna") m = x; });
        if (m) {
          panel.appendChild(el("h3", "setup-h3", m.label));
          panel.appendChild(el("p", "setup-done-note", m.help));
        }
      }
      return panel;
    }

    function render() {
      rootEl.textContent = "";
      var header = el("header", "setup-header");
      header.appendChild(el("h1", "setup-title", "Gamentic setup"));
      rootEl.appendChild(header);
      if (state.step === "welcome") rootEl.appendChild(welcomeView());
      else if (state.step === "mode") rootEl.appendChild(modeView());
      else if (state.step === "ask") rootEl.appendChild(askView());
      else if (state.step === "review") rootEl.appendChild(reviewView());
      else rootEl.appendChild(doneView());
    }

    if (opts.envText) applyEnvText(opts.envText, opts.envName);
    render();
  }

  window.GamenticSetup = {
    parseEnv: parseEnv,
    serializeEnv: serializeEnv,
    visibleSettings: visibleSettings,
    validate: validate,
    mount: mount,
  };
})();
