(function () {
  const root = document.querySelector('[data-control-tower="1"]');
  const changelistSearchInput = document.querySelector("#changelist-search #searchbar");

  const isTypingContext = (target) =>
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement ||
    target?.isContentEditable;

  const registerSlashFocusShortcut = (input) => {
    if (!input) {
      return;
    }
    document.addEventListener("keydown", (event) => {
      if (event.key === "/" && !event.metaKey && !event.ctrlKey && !event.altKey && !isTypingContext(event.target)) {
        event.preventDefault();
        input.focus();
        input.select();
      }
    });
  };

  registerSlashFocusShortcut(changelistSearchInput);

  if (!root) {
    return;
  }

  const metricsUrl = root.getAttribute("data-metrics-url");
  if (!metricsUrl) {
    return;
  }

  const refreshMs = Number.parseInt(root.getAttribute("data-refresh-ms") || "20000", 10);
  const connectionNode = root.querySelector("[data-connection-state]");
  const generatedAtNode = root.querySelector("[data-generated-at]");
  const moduleSearchInput = root.querySelector("[data-module-search-input]");
  const moduleSearchMeta = root.querySelector("[data-module-search-meta]");
  const moduleSearchEmpty = root.querySelector("[data-module-search-empty]");
  const moduleCards = Array.from(root.querySelectorAll("[data-module-card]"));

  const escapeHtml = (value) =>
    String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");

  const setConnectionState = (state, text) => {
    if (!connectionNode) {
      return;
    }
    connectionNode.setAttribute("data-connection-state", state);
    connectionNode.textContent = text;
  };

  const normalize = (value) => String(value || "").trim().toLowerCase();

  const applyModuleSearch = (queryText) => {
    if (!moduleCards.length) {
      return;
    }
    const query = normalize(queryText);
    let visibleCards = 0;

    moduleCards.forEach((card) => {
      const titleText = normalize(card.querySelector("h3")?.textContent);
      const modelRows = Array.from(card.querySelectorAll("[data-model-row]"));
      const titleMatches = query.length > 0 && titleText.includes(query);
      let matchingRows = 0;

      modelRows.forEach((row) => {
        const rowMatches = query.length === 0 || titleMatches || normalize(row.textContent).includes(query);
        row.hidden = !rowMatches;
        if (rowMatches) {
          matchingRows += 1;
        }
      });

      const cardVisible = matchingRows > 0 || titleMatches || query.length === 0;
      card.hidden = !cardVisible;
      if (cardVisible) {
        visibleCards += 1;
      }
    });

    if (moduleSearchMeta) {
      if (query.length === 0) {
        moduleSearchMeta.textContent = `Showing all modules (${visibleCards}).`;
      } else {
        moduleSearchMeta.textContent = `${visibleCards} module${
          visibleCards === 1 ? "" : "s"
        } matched "${query}".`;
      }
    }

    if (moduleSearchEmpty) {
      moduleSearchEmpty.hidden = visibleCards > 0;
    }
  };

  if (moduleSearchInput) {
    moduleSearchInput.addEventListener("input", (event) => {
      applyModuleSearch(event.target.value);
    });

    registerSlashFocusShortcut(moduleSearchInput);
    applyModuleSearch(moduleSearchInput.value);
  }

  const updateMetrics = (metrics) => {
    Object.entries(metrics || {}).forEach(([key, value]) => {
      root.querySelectorAll(`[data-metric-key="${key}"]`).forEach((node) => {
        node.textContent = String(value);
      });
    });
  };

  const renderQueueCards = (cards, metrics) => {
    const container = root.querySelector('[data-render-target="queue_cards"]');
    if (!container || !Array.isArray(cards)) {
      return;
    }
    container.innerHTML = cards
      .map((card) => {
        const value = metrics?.[card.metric_key] ?? 0;
        return `
          <article class="ops-queue-card tone-${escapeHtml(card.tone || "ok")}">
            <h3>${escapeHtml(card.title)}</h3>
            <p class="ops-queue-card__value">${escapeHtml(value)}</p>
            <p>${escapeHtml(card.detail || "")}</p>
            <a href="${escapeHtml(card.href || "#")}">Open</a>
          </article>
        `;
      })
      .join("");
  };

  const renderAlerts = (alerts) => {
    const container = root.querySelector('[data-render-target="alerts"]');
    if (!container || !Array.isArray(alerts)) {
      return;
    }
    container.innerHTML = alerts
      .map(
        (alert) => `
          <li class="tone-${escapeHtml(alert.tone || "ok")}">
            <a href="${escapeHtml(alert.href || "#")}">
              <strong>${escapeHtml(alert.title)}</strong>
              <span>${escapeHtml(alert.detail || "")}</span>
            </a>
          </li>
        `,
      )
      .join("");
  };

  const renderFeed = (target, rows, emptyLabel) => {
    const container = root.querySelector(`[data-render-target="${target}"]`);
    if (!container || !Array.isArray(rows)) {
      return;
    }
    if (!rows.length) {
      container.innerHTML = `<li class="is-empty">${escapeHtml(emptyLabel)}</li>`;
      return;
    }
    container.innerHTML = rows
      .map(
        (row) => `
          <li class="tone-${escapeHtml(row.tone || "ok")}">
            <a href="${escapeHtml(row.href || "#")}">
              <strong>${escapeHtml(row.title || "")}</strong>
              <span>${escapeHtml(row.subtitle || "")}</span>
              <time>${escapeHtml(row.timestamp || "")}</time>
            </a>
          </li>
        `,
      )
      .join("");
  };

  const renderSnapshot = (snapshot) => {
    if (!snapshot) {
      return;
    }
    updateMetrics(snapshot.metric_values);
    renderQueueCards(snapshot.queue_cards, snapshot.metric_values);
    renderAlerts(snapshot.alerts);
    renderFeed("recent_failed_runs", snapshot.recent?.failed_runs || [], "No failed runs yet.");
    renderFeed(
      "recent_expiring_approvals",
      snapshot.recent?.expiring_approvals || [],
      "No pending approvals with expiry.",
    );
    renderFeed(
      "recent_failed_intents",
      snapshot.recent?.failed_intents || [],
      "No failed intents logged.",
    );
    renderFeed(
      "recent_audit_highlights",
      snapshot.recent?.audit_highlights || [],
      "No warning/error audit events.",
    );
    if (generatedAtNode && snapshot.generated_at_label) {
      generatedAtNode.textContent = snapshot.generated_at_label;
    }
  };

  let inFlight = false;
  const pollSnapshot = async () => {
    if (inFlight) {
      return;
    }
    inFlight = true;
    setConnectionState("syncing", "Syncing");
    try {
      const response = await fetch(metricsUrl, {
        headers: {
          Accept: "application/json",
        },
        credentials: "same-origin",
      });
      if (!response.ok) {
        throw new Error(`Unexpected status: ${response.status}`);
      }
      const payload = await response.json();
      renderSnapshot(payload);
      setConnectionState("online", "Live sync active");
    } catch (error) {
      setConnectionState("offline", "Refresh delayed");
      window.console.error("Control tower refresh failed", error);
    } finally {
      inFlight = false;
    }
  };

  pollSnapshot();
  window.setInterval(pollSnapshot, Number.isFinite(refreshMs) ? refreshMs : 20000);
})();
