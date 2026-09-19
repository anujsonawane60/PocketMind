/* The setup wizard: drive → computer → about you → model → vault → install. */

const Setup = {
  steps: ["Drive", "Your computer", "About you", "Model", "Vault", "Install"],
  draft: {
    drive: null,
    report: null,
    hardware: null,
    profile: null,
    fit: null,
    password: "",
    bundlePython: true,
    acceptedLicense: false,
  },
};

Setup.frame = (stepIndex, inner) => `
  <div class="wizard">
    ${PM.brand()}
    ${PM.progressBar(Setup.steps, stepIndex)}
    ${inner}
  </div>`;

/* ------------------------------------------------------------- 0. welcome */

Setup.welcome = () => {
  PM.render(Setup.frame(0, `
    <section class="card">
      <div class="eyebrow">Welcome</div>
      <h1>Build your private AI assistant</h1>
      <p class="intro">
        PocketMind installs a local AI model, an encrypted vault, and your own memory system onto a
        removable drive. Once it is set up, everything runs on your computer with no internet
        connection and no account.
      </p>
      <div class="notice">
        <div class="icon">✓</div>
        <div>
          <strong>Nothing is written yet</strong>
          <p>You will choose a drive, see exactly what will be installed, and confirm before anything happens.
          PocketMind never formats or deletes your files.</p>
        </div>
      </div>
      <div class="notice">
        <div class="icon">◈</div>
        <div>
          <strong>What you will need</strong>
          <p>A USB drive or portable SSD with about 8 GB free, and an internet connection for the
          one-time download. After that PocketMind works offline.</p>
        </div>
      </div>
      <footer class="actions">
        <span>Takes about 10–15 minutes, mostly downloading.</span>
        <button class="primary" id="begin">Start setup →</button>
      </footer>
    </section>`));

  PM.one("#begin").addEventListener("click", Setup.drives);
};

/* -------------------------------------------------------------- 1. drives */

Setup.drives = async () => {
  PM.render(Setup.frame(0, `
    <section class="card">
      <div class="eyebrow">Step 1 of 6</div>
      <h1>Choose your PocketMind drive</h1>
      <p class="intro">
        Pick the removable drive or portable SSD your AI will live on. Internal drives and the drive
        your computer starts from are shown but cannot be selected.
      </p>
      <div class="row-heading">
        <h2>Connected drives</h2>
        <button class="secondary" id="rescan" type="button">↻ Rescan</button>
      </div>
      <div class="option-list" id="drive-list" aria-live="polite">
        <div class="loading">Looking for drives…</div>
      </div>
      <div class="notice">
        <div class="icon">✓</div>
        <div>
          <strong>Your files are safe at this step</strong>
          <p>Choosing a drive does not format, delete, or move anything. PocketMind only ever creates
          its own folder alongside what is already there.</p>
        </div>
      </div>
      <div class="error" id="error"></div>
      <footer class="actions">
        <button class="ghost" id="back">← Back</button>
        <span id="hint">Select a drive to continue</span>
      </footer>
    </section>`));

  PM.one("#back").addEventListener("click", Setup.welcome);
  PM.one("#rescan").addEventListener("click", Setup.loadDrives);
  await Setup.loadDrives();
};

Setup.loadDrives = async () => {
  const list = PM.one("#drive-list");
  list.innerHTML = '<div class="loading">Looking for drives…</div>';
  let drives;
  try {
    drives = await PM.get("/api/setup/drives");
  } catch (error) {
    list.innerHTML = "";
    PM.setError("#error", error);
    return;
  }

  const eligible = drives.filter((drive) => drive.is_eligible);
  const rest = drives.filter((drive) => !drive.is_eligible);

  if (!eligible.length) {
    list.innerHTML = `
      <div class="empty">
        <b>No removable drive found.</b><br>
        Connect a USB drive or portable SSD, then choose Rescan.
      </div>
      ${rest.map(Setup.driveRow).join("")}`;
  } else {
    list.innerHTML = eligible.map(Setup.driveRow).join("") + rest.map(Setup.driveRow).join("");
  }

  PM.on(".option[data-drive]", "click", (event) => {
    const id = event.currentTarget.dataset.drive;
    Setup.validate(drives.find((drive) => drive.id === id));
  }, list);
};

