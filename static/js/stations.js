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
  let dashboardMetrics = {
    totalStations: parseInt(document.getElementById('metric-total')?.textContent) || checkboxes.length,
    onlineStations: parseInt(document.getElementById('metric-online')?.textContent) || 0,
    activeSessions: parseInt(document.getElementById('metric-sessions')?.textContent) || 0,
    energyToday: parseFloat(document.getElementById('metric-energy')?.textContent) || 0
  };

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

  function updateVehicleSoc(stationId, socPercentage, updateSummary = true) {
    const tableCell = document.getElementById(`soc-${stationId}`);

    if (socPercentage === null || socPercentage === undefined || socPercentage === '') {
      if (tableCell) {
        tableCell.innerHTML = '<span>--</span>';
      }
      if (updateSummary) {
        updateDashboardCard('metric-vehicle-soc', '--', false);
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
      }
      return;
    }

    const formattedSoc = `${numericSoc.toFixed(2)} %`;
    if (tableCell) {
      tableCell.innerHTML = `<span>${formattedSoc}</span>`;
    }
    if (updateSummary) {
      updateDashboardCard('metric-vehicle-soc', formattedSoc, false);
    }
  }

  function humanizeRequestedMode(requestedMode) {
    if (requestedMode === 'station-default') {
      return 'Station Default';
    }
    return String(requestedMode || '--').replace(/-/g, ' ');
  }

  function updatePowerState(stationId, powerState = {}, updateSummary = true) {
    const requestedCell = document.getElementById(`requested-power-${stationId}`);
    const requestedModeCell = document.getElementById(`requested-power-mode-${stationId}`);
    const actualCell = document.getElementById(`actual-power-${stationId}`);
    const emsLimitCell = document.getElementById(`ems-limit-${stationId}`);

    const requestedDisplay = powerState.requested_power_display || '--';
    const requestedMode = powerState.requested_power_mode || '--';
    const actualPowerKw = powerState.actual_power_kw;
    const emsLimitKw = powerState.ems_limit_kw;
    const energyKwh = powerState.energy_kwh;

    if (requestedCell && requestedCell.firstElementChild) {
      requestedCell.firstElementChild.textContent = requestedDisplay;
    }
    if (requestedModeCell) {
      requestedModeCell.textContent = humanizeRequestedMode(requestedMode);
    }
    if (actualCell && actualCell.firstElementChild) {
      const actualValue = actualPowerKw === null || actualPowerKw === undefined || Number.isNaN(Number(actualPowerKw))
        ? '--'
        : `${Number(actualPowerKw).toFixed(2)} kW`;
      actualCell.firstElementChild.textContent = actualValue;
    }
    if (emsLimitCell) {
      const emsValue = emsLimitKw === null || emsLimitKw === undefined || Number.isNaN(Number(emsLimitKw))
        ? 'EMS --'
        : `EMS ${Number(emsLimitKw).toFixed(2)} kW`;
      emsLimitCell.textContent = emsValue;
    }

    if (updateSummary) {
      updateDashboardCard('metric-requested-power', requestedDisplay, false);
      const requestedModeSummary = document.getElementById('metric-requested-power-mode');
      if (requestedModeSummary) {
        requestedModeSummary.textContent = humanizeRequestedMode(requestedMode);
      }
      updateDashboardCard(
        'metric-actual-power',
        actualPowerKw === null || actualPowerKw === undefined || Number.isNaN(Number(actualPowerKw))
          ? '--'
          : `${Number(actualPowerKw).toFixed(2)} kW`,
        false,
      );
      updateDashboardCard(
        'metric-ems-limit',
        emsLimitKw === null || emsLimitKw === undefined || Number.isNaN(Number(emsLimitKw))
          ? '--'
          : `${Number(emsLimitKw).toFixed(2)} kW`,
        false,
      );
      updateDashboardCard(
        'metric-energy-session',
        energyKwh === null || energyKwh === undefined || Number.isNaN(Number(energyKwh))
          ? '--'
          : `${Number(energyKwh).toFixed(2)} kWh`,
        false,
      );
    }
  }

  function resetPowerState(stationId, updateSummary = false) {
    updatePowerState(stationId, {
      requested_power_display: '--',
      requested_power_mode: '--',
      actual_power_kw: null,
      ems_limit_kw: null,
    }, updateSummary);
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
            const wasActive = statusCell.innerHTML.includes('Active');

            if (stationStatus === 'active') {
              statusCell.innerHTML = '<span class="badge badge-success">Active</span>';
              if (!wasActive) {
                dashboardMetrics.onlineStations++;
                updateDashboardCard('metric-online', dashboardMetrics.onlineStations);
              }
            } else if (stationStatus === 'inactive') {
              statusCell.innerHTML = '<span class="badge badge-secondary">Inactive</span>';
              if (wasActive) {
                dashboardMetrics.onlineStations = Math.max(0, dashboardMetrics.onlineStations - 1);
                updateDashboardCard('metric-online', dashboardMetrics.onlineStations);
              }
            }
          }

          const connectorCell = document.getElementById(`connector-status-${stationId}`);
          if (connectorCell && connectorStatus) {
            const wasCharging = connectorCell.innerHTML.includes('Charging');
            let statusClass = 'badge-secondary';
            let statusText = connectorStatus;

            if (connectorStatus === 'charging') {
              statusClass = 'badge-primary';
              statusText = 'Charging';
              updateSessionStatusBadge('Active');
              if (!wasCharging) {
                dashboardMetrics.activeSessions++;
                updateDashboardCard('metric-sessions', dashboardMetrics.activeSessions);
              }
            } else if (connectorStatus === 'available') {
              statusClass = 'badge-success';
              statusText = 'Available';
              updateSessionStatusBadge('Completed');
              updateVehicleSoc(stationId, null, false);
              resetPowerState(stationId, false);
              if (wasCharging) {
                dashboardMetrics.activeSessions = Math.max(0, dashboardMetrics.activeSessions - 1);
                updateDashboardCard('metric-sessions', dashboardMetrics.activeSessions);
              }
            } else if (connectorStatus === 'preparing') {
              statusClass = 'badge-info';
              statusText = 'Preparing';
              updateSessionStatusBadge('Preparing');
            } else if (connectorStatus === 'finishing') {
              statusClass = 'badge-warning';
              statusText = 'Finishing';
              updateSessionStatusBadge('Finishing');
            } else if (connectorStatus === 'faulted') {
              statusClass = 'badge-danger';
              statusText = 'Faulted';
            } else if (connectorStatus === 'offline') {
              statusClass = 'badge-dark';
              statusText = 'Offline';
              updateSessionStatusBadge('Offline');
              updateVehicleSoc(stationId, null, false);
              resetPowerState(stationId, false);
              if (wasCharging) {
                dashboardMetrics.activeSessions = Math.max(0, dashboardMetrics.activeSessions - 1);
                updateDashboardCard('metric-sessions', dashboardMetrics.activeSessions);
              }
            }

            connectorCell.innerHTML = `<span class="badge ${statusClass}">${statusText}</span>`;
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
            const wasActive = statusCell.innerHTML.includes('Active');
            let statusClass = 'badge-secondary';
            let statusText = data.status;

            if (data.status === 'active') {
              statusClass = 'badge-success';
              statusText = 'Active';
              updateSessionStatusBadge('Active');
              if (!wasActive) {
                dashboardMetrics.onlineStations++;
                updateDashboardCard('metric-online', dashboardMetrics.onlineStations);
              }
            } else if (data.status === 'inactive') {
              statusClass = 'badge-secondary';
              statusText = 'Inactive';
              updateSessionStatusBadge('Offline');
              if (wasActive) {
                dashboardMetrics.onlineStations = Math.max(0, dashboardMetrics.onlineStations - 1);
                updateDashboardCard('metric-online', dashboardMetrics.onlineStations);
              }
              const connectorCell = document.getElementById(`connector-status-${data.station_id}`);
              if (connectorCell) {
                const wasCharging = connectorCell.innerHTML.includes('Charging');
                connectorCell.innerHTML = '<span class="badge badge-dark">Offline</span>';
                updateVehicleSoc(data.station_id, null, false);
                resetPowerState(data.station_id, false);
                if (wasCharging) {
                  dashboardMetrics.activeSessions = Math.max(0, dashboardMetrics.activeSessions - 1);
                  updateDashboardCard('metric-sessions', dashboardMetrics.activeSessions);
                }
              }
            } else if (data.status === 'maintenance') {
              statusClass = 'badge-warning';
              statusText = 'Maintenance';
              updateSessionStatusBadge('Maintenance');
            }

            statusCell.innerHTML = `<span class="badge ${statusClass}">${statusText}</span>`;
          }
        }

        if (data.station_id && data.connector_status && !messageType) {
          const statusCell = document.getElementById(`status-${data.station_id}`);
          const isStationActive = statusCell && statusCell.textContent.includes('Active');

          if (isStationActive) {
            const connectorCell = document.getElementById(`connector-status-${data.station_id}`);
            if (connectorCell) {
              let statusClass = 'badge-secondary';
              let statusText = data.connector_status;

              if (data.connector_status === 'charging') {
                statusClass = 'badge-primary';
                statusText = 'Charging';
              } else if (data.connector_status === 'available') {
                statusClass = 'badge-success';
                statusText = 'Available';
              } else if (data.connector_status === 'preparing') {
                statusClass = 'badge-info';
                statusText = 'Preparing';
              } else if (data.connector_status === 'finishing') {
                statusClass = 'badge-warning';
                statusText = 'Finishing';
              } else if (data.connector_status === 'faulted') {
                statusClass = 'badge-danger';
                statusText = 'Faulted';
              } else if (data.connector_status === 'offline') {
                statusClass = 'badge-dark';
                statusText = 'Offline';
              }

              connectorCell.innerHTML = `<span class="badge ${statusClass}">${statusText}</span>`;
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
  updateActionButtons();
});