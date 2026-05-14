let stationsTable = null;

document.addEventListener("DOMContentLoaded", function () {

  // =========================
  // INIT DATA TABLE
  // =========================
  const tableEl = document.getElementById("dataTable");

  if (tableEl) {
    stationsTable = $('#dataTable').DataTable({
      paging: false,
      searching: false,
      info: false,
      destroy: true
    });
  }

  // =========================
  // ELEMENTS
  // =========================
  const btnStart = document.getElementById("btn-start");
  const btnStop = document.getElementById("btn-stop");
  const powerSelect = document.getElementById("power-select");
  const selectAll = document.getElementById("select-all");
  const messageContainer = document.getElementById("message-container");

  // =========================
  // HELPERS
  // =========================
  function getCheckboxes() {
    return document.querySelectorAll("input[name='station_ids']");
  }

  function getSelectedStations() {
    return Array.from(getCheckboxes())
      .filter(cb => cb.checked)
      .map(cb => cb.value);
  }

  function getCSRFToken() {
    return document.querySelector('[name=csrfmiddlewaretoken]')?.value;
  }

  // =========================
  // UI: MESSAGE
  // =========================
  function showMessage(message, type = "info") {
    if (!messageContainer) return;

    const map = {
      success: "alert-success",
      error: "alert-danger",
      warning: "alert-warning",
      info: "alert-info"
    };

    messageContainer.innerHTML = `
      <div class="alert ${map[type] || "alert-info"} alert-dismissible fade show">
        ${message}
        <button type="button" class="close" data-dismiss="alert">
          <span>&times;</span>
        </button>
      </div>
    `;

    setTimeout(() => {
      messageContainer.querySelector(".alert")?.remove();
    }, 5000);
  }

  // =========================
  // STATE MANAGEMENT
  // =========================
  function updateActionButtons() {
    const anyChecked = getSelectedStations().length > 0;

    if (btnStart) btnStart.disabled = !anyChecked;
    if (btnStop) btnStop.disabled = !anyChecked;
    if (powerSelect) powerSelect.disabled = !anyChecked;
  }

  function syncSelectAllState() {
    if (!selectAll) return;

    const checkboxes = getCheckboxes();
    const total = checkboxes.length;
    const checked = Array.from(checkboxes).filter(cb => cb.checked).length;

    if (checked === 0) {
      selectAll.checked = false;
      selectAll.indeterminate = false;
    } else if (checked === total) {
      selectAll.checked = true;
      selectAll.indeterminate = false;
    } else {
      selectAll.checked = false;
      selectAll.indeterminate = true;
    }
  }

  // =========================
  // EVENTS (DELEGATED)
  // =========================
  document.addEventListener("change", function (e) {
    if (e.target && e.target.name === "station_ids") {
      updateActionButtons();
      syncSelectAllState();
    }
  });

  if (selectAll) {
    selectAll.addEventListener("change", function () {
      const checkboxes = getCheckboxes();
      checkboxes.forEach(cb => {
        cb.checked = selectAll.checked;
      });

      updateActionButtons();
      syncSelectAllState();
    });
  }

  // =========================
  // COMMAND SENDING
  // =========================
  function sendCommand(action, extraData = {}) {

    const selectedStations = getSelectedStations();

    if (selectedStations.length === 0) {
      showMessage("Please select at least one station.", "warning");
      return;
    }

    const formData = new FormData();
    formData.append("csrfmiddlewaretoken", getCSRFToken());
    formData.append("action", action);

    selectedStations.forEach(id => {
      formData.append("station_ids", id);
    });

    Object.entries(extraData).forEach(([key, value]) => {
      if (value !== null && value !== undefined) {
        formData.append(key, value);
      }
    });

    showMessage(`Sending ${action} command...`, "info");

    fetch(window.location.pathname, {
      method: "POST",
      body: formData,
      headers: {
        "X-Requested-With": "XMLHttpRequest"
      }
    })
      .then(async r => {
        const text = await r.text();
        try {
          return JSON.parse(text);
        } catch {
          throw new Error(text);
        }
      })
      .then(data => {
        showMessage(
          data.message || (data.success ? "Success" : "Error"),
          data.success ? "success" : "error"
        );
      })
      .catch(() => {
        showMessage("Request failed", "error");
      });
  }

  // =========================
  // BUTTONS
  // =========================
  if (btnStart) {
    btnStart.addEventListener("click", function (e) {
      e.preventDefault();
      sendCommand("start", {
        power: powerSelect ? powerSelect.value : null
      });
    });
  }

  if (btnStop) {
    btnStop.addEventListener("click", function (e) {
      e.preventDefault();
      sendCommand("stop");
    });
  }

  // =========================
  // WEBSOCKET
  // =========================
  function updateConnectionStatus(connected) {
    const dot = document.getElementById("ws-status-dot");
    const text = document.getElementById("ws-status-text");

    if (!dot || !text) return;

    dot.className = connected
      ? "status-dot bg-success mr-2"
      : "status-dot bg-danger mr-2";

    text.textContent = connected
      ? "Live updates active"
      : "Reconnecting...";
  }

  function updateVehicleSoc(id, soc) {
    const cell = document.getElementById(`soc-${id}`);
    if (!cell) return;

    cell.innerHTML = soc !== null && soc !== undefined
      ? `${Number(soc).toFixed(2)} %`
      : "--";
  }

  function updatePowerState(id, state = {}) {
    const req = document.getElementById(`requested-power-${id}`);
    const mode = document.getElementById(`requested-power-mode-${id}`);
    const act = document.getElementById(`actual-power-${id}`);
    const ems = document.getElementById(`ems-limit-${id}`);

    if (req && req.firstElementChild) {
      req.firstElementChild.textContent = state.requested_power_display || "--";
    }

    if (mode) {
      mode.textContent = state.requested_power_mode || "--";
    }

    if (act && act.firstElementChild) {
      act.firstElementChild.textContent = state.actual_power_kw
        ? `${Number(state.actual_power_kw).toFixed(2)} kW`
        : "--";
    }

    if (ems) {
      ems.textContent = state.ems_limit_kw
        ? `EMS ${Number(state.ems_limit_kw).toFixed(2)} kW`
        : "EMS --";
    }
  }

  function connectWebSocket() {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${window.location.host}/ws/stations/status/`);

    ws.onopen = () => updateConnectionStatus(true);
    ws.onclose = () => updateConnectionStatus(false);
    ws.onerror = () => updateConnectionStatus(false);

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        if (data.type === "soc_update") {
          updateVehicleSoc(data.station_id, data.soc_percentage);
        }

        if (data.type === "station_power_update") {
          updatePowerState(data.station_id, data);
        }

        if (data.status) {
          const cell = document.getElementById(`status-${data.station_id}`);
          if (cell) {
            cell.innerHTML = `<span class="badge badge-success">${data.status}</span>`;
          }
        }

        if (data.message) {
          showMessage(data.message, data.message_type || "info");
        }

      } catch (e) {
        console.error("WS error:", e);
      }
    };
  }

  // =========================
  // INIT
  // =========================
  updateActionButtons();
  syncSelectAllState();
  connectWebSocket();
});