/* Unlabelled volumes need a name that matches what they actually are. Calling
   the system disk a "removable drive" is both wrong and alarming. */
Setup.describeDrive = (drive) => {
  if (drive.label) return drive.label;
  if (drive.is_system_drive) return "System drive";
  if (drive.kind === "removable") return "Removable drive";
  if (drive.kind === "network") return "Network drive";
  if (drive.kind === "cdrom") return "Disc drive";
  if (drive.kind === "fixed") return drive.is_external ? "External drive" : "Internal drive";
  return "Drive";
};

Setup.driveRow = (drive) => {
  const badge = drive.has_pocketmind ? '<span class="tag">PocketMind installed</span>' : "";
  const busy = drive.is_eligible ? "" : ' disabled title="Cannot be used"';
  return `
    <button class="option" data-drive="${PM.esc(drive.id)}"${busy} type="button">
      <span class="radio" aria-hidden="true"></span>
      <span class="option-body">
        <span class="option-title">${PM.esc(Setup.describeDrive(drive))} (${PM.esc(drive.id)})${badge}</span>
        <span class="option-meta">${
          drive.is_eligible
            ? `${PM.esc(drive.filesystem || "Unknown format")}${drive.bus_type ? ` · ${PM.esc(drive.bus_type)}` : ""} · ${PM.bytes(drive.total_bytes)} total`
            : PM.esc(drive.ineligible_reason || "Not usable")
        }</span>
      </span>
      <span class="option-side"><b>${PM.bytes(drive.free_bytes)} free</b>${PM.bytes(drive.used_bytes)} used</span>
    </button>`;
};

/* ------------------------------------------------------------ 2. validate */

Setup.validate = async (drive) => {
  Setup.draft.drive = drive;
  PM.render(Setup.frame(0, `
    <section class="card">
      <div class="eyebrow">Step 1 of 6</div>
      <h1>Checking ${PM.esc(drive.id)}</h1>
      <p class="intro">PocketMind is writing and deleting one 8 MB test file to measure how fast this drive is.</p>
      <div class="loading">Inspecting the drive…</div>
    </section>`));

  let report;
  try {
    report = await PM.post("/api/setup/drive-report", { drive_id: drive.id });
  } catch (error) {
    PM.render(Setup.frame(0, `
      <section class="card">
        <h1>That drive could not be checked</h1>
        <div class="error">${PM.esc(error.message)}</div>
        <footer class="actions"><button class="ghost" id="back">← Choose another drive</button><span></span></footer>
      </section>`));
    PM.one("#back").addEventListener("click", Setup.drives);
    return;
  }

  Setup.draft.report = report;
  const speed = report.write_speed_mb_per_second;
  const notices = report.warnings
    .map((warning) => `
      <div class="notice warn">
        <div class="icon">!</div><div><p>${PM.esc(warning)}</p></div>
      </div>`)
    .join("");

  PM.render(Setup.frame(0, `
    <section class="card">
      <button class="back" id="back">← Choose a different drive</button>
      <div class="eyebrow">Step 1 of 6</div>
      <h1>${PM.esc(report.drive.label || `Your PocketMind drive (${report.drive.id})`)}</h1>
      <p class="intro">Here is what PocketMind found. Nothing has been changed on the drive.</p>
      <div class="spec-grid">
        <div class="spec"><span>Drive</span><b>${PM.esc(report.drive.id)}</b></div>
        <div class="spec"><span>Capacity</span><b>${PM.bytes(report.drive.total_bytes)}</b></div>
        <div class="spec"><span>Free</span><b>${PM.bytes(report.drive.free_bytes)}</b></div>
        <div class="spec"><span>Format</span><b>${PM.esc(report.drive.filesystem || "Unknown")}</b></div>
        <div class="spec"><span>Write speed</span><b>${speed ? `${speed} MB/s` : "Not measured"}</b></div>
        <div class="spec"><span>Status</span><b>${PM.esc(report.status)}</b></div>
      </div>
      ${report.has_existing_data ? `
        <div class="notice">
          <div class="icon">◈</div>
          <div>
            <strong>This drive already contains ${report.existing_entries.length} item(s)</strong>
            <p>${PM.esc(report.existing_entries.slice(0, 8).join(", "))}${report.existing_entries.length > 8 ? ", …" : ""}</p>
          </div>
        </div>` : ""}
      ${notices}
      <div class="notice">
        <div class="icon">✓</div>
        <div>
          <strong>PocketMind does not format drives</strong>
          <p>Your existing files stay exactly where they are. Everything PocketMind installs goes into a
          single folder named <b>PocketMind</b>.</p>
        </div>
      </div>
      <footer class="actions">
        <span>Selected: <b>${PM.esc(report.drive.id)}</b></span>
        <button class="primary" id="continue">Continue →</button>
      </footer>
    </section>`));

  PM.one("#back").addEventListener("click", Setup.drives);
  PM.one("#continue").addEventListener("click", Setup.hardware);
};

