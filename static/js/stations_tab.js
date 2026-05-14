// Global reference to DataTable for WebSocket updates
var stationsTable = null;

document.addEventListener("DOMContentLoaded", function () {
  // Initialize DataTable with paging disabled for real-time updates
  stationsTable = $('#dataTable').DataTable({
    paging: false,
    searching: false,
    info: false
  });

  const checkboxes = document.querySelectorAll("input[name='station_ids']");
  const btnStart = document.getElementById("btn-start");
  const btnStop = document.getElementById("btn-stop");
  const powerSelect = document.getElementById("power-select");
  const selectAll = document.getElementById("select-all");

  // Enable/disable action buttons and power dropdown based on checkbox selection
  function updateActionButtons() {
    const anyChecked = Array.from(checkboxes).some(cb => cb.checked);
    if (btnStart) btnStart.disabled = !anyChecked;
    if (btnStop) btnStop.disabled = !anyChecked;
    if (powerSelect) powerSelect.disabled = !anyChecked;
  }

  // Attach listeners to checkboxes
  checkboxes.forEach(cb => cb.addEventListener("change", updateActionButtons));

  // Select/Deselect All functionality
  if (selectAll) {
    selectAll.addEventListener("change", () => {
      const checked = selectAll.checked;
      checkboxes.forEach(cb => cb.checked = checked);
      updateActionButtons();
    });
  }

  // Get CSRF token for AJAX requests
  function getCSRFToken() {
    return document.querySelector('[name=csrfmiddlewaretoken]').value;
  }

  // Show feedback message
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

    // Insert in the dedicated message container between buttons and table
    const messageContainer = document.getElementById('message-container');
    if (!messageContainer) {
      console.error('Message container not found');
      return;
    }
    
    // Remove existing alerts
    const existingAlerts = messageContainer.querySelectorAll('.alert');
    existingAlerts.forEach(alert => alert.remove());
    
    messageContainer.innerHTML = alertHtml;
    
    // Auto-dismiss after 5 seconds
    setTimeout(() => {
      const alert = messageContainer.querySelector('.alert');
      if (alert) alert.remove();
    }, 5000);
  }

  // Send command via AJAX
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
    formData.append('current_tab', 'list');
    selectedStations.forEach(id => formData.append('station_ids', id));
    
    // Add extra data
    Object.keys(extraData).forEach(key => {
      formData.append(key, extraData[key]);
    });

    // Show loading state
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

  // Attach button click handlers
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

  // Meter values request not supported in OCPP 1.6
  // if (btnMeterValues) {
  //   btnMeterValues.addEventListener('click', (e) => {
  //     e.preventDefault();
  //     sendCommand('request_meter_values');
  //   });
  // }


  // WebSocket for real-time station status updates
  let statusSocket = null;
  
  // Dashboard metrics tracking
  let dashboardMetrics = {
    totalStations: parseInt(document.getElementById('metric-total')?.textContent) || 0,
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
      let statusClass = "badge-secondary";
      let statusText = status;
      
      if (status === "active") {
        statusClass = "badge-success";
        statusText = "Active";
      } else if (status === "inactive") {
        statusClass = "badge-secondary";
        statusText = "Inactive";
      } else if (status === "maintenance") {
        statusClass = "badge-warning";
        statusText = "Maintenance";
      }
      
      statusCell.innerHTML = `<span class="badge ${statusClass}">${statusText}</span>`;
    }
  }
  
  function updateDashboardCard(elementId, value, animate = true) {
    const element = document.getElementById(elementId);
    if (element) {
      if (animate) {
        element.style.transition = 'transform 0.3s ease';
        element.style.transform = 'scale(1.1)';
        setTimeout(() => {
          element.textContent = value;
          element.style.transform = 'scale(1)';
        }, 150);
      } else {
        element.textContent = value;
      }
    }
  }

  function updateVehicleSoc(_stationId, socPercentage) {
    const tableCell = document.getElementById(`soc-${_stationId}`);

    if (socPercentage === null || socPercentage === undefined || socPercentage === '') {
      if (tableCell) {
        tableCell.innerHTML = '<span>--</span>';
      }
      updateDashboardCard('metric-vehicle-soc', '--', false);
      return;
    }

    const numericSoc = Number(socPercentage);
    if (Number.isNaN(numericSoc)) {
      if (tableCell) {
        tableCell.innerHTML = '<span>--</span>';
      }
      updateDashboardCard('metric-vehicle-soc', '--', false);
      return;
    }

    const formattedSoc = `${numericSoc.toFixed(2)} %`;
    if (tableCell) {
      tableCell.innerHTML = `<span>${formattedSoc}</span>`;
    }
    updateDashboardCard('metric-vehicle-soc', formattedSoc, false);
  }

  function updatePowerState(stationId, powerState = {}) {
    const requestedCell = document.getElementById(`requested-power-${stationId}`);
    const requestedModeCell = document.getElementById(`requested-power-mode-${stationId}`);
    const actualCell = document.getElementById(`actual-power-${stationId}`);
    const emsLimitCell = document.getElementById(`ems-limit-${stationId}`);

    const requestedDisplay = powerState.requested_power_display || '--';
    const requestedMode = powerState.requested_power_mode || '--';
    const actualPowerKw = powerState.actual_power_kw;
    const emsLimitKw = powerState.ems_limit_kw;

    if (requestedCell) {
      requestedCell.firstElementChild.textContent = requestedDisplay;
    }
    if (requestedModeCell) {
      requestedModeCell.textContent = requestedMode === 'station-default' ? 'Station Default' : requestedMode.replace('-', ' ');
    }
    if (actualCell) {
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

    updateDashboardCard('metric-requested-power', requestedDisplay, false);
    const requestedModeSummary = document.getElementById('metric-requested-power-mode');
    if (requestedModeSummary) {
      requestedModeSummary.textContent = requestedMode === 'station-default' ? 'Station Default' : requestedMode.replace('-', ' ');
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
  }

  function resetPowerState(stationId) {
    updatePowerState(stationId, {
      requested_power_display: '--',
      requested_power_mode: '--',
      actual_power_kw: null,
      ems_limit_kw: null,
    });
  }
  
  function connectStatusWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/stations/status/`;
    
    statusSocket = new WebSocket(wsUrl);

    statusSocket.onopen = function() {
      console.log('Connected to station status updates');
      updateConnectionStatus(true);
    };

    statusSocket.onclose = function(e) {
      console.log('Disconnected from station status updates');
      updateConnectionStatus(false);
      // Prevent multiple reconnection attempts
      if (!statusSocket.reconnectAttempt) {
        statusSocket.reconnectAttempt = true;
        setTimeout(() => {
          statusSocket.reconnectAttempt = false;
          connectStatusWebSocket();
        }, 5000);
      }
    };

    statusSocket.onerror = function(error) {
      console.error('WebSocket error:', error);
      updateConnectionStatus(false);
    };

    statusSocket.onmessage = function(event) {
      try {
        const data = JSON.parse(event.data);
        console.log('WebSocket message received:', data);
        
        // Handle different message types
        const messageType = data.type || '';
        
        // Handle status snapshot (initial station status)
        if (messageType === 'status_snapshot' && data.stations) {
          console.log('Received status snapshot:', data);
          data.stations.forEach(station => {
            updateStationStatusBadge(station.station_id, station.status);
          });
          
          // Update dashboard counters
          const onlineStations = document.getElementById('metric-online');
          const availableStations = document.getElementById('metric-available');
          
          if (onlineStations) {
            const onlineCount = data.stations.filter(s => s.online).length;
            onlineStations.textContent = onlineCount;
            dashboardMetrics.onlineStations = onlineCount;
          }
          if (availableStations) {
            const availableCount = data.stations.filter(s => s.status === 'active').length;
            availableStations.textContent = availableCount;
          }
          
          // Update last update time
          const lastUpdate = document.getElementById('last-update');
          if (lastUpdate) {
            const now = new Date();
            lastUpdate.textContent = now.toLocaleTimeString();
          }
          
          return;
        }
        
        // Update last update timestamp
        const lastUpdate = document.getElementById('last-update');
        if (lastUpdate) {
          lastUpdate.textContent = 'Last update: ' + new Date().toLocaleTimeString();
        }
        
        // Handle connector status update
        if (messageType === 'connector_status_update' || data.connector_status || data.status === 'charging') {
          const stationId = data.station_id;
          const connectorStatus = data.connector_status || (data.status === 'charging' ? 'charging' : null);
          const stationStatus = data.status;
          
          console.log(`Updating station ${stationId}: stationStatus=${stationStatus}, connectorStatus=${connectorStatus}`);
          
          // Update station status badge
          const statusCell = document.getElementById(`status-${stationId}`);
          if (statusCell) {
            const wasActive = statusCell.innerHTML.includes('Active');
            const isNowActive = stationStatus === 'active';
            
            if (stationStatus === 'active') {
              statusCell.innerHTML = `<span class="badge badge-success">Active</span>`;
              // Update online counter if station just came online
              if (!wasActive) {
                dashboardMetrics.onlineStations++;
                updateDashboardCard('metric-online', dashboardMetrics.onlineStations);
              }
            } else if (stationStatus === 'inactive') {
              statusCell.innerHTML = `<span class="badge badge-secondary">Inactive</span>`;
              // Update online counter if station just went offline
              if (wasActive) {
                dashboardMetrics.onlineStations = Math.max(0, dashboardMetrics.onlineStations - 1);
                updateDashboardCard('metric-online', dashboardMetrics.onlineStations);
              }
            }
          }
          
          // Update connector status badge
          const connectorCell = document.getElementById(`connector-status-${stationId}`);
          if (connectorCell && connectorStatus) {
            const wasCharging = connectorCell.innerHTML.includes('Charging');
            let statusClass = "badge-secondary";
            let statusText = connectorStatus;
            
            if (connectorStatus === "charging") {
              statusClass = "badge-primary";
              statusText = "Charging";
              // Update active sessions if just started charging
              if (!wasCharging) {
                dashboardMetrics.activeSessions++;
                updateDashboardCard('metric-sessions', dashboardMetrics.activeSessions);
              }
            } else if (connectorStatus === "available") {
              statusClass = "badge-success";
              statusText = "Available";
              updateVehicleSoc(stationId, null);
              resetPowerState(stationId);
              // Update active sessions if just stopped charging
              if (wasCharging) {
                dashboardMetrics.activeSessions = Math.max(0, dashboardMetrics.activeSessions - 1);
                updateDashboardCard('metric-sessions', dashboardMetrics.activeSessions);
              }
            } else if (connectorStatus === "preparing") {
              statusClass = "badge-info";
              statusText = "Preparing";
            } else if (connectorStatus === "faulted") {
              statusClass = "badge-danger";
              statusText = "Faulted";
            } else if (connectorStatus === "offline") {
              statusClass = "badge-dark";
              statusText = "Offline";
              updateVehicleSoc(stationId, null);
              resetPowerState(stationId);
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
        
        // Handle transaction stopped
        if (messageType === 'transaction_stopped') {
          const stationId = data.station_id;
          const connectorCell = document.getElementById(`connector-status-${stationId}`);
          if (connectorCell) {
            connectorCell.innerHTML = `<span class="badge badge-success">Available</span>`;
          }
        }
        
        // Handle station status update (connect/disconnect)
        if (messageType === 'station_status_update' || messageType === 'status_update' || messageType === 'station_status') {
          console.log('Processing station_status:', data);
          const statusCell = document.getElementById(`status-${data.station_id}`);
          console.log('Status cell found:', statusCell);
          if (statusCell) {
            const wasActive = statusCell.innerHTML.includes('Active');
            let statusClass = "badge-secondary";
            let statusText = data.status;
            
            if (data.status === "active") {
              statusClass = "badge-success";
              statusText = "Active";
              // Update online counter if station just came online
              if (!wasActive) {
                dashboardMetrics.onlineStations++;
                updateDashboardCard('metric-online', dashboardMetrics.onlineStations);
              }
            } else if (data.status === "inactive") {
              statusClass = "badge-secondary";
              statusText = "Inactive";
              // Update online counter if station just went offline
              if (wasActive) {
                dashboardMetrics.onlineStations = Math.max(0, dashboardMetrics.onlineStations - 1);
                updateDashboardCard('metric-online', dashboardMetrics.onlineStations);
              }
              // When station goes offline, connector must also be offline
              const connectorCell = document.getElementById(`connector-status-${data.station_id}`);
              if (connectorCell) {
                const wasCharging = connectorCell.innerHTML.includes('Charging');
                connectorCell.innerHTML = `<span class="badge badge-dark">Offline</span>`;
                updateVehicleSoc(data.station_id, null);
                resetPowerState(data.station_id);
                if (wasCharging) {
                  dashboardMetrics.activeSessions = Math.max(0, dashboardMetrics.activeSessions - 1);
                  updateDashboardCard('metric-sessions', dashboardMetrics.activeSessions);
                }
              }
            } else if (data.status === "maintenance") {
              statusClass = "badge-warning";
              statusText = "Maintenance";
            }
            
            statusCell.innerHTML = `<span class="badge ${statusClass}">${statusText}</span>`;
          }
        }

        // Update connector status (legacy format)
        if (data.station_id && data.connector_status && !messageType) {
          const statusCell = document.getElementById(`status-${data.station_id}`);
          const isStationActive = statusCell && statusCell.textContent.includes('Active');
          
          if (isStationActive) {
            const connectorCell = document.getElementById(`connector-status-${data.station_id}`);
            if (connectorCell) {
              let statusClass = "badge-secondary";
              let statusText = data.connector_status;
              
              if (data.connector_status === "charging") {
                statusClass = "badge-primary";
                statusText = "Charging";
              } else if (data.connector_status === "available") {
                statusClass = "badge-success";
                statusText = "Available";
              } else if (data.connector_status === "preparing") {
                statusClass = "badge-info";
                statusText = "Preparing";
              } else if (data.connector_status === "faulted") {
                statusClass = "badge-danger";
                statusText = "Faulted";
              } else if (data.connector_status === "offline") {
                statusClass = "badge-dark";
                statusText = "Offline";
              }
              
              connectorCell.innerHTML = `<span class="badge ${statusClass}">${statusText}</span>`;
            }
          }
        }

        // Show feedback message if provided
        if (data.message) {
          showMessage(data.message, data.message_type || 'info');
        }
        
      } catch (error) {
        console.error('Error parsing WebSocket message:', error);
      }
    };
  }

  // Connect to status WebSocket when page loads
  connectStatusWebSocket();
  // Initial button state
  updateActionButtons();
});