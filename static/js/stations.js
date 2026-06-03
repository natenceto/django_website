// Global reference to DataTable for WebSocket updates
var stationsTable = null;

document.addEventListener("DOMContentLoaded", function () {
  if (window.$ && $('#dataTable').length) {
    stationsTable = $('#dataTable').DataTable({
      paging: false,
      searching: false,
      info: false
    });
  }

  const checkboxes = document.querySelectorAll("input[name='station_ids']");
  const btnStart = document.getElementById("btn-start");
  const btnStop = document.getElementById("btn-stop");
  const powerSelect = document.getElementById("power-select");
  const selectAll = document.getElementById("select-all");

  function updateActionButtons() {
    const anyChecked = Array.from(checkboxes).some(cb => cb.checked);
    if (btnStart) btnStart.disabled = !anyChecked;
    if (btnStop) btnStop.disabled = !anyChecked;
    if (powerSelect) powerSelect.disabled = !anyChecked;
  }

  checkboxes.forEach(cb => cb.addEventListener("change", updateActionButtons));

  if (selectAll) {
    selectAll.addEventListener("change", () => {
      const checked = selectAll.checked;
      checkboxes.forEach(cb => cb.checked = checked);
      updateActionButtons();
    });
  }

  function getCSRFToken() {
    return document.querySelector('[name=csrfmiddlewaretoken]').value;
  }

  function showMessage(message, type = 'info') {
    const alertClass = {
      'success': 'alert-success',
      'error': 'alert-danger',
      'warning': 'alert-warning',
      'info': 'alert-info'
    }[type] || 'alert-info';

    const alertHtml = `
      <div class="alert ${alertClass} alert-dismissible fade show" role="alert">
        ${message}
        <button type="button" class="close" data-dismiss="alert">
          <span>&times;</span>
        </button>
      </div>
    `;

    const messageContainer = document.getElementById('message-container');
    if (!messageContainer) {
      console.error('Message container not found');
      return;
    }

    const existingAlerts = messageContainer.querySelectorAll('.alert');
    existingAlerts.forEach(alert => alert.remove());
    messageContainer.innerHTML = alertHtml;

    setTimeout(() => {
      const alert = messageContainer.querySelector('.alert');
      if (alert) alert.remove();
    }, 5000);
  }

  function sendCommand(action, extraData = {}) {
    const selectedStations = Array.from(checkboxes)
      .filter(cb => cb.checked)
      .map(cb => cb.value);

    if (selectedStations.length === 0) {
      showMessage('Please select at least one station.', 'warning');
      return;
    }

    const formData = new FormData();
    formData.append('csrfmiddlewaretoken', getCSRFToken());
    formData.append('action', action);
    selectedStations.forEach(id => formData.append('station_ids', id));

    Object.keys(extraData).forEach(key => {
      formData.append(key, extraData[key]);
    });

    const actionText = action.charAt(0).toUpperCase() + action.slice(1);
    showMessage(`Sending ${actionText} command...`, 'info');

    fetch(window.location.pathname, {
      method: 'POST',
      body: formData,
      headers: {
        'X-Requested-With': 'XMLHttpRequest'
      }
    })
      .then(response => response.json())
      .then(data => {
        if (data.success) {
          showMessage(data.message || `${actionText} command completed.`, 'success');
        } else {
          showMessage(data.message || `${actionText} command failed.`, 'error');
        }
      })
      .catch(error => {
        console.error('Error:', error);
        showMessage(`Error sending ${actionText} command.`, 'error');
      });
  }

  if (btnStart) {
    btnStart.addEventListener('click', (e) => {
      e.preventDefault();
      const powerValue = powerSelect ? powerSelect.value : null;
      sendCommand('start', { power: powerValue });
    });
  }

  if (btnStop) {
    btnStop.addEventListener('click', (e) => {
      e.preventDefault();
      sendCommand('stop');
    });
  }

  let statusSocket = null;
  const stationRuntime = new Map();
  const summaryRuntime = {
    vehicleSoc: null,
    actualPowerKw: null,
    batteryCapacityKwh: null,
  };
  
  // Initialize dashboard metrics: count actual charging sessions from table
  function initializeDashboardMetrics() {
    const totalStations = parseInt(document.getElementById('metric-total')?.textContent) || checkboxes.length;
    const onlineStations = parseInt(document.getElementById('metric-online')?.textContent) || 0;
    const energyToday = parseFloat(document.getElementById('metric-energy')?.textContent) || 0;
    
    // Count actually charging stations from table
    let activeSessions = 0;
    const tableBody = document.getElementById('stations-table');
    if (tableBody) {
      const rows = tableBody.querySelectorAll('tr');
      rows.forEach(row => {
        const connectorCell = row.querySelector('[id^="connector-status-"]');
        if (connectorCell && connectorCell.textContent.includes('Charging')) {
          activeSessions++;
        }
      });
    }
    
    return {
      totalStations,
      onlineStations,
      activeSessions,
      energyToday
    };
  }
  
  let dashboardMetrics = initializeDashboardMetrics();

  function getStationRuntime(stationId) {
    const normalizedStationId = Number(stationId);
    if (!stationRuntime.has(normalizedStationId)) {
      stationRuntime.set(normalizedStationId, {
        rawConnectorStatus: null,
        renderedConnectorStatus: null,
        actualPowerKw: null,
        energyKwh: null,
      });
    }
    return stationRuntime.get(normalizedStationId);
  }

  function parseNumericValue(value) {
    const numericValue = Number(value);
    return Number.isFinite(numericValue) ? numericValue : null;
  }

  function hasActiveSessionSignal(stationId) {
    const runtime = getStationRuntime(stationId);
    return (runtime.renderedConnectorStatus === 'charging')
      || (runtime.actualPowerKw !== null && runtime.actualPowerKw > 0)
      || (runtime.energyKwh !== null && runtime.energyKwh > 0);
  }

  function normalizeConnectorStatusForDisplay(stationId, connectorStatus) {
    if (!connectorStatus) {
      return connectorStatus;
    }

    const normalizedStatus = String(connectorStatus).toLowerCase();
    if ((normalizedStatus === 'preparing' || normalizedStatus === 'finishing') && hasActiveSessionSignal(stationId)) {
      return 'charging';
    }

    return normalizedStatus;
  }

  function updateConnectionStatus(connected) {
    const dot = document.getElementById('ws-status-dot');
    const text = document.getElementById('ws-status-text');
    const lastUpdate = document.getElementById('last-update');

    if (dot && text) {
      if (connected) {
        dot.className = 'status-dot bg-success mr-2';
        dot.style.cssText = 'width: 10px; height: 10px; border-radius: 50%; display: inline-block; animation: pulse 2s infinite;';
        text.textContent = 'Live updates active';
        text.className = 'text-success';
      } else {
        dot.className = 'status-dot bg-danger mr-2';
        dot.style.cssText = 'width: 10px; height: 10px; border-radius: 50%; display: inline-block;';
        text.textContent = 'Reconnecting...';
        text.className = 'text-danger';
      }
    }
    if (lastUpdate && connected) {
      lastUpdate.textContent = 'Last update: ' + new Date().toLocaleTimeString();
    }
  }

  function updateStationStatusBadge(stationId, status) {
    const statusCell = document.getElementById(`status-${stationId}`);
    if (statusCell) {
      let statusClass = 'badge-secondary';
      let statusText = status;

      if (status === 'active') {
        statusClass = 'badge-success';
        statusText = 'Active';
      } else if (status === 'inactive') {
        statusClass = 'badge-secondary';
        statusText = 'Inactive';
      } else if (status === 'maintenance') {
        statusClass = 'badge-warning';
        statusText = 'Maintenance';
      }

      statusCell.innerHTML = `<span class="badge ${statusClass}">${statusText}</span>`;
    }
  }

  function updateSessionStatusBadge(statusLabel) {
    const badge = document.getElementById('metric-session-status');
    if (!badge) {
      return;
    }

    let badgeClass = 'badge badge-light';
    const normalized = String(statusLabel || '').toLowerCase();
    if (normalized.includes('active') || normalized.includes('charging')) {
      badgeClass = 'badge badge-success';
    } else if (normalized.includes('preparing') || normalized.includes('finishing')) {
      badgeClass = 'badge badge-info';
    } else if (normalized.includes('suspended')) {
      badgeClass = 'badge badge-warning';
    } else if (normalized.includes('completed') || normalized.includes('available')) {
      badgeClass = 'badge badge-secondary';
    } else if (normalized.includes('offline') || normalized.includes('inactive')) {
      badgeClass = 'badge badge-dark';
    } else if (normalized.includes('maintenance')) {
      badgeClass = 'badge badge-warning';
    }

    badge.className = badgeClass;
    badge.textContent = statusLabel;
  }

  function syncActiveSessions() {
    // Count actual charging stations from table and update dashboard
    let activeSessions = 0;
    const tableBody = document.getElementById('stations-table');
    if (tableBody) {
      const rows = tableBody.querySelectorAll('tr');
      rows.forEach(row => {
        const connectorCell = row.querySelector('[id^="connector-status-"]');
        if (connectorCell && connectorCell.textContent.includes('Charging')) {
          activeSessions++;
        }
      });
    }
    
    // Update metrics if changed
    if (dashboardMetrics.activeSessions !== activeSessions) {
      dashboardMetrics.activeSessions = activeSessions;
      updateDashboardCard('metric-sessions', activeSessions);
    }
  }

  function syncOnlineStations() {
    let onlineStations = 0;
    const tableBody = document.getElementById('stations-table');
    if (tableBody) {
      const rows = tableBody.querySelectorAll('tr');
      rows.forEach(row => {
        const statusCell = row.querySelector('[id^="status-"]');
        if (statusCell && statusCell.textContent.includes('Active')) {
          onlineStations++;
        }
      });
    }

    const totalStations = Number(dashboardMetrics.totalStations) || 0;
    if (totalStations > 0) {
      onlineStations = Math.min(onlineStations, totalStations);
    }

    if (dashboardMetrics.onlineStations !== onlineStations) {
      dashboardMetrics.onlineStations = onlineStations;
      updateDashboardCard('metric-online', onlineStations);
    }
  }

  function updateDashboardCard(elementId, value, animate = true) {
    const element = document.getElementById(elementId);
    if (!element) {
      return;
    }

    if (animate) {
      element.style.transition = 'transform 0.3s ease';
      element.style.transform = 'scale(1.1)';
      setTimeout(() => {
        element.textContent = value;
        element.style.transform = 'scale(1)';
      }, 150);
      return;
    }

    element.textContent = value;
  }

  function formatSocValue(socPercentage) {
    const numericSoc = Number(socPercentage);
    if (Number.isNaN(numericSoc)) {
      return '--';
    }

    if (Number.isInteger(numericSoc)) {
      return `${numericSoc.toFixed(0)} %`;
    }

    return `${numericSoc.toFixed(2)} %`;
  }

  function formatEtaDuration(hoursRemaining) {
    if (!Number.isFinite(hoursRemaining) || hoursRemaining < 0) {
      return '--';
    }

    const minutesTotal = Math.max(1, Math.round(hoursRemaining * 60));
    const hours = Math.floor(minutesTotal / 60);
    const minutes = minutesTotal % 60;

    if (hours > 0 && minutes > 0) {
      return `${hours}h ${minutes}m`;
    }
    if (hours > 0) {
      return `${hours}h`;
    }
    return `${minutes}m`;
  }

  function updateEtaReason(reasonText) {
    const etaReasonElement = document.getElementById('metric-eta-reason');
    if (!etaReasonElement) {
      return;
    }

    if (reasonText) {
      etaReasonElement.textContent = `ETA unavailable: ${reasonText}`;
      etaReasonElement.title = reasonText;
      etaReasonElement.style.visibility = 'visible';
      return;
    }

    etaReasonElement.textContent = '';
    etaReasonElement.removeAttribute('title');
    etaReasonElement.style.visibility = 'hidden';
  }

  function toggleEtaPanelVisibility(visible) {
    const etaPanel = document.getElementById('metric-eta-panel');
    if (!etaPanel) {
      return;
    }

    if (visible) {
      etaPanel.classList.remove('snapshot-item--hidden');
      return;
    }

    etaPanel.classList.add('snapshot-item--hidden');
  }

  function formatPowerKw(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
      return '--';
    }
    return `${Number(value).toFixed(2)} kW`;
  }

  function formatEnergyKwh(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
      return '--';
    }
    return `${Number(value).toFixed(2)} kWh`;
  }

  function formatCapacityKwh(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) {
      return '--';
    }
    return `${Number(value).toFixed(1)} kWh`;
  }

  function formatSnapshotTimestamp(value) {
    if (!value) {
      return '--';
    }

    const parsedDate = new Date(value);
    if (Number.isNaN(parsedDate.getTime())) {
      return '--';
    }

    return parsedDate.toLocaleString();
  }

  function hasMeaningfulMetric(value) {
    if (value === null || value === undefined) {
      return false;
    }
    const text = String(value).trim();
    return text !== '' && text !== '--';
  }

  function toggleElementVisibility(elementId, visible) {
    const element = document.getElementById(elementId);
    if (!element) {
      return;
    }

    if (visible) {
      element.classList.remove('snapshot-item--hidden');
    } else {
      element.classList.add('snapshot-item--hidden');
    }
  }

  function updateSnapshotOptionalVisibility() {
    const batteryText = document.getElementById('metric-battery-capacity')?.textContent || '';
    const emsText = document.getElementById('metric-ems-limit')?.textContent || '';
    const energyText = document.getElementById('metric-session-energy')?.textContent || '';
    const requestedPowerText = document.getElementById('metric-requested-power')?.textContent || '';
    const requestedModeText = document.getElementById('metric-requested-power-mode')?.textContent || '';

    toggleElementVisibility('metric-battery-capacity-item', hasMeaningfulMetric(batteryText));
    toggleElementVisibility('metric-ems-limit-item', hasMeaningfulMetric(emsText));
    toggleElementVisibility('metric-session-energy-item', hasMeaningfulMetric(energyText));

    const showRequestedMode = hasMeaningfulMetric(requestedModeText)
      && requestedModeText.trim().toLowerCase() !== requestedPowerText.trim().toLowerCase();
    toggleElementVisibility('metric-requested-power-mode', showRequestedMode);
  }

  function computeEtaToTarget(targetSoc) {
    const socValue = summaryRuntime.vehicleSoc;
    if (!Number.isFinite(socValue)) {
      return { value: '--', reason: 'Missing vehicle SoC' };
    }

    const remainingPercent = Math.max(0, targetSoc - socValue);
    if (remainingPercent <= 0.01) {
      return { value: 'Ready', reason: null };
    }

    if (!Number.isFinite(summaryRuntime.batteryCapacityKwh) || summaryRuntime.batteryCapacityKwh <= 0) {
      return { value: '--', reason: 'Missing battery capacity' };
    }

    if (!Number.isFinite(summaryRuntime.actualPowerKw) || summaryRuntime.actualPowerKw <= 0) {
      return { value: '--', reason: 'Charging power is 0 kW' };
    }

    const remainingEnergyKwh = summaryRuntime.batteryCapacityKwh * (remainingPercent / 100);
    const etaHours = remainingEnergyKwh / summaryRuntime.actualPowerKw;
    return { value: formatEtaDuration(etaHours), reason: null };
  }

  function updateEtaSummary() {
    const eta80Element = document.getElementById('metric-eta80-value');
    const eta100Element = document.getElementById('metric-eta100-value');

    if (!eta80Element || !eta100Element) {
      return;
    }

    const eta80 = computeEtaToTarget(80);
    const eta100 = computeEtaToTarget(100);
    const hasCapacity = Number.isFinite(summaryRuntime.batteryCapacityKwh) && summaryRuntime.batteryCapacityKwh > 0;
    const hasSoc = Number.isFinite(summaryRuntime.vehicleSoc);
    const hasPower = Number.isFinite(summaryRuntime.actualPowerKw) && summaryRuntime.actualPowerKw > 0;
    toggleEtaPanelVisibility(hasCapacity && hasSoc && hasPower);

    eta80Element.textContent = eta80.value;
    eta100Element.textContent = eta100.value;
    updateEtaReason(eta80.reason || eta100.reason);
  }

  function updateVehicleSoc(stationId, socPercentage, updateSummary = true) {
    const tableCell = document.getElementById(`soc-${stationId}`);

    if (socPercentage === null || socPercentage === undefined || socPercentage === '') {
      if (tableCell) {
        tableCell.innerHTML = '<span>--</span>';
      }
      if (updateSummary) {
        updateDashboardCard('metric-vehicle-soc', '--', false);
        summaryRuntime.vehicleSoc = null;
        updateEtaSummary();
      }
      return;
    }

    const numericSoc = Number(socPercentage);
    if (Number.isNaN(numericSoc)) {
      if (tableCell) {
        tableCell.innerHTML = '<span>--</span>';
      }
      if (updateSummary) {
        updateDashboardCard('metric-vehicle-soc', '--', false);
        summaryRuntime.vehicleSoc = null;
        updateEtaSummary();
      }
      return;
    }

    const formattedSoc = formatSocValue(numericSoc);
    if (tableCell) {
      tableCell.innerHTML = `<span>${formattedSoc}</span>`;
    }
    if (updateSummary) {
      updateDashboardCard('metric-vehicle-soc', formattedSoc, false);
      summaryRuntime.vehicleSoc = numericSoc;
      updateEtaSummary();
    }
  }

  function humanizeRequestedMode(requestedMode) {
    const normalizedMode = String(requestedMode || '').toLowerCase();
    if (normalizedMode === 'station-default') {
      return 'Station Default';
    }
    if (normalizedMode === 'auto') {
      return 'Auto';
    }
    if (normalizedMode === 'manual') {
      return 'Manual';
    }

    const rendered = String(requestedMode || '--').replace(/-/g, ' ');
    return rendered.charAt(0).toUpperCase() + rendered.slice(1);
  }

  function updatePowerState(stationId, powerState = {}, updateSummary = true) {
    const runtime = getStationRuntime(stationId);

    // New session has started; avoid showing stale SoC from previous session
    // until fresh telemetry arrives from MeterValues/DataTransfer.
    if (powerState.source === 'start_transaction') {
      updateVehicleSoc(stationId, null, updateSummary);
    }

    const requestedDisplay = powerState.requested_power_display || '--';
    const requestedMode = powerState.requested_power_mode || '--';
    const actualPowerKw = powerState.actual_power_kw;
    const batteryCapacityKwh = powerState.battery_capacity_kwh;
    const energyKwh = powerState.energy_kwh;

    runtime.actualPowerKw = parseNumericValue(actualPowerKw);
    runtime.energyKwh = parseNumericValue(energyKwh);

    if (updateSummary) {
      updateDashboardCard('metric-requested-power', requestedDisplay, false);
      const requestedModeSummary = document.getElementById('metric-requested-power-mode');
      if (requestedModeSummary) {
        requestedModeSummary.textContent = humanizeRequestedMode(requestedMode);
      }
      updateDashboardCard(
        'metric-actual-power',
        formatPowerKw(actualPowerKw),
        false,
      );

      updateDashboardCard('metric-ems-limit', formatPowerKw(powerState.ems_limit_kw), false);
      updateDashboardCard('metric-session-energy', formatEnergyKwh(energyKwh), false);
      updateDashboardCard('metric-battery-capacity', formatCapacityKwh(batteryCapacityKwh), false);

      summaryRuntime.actualPowerKw = parseNumericValue(actualPowerKw);
      if (batteryCapacityKwh !== null && batteryCapacityKwh !== undefined && Number.isFinite(Number(batteryCapacityKwh))) {
        summaryRuntime.batteryCapacityKwh = Number(batteryCapacityKwh);
        const etaPanel = document.getElementById('metric-eta-panel');
        if (etaPanel) {
          etaPanel.dataset.batteryCapacityKwh = String(summaryRuntime.batteryCapacityKwh);
        }
      }
      updateDashboardCard('metric-snapshot-updated', formatSnapshotTimestamp(powerState.timestamp), false);
      updateSnapshotOptionalVisibility();
      updateEtaSummary();
    }

    if (hasActiveSessionSignal(stationId)) {
      renderConnectorStatus(stationId, runtime.rawConnectorStatus || 'charging', updateSummary);
    }
  }

  function resetPowerState(stationId, updateSummary = false) {
    const runtime = getStationRuntime(stationId);
    runtime.actualPowerKw = null;
    runtime.energyKwh = null;
    updatePowerState(stationId, {
      requested_power_display: '--',
      requested_power_mode: '--',
      actual_power_kw: null,
      ems_limit_kw: null,
    }, updateSummary);
  }

  function renderConnectorStatus(stationId, connectorStatus, updateSummary = true) {
    const normalizedStationId = Number(stationId);
    const runtime = getStationRuntime(normalizedStationId);
    runtime.rawConnectorStatus = connectorStatus ? String(connectorStatus).toLowerCase() : null;

    const displayStatus = normalizeConnectorStatusForDisplay(normalizedStationId, connectorStatus);
    runtime.renderedConnectorStatus = displayStatus;

    const connectorCell = document.getElementById(`connector-status-${normalizedStationId}`);
    if (!connectorCell || !displayStatus) {
      return;
    }

    const wasCharging = connectorCell.textContent.includes('Charging');
    let statusClass = 'badge-secondary';
    let statusText = displayStatus;

    if (displayStatus === 'charging') {
      statusClass = 'badge-primary';
      statusText = 'Charging';
      if (updateSummary) {
        updateSessionStatusBadge('Active');
      }
      syncActiveSessions();
    } else if (displayStatus === 'available') {
      statusClass = 'badge-success';
      statusText = 'Available';
      if (updateSummary) {
        updateSessionStatusBadge('Completed');
      }
      updateVehicleSoc(normalizedStationId, null, false);
      resetPowerState(normalizedStationId, updateSummary);
      syncActiveSessions();
    } else if (displayStatus === 'preparing') {
      statusClass = 'badge-info';
      statusText = 'Preparing';
      if (updateSummary) {
        updateSessionStatusBadge('Preparing');
      }
    } else if (displayStatus === 'finishing') {
      statusClass = 'badge-warning';
      statusText = 'Finishing';
      if (updateSummary) {
        updateSessionStatusBadge('Finishing');
      }
    } else if (displayStatus === 'suspendedev' || displayStatus === 'suspendedevse') {
      statusClass = 'badge-warning';
      statusText = 'Suspended';
      if (updateSummary) {
        updateSessionStatusBadge('Suspended');
      }
    } else if (displayStatus === 'faulted') {
      statusClass = 'badge-danger';
      statusText = 'Faulted';
    } else if (displayStatus === 'offline') {
      statusClass = 'badge-dark';
      statusText = 'Offline';
      if (updateSummary) {
        updateSessionStatusBadge('Offline');
      }
      updateVehicleSoc(normalizedStationId, null, false);
      resetPowerState(normalizedStationId, updateSummary);
      syncActiveSessions();
    }

    connectorCell.innerHTML = `<span class="badge ${statusClass}">${statusText}</span>`;
  }

  function connectStatusWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/stations/status/`;

    statusSocket = new WebSocket(wsUrl);

    statusSocket.onopen = function () {
      console.log('Connected to station status updates');
      updateConnectionStatus(true);
    };

    statusSocket.onclose = function () {
      console.log('Disconnected from station status updates');
      updateConnectionStatus(false);
      if (!statusSocket.reconnectAttempt) {
        statusSocket.reconnectAttempt = true;
        setTimeout(() => {
          statusSocket.reconnectAttempt = false;
          connectStatusWebSocket();
        }, 5000);
      }
    };

    statusSocket.onerror = function (error) {
      console.error('WebSocket error:', error);
      updateConnectionStatus(false);
    };

    statusSocket.onmessage = function (event) {
      try {
        const data = JSON.parse(event.data);
        const messageType = data.type || '';

        if (messageType === 'status_snapshot' && data.stations) {
          data.stations.forEach(station => {
            updateStationStatusBadge(station.station_id, station.status);
          });

          const onlineStations = document.getElementById('metric-online');
          if (onlineStations) {
            const onlineCount = data.stations.filter(station => station.online).length;
            onlineStations.textContent = onlineCount;
            dashboardMetrics.onlineStations = onlineCount;
          }

          const lastUpdate = document.getElementById('last-update');
          if (lastUpdate) {
            lastUpdate.textContent = new Date().toLocaleTimeString();
          }
          return;
        }

        const lastUpdate = document.getElementById('last-update');
        if (lastUpdate) {
          lastUpdate.textContent = 'Last update: ' + new Date().toLocaleTimeString();
        }

        if (messageType === 'connector_status_update' || data.connector_status || data.status === 'charging') {
          const stationId = data.station_id;
          const connectorStatus = data.connector_status || (data.status === 'charging' ? 'charging' : null);
          const stationStatus = data.status;

          const statusCell = document.getElementById(`status-${stationId}`);
          if (statusCell) {
            if (stationStatus === 'active') {
              statusCell.innerHTML = '<span class="badge badge-success">Active</span>';
            } else if (stationStatus === 'inactive') {
              statusCell.innerHTML = '<span class="badge badge-secondary">Inactive</span>';
            }
            syncOnlineStations();
          }

          const connectorCell = document.getElementById(`connector-status-${stationId}`);
          if (connectorCell && connectorStatus) {
            renderConnectorStatus(stationId, connectorStatus);
          }
        }

        if (messageType === 'soc_update' && data.station_id) {
          updateVehicleSoc(data.station_id, data.soc_percentage);
        }

        if (messageType === 'station_power_update' && data.station_id) {
          updatePowerState(data.station_id, data);
        }

        if (messageType === 'transaction_stopped') {
          const stationId = data.station_id;
          const connectorCell = document.getElementById(`connector-status-${stationId}`);
          if (connectorCell) {
            connectorCell.innerHTML = '<span class="badge badge-success">Available</span>';
          }
        }

        if (messageType === 'station_status_update' || messageType === 'status_update' || messageType === 'station_status') {
          const statusCell = document.getElementById(`status-${data.station_id}`);
          if (statusCell) {
            let statusClass = 'badge-secondary';
            let statusText = data.status;

            if (data.status === 'active') {
              statusClass = 'badge-success';
              statusText = 'Active';
            } else if (data.status === 'inactive') {
              statusClass = 'badge-secondary';
              statusText = 'Inactive';
              const connectorCell = document.getElementById(`connector-status-${data.station_id}`);
              if (connectorCell) {
                const wasCharging = connectorCell.innerHTML.includes('Charging');
                connectorCell.innerHTML = '<span class="badge badge-dark">Offline</span>';
                updateVehicleSoc(data.station_id, null, false);
                resetPowerState(data.station_id, true);
                syncActiveSessions();
              }
            } else if (data.status === 'maintenance') {
              statusClass = 'badge-warning';
              statusText = 'Maintenance';
            }

            statusCell.innerHTML = `<span class="badge ${statusClass}">${statusText}</span>`;
            syncOnlineStations();
          }
        }

        if (data.station_id && data.connector_status && !messageType) {
          const statusCell = document.getElementById(`status-${data.station_id}`);
          const isStationActive = statusCell && statusCell.textContent.includes('Active');

          if (isStationActive) {
            const connectorCell = document.getElementById(`connector-status-${data.station_id}`);
            if (connectorCell) {
              renderConnectorStatus(data.station_id, data.connector_status, false);
            }
          }
        }

        if (data.message) {
          showMessage(data.message, data.message_type || 'info');
        }
      } catch (error) {
        console.error('Error parsing WebSocket message:', error);
      }
    };
  }

  connectStatusWebSocket();

  // Normalize initial server-rendered value with the same runtime formatter.
  const initialSoc = document.getElementById('metric-vehicle-soc');
  if (initialSoc) {
    const raw = Number((initialSoc.textContent || '').replace('%', '').trim());
    if (Number.isFinite(raw)) {
      initialSoc.textContent = formatSocValue(raw);
      summaryRuntime.vehicleSoc = raw;
    }
  }

  const initialActualPower = document.getElementById('metric-actual-power');
  if (initialActualPower) {
    const rawActualPower = Number((initialActualPower.textContent || '').replace('kW', '').trim());
    if (Number.isFinite(rawActualPower)) {
      summaryRuntime.actualPowerKw = rawActualPower;
    }
  }

  const etaPanel = document.getElementById('metric-eta-panel');
  if (etaPanel) {
    const capacityRaw = Number(etaPanel.dataset.batteryCapacityKwh);
    if (Number.isFinite(capacityRaw)) {
      summaryRuntime.batteryCapacityKwh = capacityRaw;
    }
  }

  const etaReasonElement = document.getElementById('metric-eta-reason');
  if (etaReasonElement && !etaReasonElement.textContent.trim()) {
    etaReasonElement.style.visibility = 'hidden';
  }

  updateEtaSummary();
  updateSnapshotOptionalVisibility();
  syncOnlineStations();

  updateActionButtons();
});