/* ------------------------------------------------------------ 3. hardware */

Setup.hardware = async () => {
  PM.render(Setup.frame(1, `
    <section class="card">
      <div class="eyebrow">Step 2 of 6</div>
      <h1>Looking at your computer</h1>
      <p class="intro">PocketMind checks what this machine can handle so it only suggests models that will actually run well.</p>
      <div class="loading">Reading processor, memory, and graphics…</div>
    </section>`));

  let profile;
  try {
    profile = await PM.get("/api/setup/hardware");
  } catch (error) {
    PM.toast(error.message, true);
    return;
  }
  Setup.draft.hardware = profile;
  Setup.draft.buildAnyway = Boolean(profile.app_control_blocks_engine);

  PM.render(Setup.frame(1, `
    <section class="card">
      <button class="back" id="back">← Back to drive</button>
      <div class="eyebrow">Step 2 of 6</div>
      <h1>Your computer</h1>
      <p class="intro">This is used only to pick a suitable model. None of it is sent anywhere.</p>
      <div class="spec-grid">
        <div class="spec"><span>Processor</span><b>${PM.esc(profile.cpu_name)}</b></div>
        <div class="spec"><span>Cores</span><b>${profile.physical_cores ?? "?"} physical · ${profile.logical_cores ?? "?"} logical</b></div>
        <div class="spec"><span>Memory</span><b>${PM.bytes(profile.ram_bytes)}</b></div>
        <div class="spec"><span>Graphics</span><b>${PM.esc(profile.gpu_name || "None detected")}</b></div>
        <div class="spec"><span>Graphics memory</span><b>${profile.gpu_vram_bytes ? PM.bytes(profile.gpu_vram_bytes) : "—"}${profile.vram_is_estimate && profile.gpu_vram_bytes ? " (estimated)" : ""}</b></div>
        <div class="spec"><span>System</span><b>${PM.esc(profile.operating_system)} · ${PM.esc(profile.architecture)}</b></div>
      </div>
      <div class="notice">
        <div class="icon">★</div>
        <div>
          <strong>${PM.esc(profile.performance_label)}</strong>
          <div class="stars" aria-label="${profile.performance_stars} out of 5">${PM.stars(profile.performance_stars)}</div>
          ${profile.performance_notes.map((note) => `<p>${PM.esc(note)}</p>`).join("")}
        </div>
      </div>
      ${profile.blockers.map((blocker) => `
        <div class="notice warn">
          <div class="icon">!</div>
          <div>
            <strong>This computer will not run the AI engine</strong>
            <p>${PM.esc(blocker)}</p>
            <p>You can still continue: PocketMind will prepare the drive so it works on a computer
            without Smart App Control.</p>
          </div>
        </div>`).join("")}
      <footer class="actions">
        <span>Speed depends on this computer, not the drive.</span>
        <button class="primary" id="continue">Continue →</button>
      </footer>
    </section>`));

  PM.one("#back").addEventListener("click", Setup.drives);
  PM.one("#continue").addEventListener("click", Setup.aboutYou);
};

/* ----------------------------------------------------------- 4. about you */

Setup.USE_CASES = [
  ["assistant", "Personal organisation", "Planning, notes, reminders, and reflection"],
  ["learning", "Learning", "Study material, explanations, and revision"],
  ["coding", "Programming", "Code help, debugging, and technical notes"],
  ["documents", "Private documents", "Search and ask questions about your own files"],
  ["journaling", "Journaling", "Personal writing kept entirely private"],
  ["finance", "Finance", "Records, budgets, and figures"],
];

Setup.aboutYou = () => {
  const saved = Setup.draft.profile;
  PM.render(Setup.frame(2, `
    <section class="card">
      <button class="back" id="back">← Back to your computer</button>
      <div class="eyebrow">Step 3 of 6</div>
      <h1>Tell PocketMind about yourself</h1>
      <p class="intro">
        This becomes your assistant's first memories and shapes which model is recommended.
        It is stored on your drive and nowhere else.
      </p>
      <form id="about-form">
        <label class="field">
          <span>What should PocketMind call you?</span>
          <input type="text" id="display-name" name="display_name" maxlength="80" required
                 placeholder="For example, Alex" value="${PM.esc(saved?.display_name || "")}">
        </label>

        <fieldset>
          <legend>What will you mainly use it for? Choose as many as you like.</legend>
          <div class="choice-grid">
            ${Setup.USE_CASES.map(([value, title, description]) => `
              <label class="choice">
                <input type="checkbox" name="use_cases" value="${value}"
                       ${saved?.use_cases?.includes(value) ? "checked" : ""}>
                <span><b>${title}</b><small>${description}</small></span>
              </label>`).join("")}
          </div>
        </fieldset>

        <fieldset>
          <legend>How familiar are you with local AI models?</legend>
          <div class="inline-choices">
            ${[["new", "New to this"], ["some experience", "Some experience"], ["experienced", "Experienced"]]
              .map(([value, label], index) => `
                <label><input type="radio" name="experience" value="${value}"
                  ${saved?.experience === value || (!saved && index === 0) ? "checked" : ""}> ${label}</label>`)
              .join("")}
          </div>
        </fieldset>

        <label class="choice" style="margin-bottom:18px">
          <input type="checkbox" id="bundle-python" ${Setup.draft.bundlePython ? "checked" : ""}>
          <span>
            <b>Make the drive fully self-contained</b>
            <small>Adds about 250 MB so PocketMind runs on computers that do not have Python installed.
            Recommended — this is what makes the drive truly portable.</small>
          </span>
        </label>

        <label class="choice">
          <input type="checkbox" id="network-allowed" ${saved ? (saved.network_allowed ? "checked" : "") : "checked"}>
          <span>
            <b>Allow internet during setup</b>
            <small>Used only to download the AI engine and model. Everyday chat is always offline.</small>
          </span>
        </label>

        <div class="error" id="error"></div>
        <footer class="actions">
          <span>Your answers stay on your drive.</span>
          <button class="primary" type="submit">Continue →</button>
        </footer>
      </form>
    </section>`));

  PM.one("#back").addEventListener("click", Setup.hardware);
  PM.one("#about-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const useCases = [...document.querySelectorAll('input[name="use_cases"]:checked')].map((node) => node.value);
    if (!useCases.length) {
      PM.setError("#error", { message: "Choose at least one thing you want help with." });
      return;
    }
    Setup.draft.bundlePython = PM.one("#bundle-python").checked;
    Setup.draft.profile = {
      display_name: PM.one("#display-name").value.trim(),
      use_cases: useCases,
      experience: PM.one('input[name="experience"]:checked')?.value || "new",
      network_allowed: PM.one("#network-allowed").checked,
      tone: "balanced",
    };
    Setup.models();
  });
};

/* -------------------------------------------------------------- 5. models */

Setup.models = async () => {
  PM.render(Setup.frame(3, `
    <section class="card">
      <div class="eyebrow">Step 4 of 6</div>
      <h1>Choosing a model for you</h1>
      <p class="intro">Checking which models fit ${PM.esc(Setup.draft.drive.id)} and run well on this computer.</p>
      <div class="loading">Reading the model catalogue…</div>
    </section>`));

  let result;
  try {
    result = await PM.post("/api/setup/recommendations", {
      drive_id: Setup.draft.drive.id,
      use_cases: Setup.draft.profile.use_cases,
      bundle_portable_python: Setup.draft.bundlePython,
    });
  } catch (error) {
    PM.render(Setup.frame(3, `
      <section class="card">
        <h1>Models could not be listed</h1>
        <div class="error">${PM.esc(error.message)}</div>
        <footer class="actions">
          <button class="ghost" id="back">← Back</button>
          <button class="primary" id="retry">Try again</button>
        </footer>
      </section>`));
    PM.one("#back").addEventListener("click", Setup.aboutYou);
    PM.one("#retry").addEventListener("click", Setup.models);
    return;
  }

  Setup.recommendations = result;
  const featured = [
    ["Recommended for you", result.recommended],
    ["Another good option", result.alternative],
    ["Lightest option", result.lightweight],
  ].filter(([, fit]) => fit);

  const others = result.all_models.filter(
    (fit) => !featured.some(([, chosen]) => chosen.model.id === fit.model.id));

  PM.render(Setup.frame(3, `
    <section class="card">
      <button class="back" id="back">← Back</button>
      <div class="eyebrow">Step 4 of 6</div>
      <h1>Choose your AI model</h1>
      <p class="intro">
        These are ranked for ${PM.bytes(Setup.draft.hardware.ram_bytes)} of memory,
        ${Setup.draft.hardware.gpu_name ? PM.esc(Setup.draft.hardware.gpu_name) : "no dedicated graphics"},
        and ${PM.bytes(Setup.draft.drive.free_bytes)} free on ${PM.esc(Setup.draft.drive.id)}.
      </p>
      ${result.catalog_note ? `<div class="notice warn"><div class="icon">!</div><div><p>${PM.esc(result.catalog_note)}</p></div></div>` : ""}
      ${featured.map(([label, fit]) => Setup.modelCard(fit, label)).join("")}
      ${others.length ? `
        <div class="section" style="margin-top:26px">
          <h2>All models</h2>
          ${others.map((fit) => Setup.modelCard(fit, null)).join("")}
        </div>` : ""}
      <div class="error" id="error"></div>
      <footer class="actions">
        <span>You can install more models later from Settings.</span>
        <span></span>
      </footer>
    </section>`));

  PM.one("#back").addEventListener("click", Setup.aboutYou);
  PM.on("[data-pick]", "click", (event) => {
    const id = event.currentTarget.dataset.pick;
    const fit = result.all_models.find((item) => item.model.id === id);
    Setup.draft.fit = fit;
    Setup.license(fit);
  });
};

Setup.modelCard = (fit, label) => {
  const model = fit.model;
  const blocked = fit.blockers.length > 0;
  const slow = fit.expected_speed.startsWith("Slow");
  return `
    <article class="model-card ${label === "Recommended for you" ? "recommended" : ""} ${blocked ? "blocked" : ""}">
      <div class="model-head">
        <div>
          <b>${PM.esc(model.name)}</b>
          <span class="tag ${blocked ? "muted" : ""}">${PM.esc(model.tier)}</span>
          ${label ? `<span class="tag muted">${PM.esc(label)}</span>` : ""}
          <div class="option-meta">${PM.esc(model.best_for)}</div>
        </div>
        <button class="${label === "Recommended for you" ? "primary" : "secondary"}"
                data-pick="${PM.esc(model.id)}" ${blocked ? "disabled" : ""}>
          ${blocked ? "Will not fit" : "Select"}
        </button>
      </div>
      <div class="model-facts">
        <span>Download <b>${PM.bytes(model.download_size_bytes)}</b>${model.size_is_estimate ? " (estimate)" : ""}</span>
        <span>Memory needed <b>${PM.bytes(model.min_ram_bytes)}</b></span>
        <span>Context <b>${(model.context_length / 1024).toFixed(0)}K</b></span>
        <span>Speed <b>${PM.esc(fit.expected_speed.split("—")[0].trim())}</b></span>
        <span>Licence <b>${PM.esc(model.license)}</b></span>
      </div>
      <ul class="reasons">${fit.reasons.map((reason) => `<li>${PM.esc(reason)}</li>`).join("")}</ul>
      ${slow && !blocked ? `<ul class="reasons cautions"><li>${PM.esc(fit.expected_speed)}. Replies will
        arrive slowly on this computer — a smaller model will feel much more responsive.</li></ul>` : ""}
      ${fit.blockers.length ? `<ul class="reasons blockers">${fit.blockers.map((b) => `<li>${PM.esc(b)}</li>`).join("")}</ul>` : ""}
    </article>`;
};

Setup.license = (fit) => {
  const model = fit.model;
  PM.render(Setup.frame(3, `
    <section class="card">
      <button class="back" id="back">← Choose a different model</button>
      <div class="eyebrow">Model licence</div>
      <h1>${PM.esc(model.name)}</h1>
      <p class="intro">
        PocketMind is open source, but each model carries its own licence from whoever published it.
        You need to accept this one before it is downloaded.
      </p>
      <div class="spec-grid">
        <div class="spec"><span>Licence</span><b>${PM.esc(model.license)}</b></div>
        <div class="spec"><span>Publisher</span><b>${PM.esc(model.family)}</b></div>
        <div class="spec"><span>Download size</span><b>${PM.bytes(model.download_size_bytes)}</b></div>
      </div>
      ${model.license_url ? `<p class="intro" style="margin-top:16px">
        Full terms: <a href="${PM.esc(model.license_url)}" target="_blank" rel="noreferrer">${PM.esc(model.license_url)}</a>
      </p>` : ""}
      <label class="choice" style="margin-top:18px">
        <input type="checkbox" id="accept">
        <span><b>I accept the ${PM.esc(model.license)} terms for this model</b>
        <small>PocketMind's own MIT licence does not cover model weights.</small></span>
      </label>
      <footer class="actions">
        <span></span>
        <button class="primary" id="continue" disabled>Continue →</button>
      </footer>
    </section>`));

  PM.one("#back").addEventListener("click", Setup.models);
  PM.one("#accept").addEventListener("change", (event) => {
    Setup.draft.acceptedLicense = event.target.checked;
    PM.one("#continue").disabled = !event.target.checked;
  });
  PM.one("#continue").addEventListener("click", Setup.vault);
};

/* --------------------------------------------------------------- 6. vault */

Setup.strength = (password) => {
  const suggestions = [];
  let score = 0;
  if (password.length >= 12) score += 1;
  if (password.length >= 16) score += 1; else suggestions.push("Longer is stronger — aim for 16 characters or a short sentence.");
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score += 1; else suggestions.push("Mix upper and lower case.");
  if (/\d/.test(password)) score += 1; else suggestions.push("Add a number.");
  if (/[^A-Za-z0-9]/.test(password)) score += 1; else suggestions.push("Add a symbol or a space.");
  const labels = ["Very weak", "Very weak", "Weak", "Fair", "Strong", "Very strong"];
  return { score, label: labels[score], suggestions };
};

Setup.vault = () => {
  PM.render(Setup.frame(4, `
    <section class="card">
      <button class="back" id="back">← Back to models</button>
      <div class="eyebrow">Step 5 of 6</div>
      <h1>Create your master password</h1>
      <p class="intro">
        This password encrypts your private vault — passwords, API keys, recovery codes, and secure notes.
        It is never stored anywhere, so PocketMind cannot recover it for you.
      </p>
      <label class="field">
        <span>Master password</span>
        <input type="password" id="password" autocomplete="new-password" minlength="12" placeholder="At least 12 characters">
        <div class="strength"><div class="bar"><i id="strength-bar"></i></div><span id="strength-label">—</span></div>
        <small id="strength-hint">A short sentence you will remember works better than a short complicated word.</small>
      </label>
      <label class="field">
        <span>Confirm password</span>
        <input type="password" id="confirm" autocomplete="new-password" placeholder="Type it again">
      </label>
      <div class="notice warn">
        <div class="icon">!</div>
        <div>
          <strong>There is no password reset</strong>
          <p>Your vault is encrypted with a key derived from this password using Argon2id. If you forget it,
          the contents cannot be recovered by anyone, including you. Write it down and keep it somewhere safe.</p>
        </div>
      </div>
      <div class="error" id="error"></div>
      <footer class="actions">
        <span>Your chat history and memories are separate from the vault.</span>
        <button class="primary" id="continue" disabled>Create and install →</button>
      </footer>
    </section>`));

  const password = PM.one("#password");
  const confirm = PM.one("#confirm");
  const button = PM.one("#continue");

  const check = () => {
    const strength = Setup.strength(password.value);
    PM.one("#strength-bar").style.width = `${(strength.score / 5) * 100}%`;
    PM.one("#strength-label").textContent = password.value ? strength.label : "—";
    PM.one("#strength-hint").textContent =
      strength.suggestions[0] || "Strong enough. Make sure you can remember it.";
    const matches = password.value.length >= 12 && password.value === confirm.value;
    const strongEnough = strength.score >= 3;
    button.disabled = !(matches && strongEnough);
    PM.setError("#error",
      confirm.value && password.value !== confirm.value ? { message: "The two passwords do not match." } : null);
  };

  password.addEventListener("input", check);
  confirm.addEventListener("input", check);
  PM.one("#back").addEventListener("click", Setup.models);
  button.addEventListener("click", () => {
    Setup.draft.password = password.value;
    Setup.install();
  });
};

/* ------------------------------------------------------------- 7. install */

Setup.install = async () => {
  PM.render(Setup.frame(5, `
    <section class="card">
      <div class="eyebrow">Step 6 of 6</div>
      <h1>Installing PocketMind</h1>
      <p class="intro" id="install-message">Getting started…</p>
      <div class="bar-label"><span id="install-current">Preparing</span><span id="install-percent">0%</span></div>
      <div class="bar-outer"><i id="install-bar"></i></div>
      <div class="steps" id="install-steps" style="margin-top:20px"></div>
      <div class="error" id="error"></div>
      <footer class="actions">
        <span>You can leave this running. Downloads resume if the connection drops.</span>
        <button class="ghost" id="cancel">Stop</button>
      </footer>
    </section>`));

  PM.one("#cancel").addEventListener("click", async () => {
    if (!PM.confirmAction("Stop the installation? Your progress is saved and you can resume.")) return;
    try { await PM.post("/api/setup/install/cancel"); } catch (error) { PM.toast(error.message, true); }
  });

  try {
    await PM.post("/api/setup/install", Setup.request());
  } catch (error) {
    PM.setError("#error", error);
    Setup.showRetry();
    return;
  }
  Setup.poll();
};

Setup.request = () => ({
  drive_id: Setup.draft.drive.id,
  model_id: Setup.draft.fit.model.id,
  profile: Setup.draft.profile,
  vault_password: Setup.draft.password,
  bundle_portable_python: Setup.draft.bundlePython,
  accept_model_license: Setup.draft.acceptedLicense,
  build_anyway: Boolean(Setup.draft.buildAnyway),
});

Setup.STEP_MARKS = {
  pending: "○", running: "◌", completed: "✓", skipped: "–", failed: "✕",
};

Setup.poll = () => {
  clearInterval(Setup.timer);
  Setup.timer = setInterval(async () => {
    let status;
    try {
      status = await PM.get("/api/setup/install/status");
    } catch {
      return; // transient; keep polling
    }
    Setup.paint(status);
    if (["completed", "failed", "cancelled"].includes(status.state)) {
      clearInterval(Setup.timer);
      if (status.state === "completed") Setup.finish(status);
      else Setup.showRetry(status);
    }
  }, 900);
};

Setup.paint = (status) => {
  const percent = Math.round(status.overall_progress * 100);
  const bar = PM.one("#install-bar");
  if (!bar) return;
  bar.style.width = `${percent}%`;
  PM.one("#install-percent").textContent = `${percent}%`;
  PM.one("#install-current").textContent = status.current_step || status.message || "Working";
  PM.one("#install-message").textContent = status.message || "";
  PM.one("#install-steps").innerHTML = status.steps
    .map((step) => `
      <div class="step ${step.status}">
        <span class="step-mark">${Setup.STEP_MARKS[step.status] || "○"}</span>
        <span class="step-body">
          <b>${PM.esc(step.title)}</b>
          ${step.detail ? `<small>${PM.esc(step.detail)}</small>` : ""}
          ${step.status === "running" && step.progress > 0
            ? `<span class="bar-outer" style="margin-top:8px"><i style="width:${Math.round(step.progress * 100)}%"></i></span>`
            : ""}
        </span>
      </div>`)
    .join("");
};

Setup.showRetry = (status) => {
  const error = PM.one("#error");
  if (error && status) {
    error.textContent = status.error ? `${status.error} ${status.recovery_hint || ""}` : status.message;
  }
  const footer = PM.one(".actions");
  if (!footer) return;
  footer.innerHTML = `
    <button class="ghost" id="restart">Start over</button>
    <button class="primary" id="resume">Resume installation</button>`;
  PM.one("#restart").addEventListener("click", Setup.drives);
  PM.one("#resume").addEventListener("click", Setup.install);
};

/* ---------------------------------------------------------------- 8. done */

Setup.finish = async (status) => {
  clearInterval(Setup.timer);
  try {
    await PM.post("/api/setup/open", { root: status.install_path });
    const unlocked = await PM.post("/api/vault/unlock", { password: Setup.draft.password });
    PM.vaultToken = unlocked.session_token;
  } catch (error) {
    PM.toast(`Installed, but could not open the drive automatically: ${error.message}`, true);
  }
  Setup.draft.password = "";

  const name = Setup.draft.profile.display_name;
  PM.render(Setup.frame(5, `
    <section class="card">
      <div class="eyebrow">All done</div>
      <h1>PocketMind is ready, ${PM.esc(name)}</h1>
      <p class="intro">Your private assistant now lives on your drive and runs without an internet connection.</p>
      <div class="spec-grid">
        <div class="spec"><span>Installed to</span><b>${PM.esc(status.install_path || "")}</b></div>
        <div class="spec"><span>Model</span><b>${PM.esc(Setup.draft.fit.model.name)}</b></div>
        <div class="spec"><span>Internet required</span><b>No</b></div>
        <div class="spec"><span>Your data</span><b>Stored on this drive only</b></div>
      </div>
      <div class="notice">
        <div class="icon">◈</div>
        <div>
          <strong>Next time, start from the drive</strong>
          <p>Open the drive on any Windows computer and run <b>START_POCKETMIND.cmd</b>.
          PocketMind opens straight into your chat.</p>
        </div>
      </div>
      <div class="notice warn">
        <div class="icon">!</div>
        <div>
          <strong>Before you unplug</strong>
          <p>Use <b>Eject drive</b> in Settings so the model and database close cleanly.</p>
        </div>
      </div>
      <footer class="actions">
        <span>Your vault is unlocked for this session.</span>
        <button class="primary" id="launch">Open PocketMind →</button>
      </footer>
    </section>`));

  PM.one("#launch").addEventListener("click", () => PM.boot({ showTutorial: true }));
};
