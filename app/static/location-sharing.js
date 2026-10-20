(() => {
  const config = document.getElementById('location-sharing-config');
  if (!config) return;
  const locationSupported = Boolean(navigator.geolocation);

  const statusUrl = config.dataset.statusUrl;
  const updatesUrl = config.dataset.updatesUrl;
  const indicator = document.getElementById('location-sharing-indicator');
  const updateIntervalMs = 30000;
  let active = false;
  let updateTimer = null;
  let statusTimer = null;
  let updatePending = false;

  async function api(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Location sharing is unavailable.');
    return data;
  }

  function renderStatus(status, error = '') {
    if (!indicator) return;
    indicator.hidden = false;
    indicator.classList.toggle('is-sharing', Boolean(status?.enabled));
    indicator.classList.toggle('is-paused', Boolean(status?.active_recipients && !status?.enabled));
    if (error) {
      indicator.textContent = 'Location sharing status unavailable';
      indicator.title = error;
    } else if (status.enabled && !locationSupported) {
      indicator.textContent = 'Location access unavailable in this browser';
      indicator.title = 'This browser does not support geolocation.';
    } else if (status.enabled) {
      indicator.textContent = `Sharing location with ${status.active_recipients} contact${status.active_recipients === 1 ? '' : 's'}`;
      indicator.title = 'Your latest location is shared while you are using Flutu.';
    } else if (status.active_recipients) {
      indicator.textContent = 'Location sharing paused';
      indicator.title = 'You have active permissions, but location updates are paused.';
    } else {
      indicator.textContent = 'Location sharing off';
      indicator.title = 'No active location-sharing permissions.';
    }
  }

  function stopUpdates() {
    active = false;
    if (updateTimer !== null) window.clearInterval(updateTimer);
    updateTimer = null;
  }

  function sendLocation() {
    if (!locationSupported || !active || updatePending || document.visibilityState === 'hidden') return;
    updatePending = true;
    navigator.geolocation.getCurrentPosition(async position => {
      try {
        await api(updatesUrl, {
          method: 'POST',
          body: JSON.stringify({
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
            accuracy: position.coords.accuracy
          })
        });
      } catch (error) {
        if (error.message.includes('Accept a sharing request')) stopUpdates();
      } finally {
        updatePending = false;
      }
    }, () => {
      updatePending = false;
    }, { enableHighAccuracy: false, maximumAge: 15000, timeout: 20000 });
  }

  function startUpdates() {
    if (active || !locationSupported) return;
    active = true;
    sendLocation();
    updateTimer = window.setInterval(sendLocation, updateIntervalMs);
  }

  async function refreshStatus() {
    try {
      const status = await api(statusUrl);
      renderStatus(status);
      if (status.enabled && status.active_recipients) startUpdates();
      else stopUpdates();
    } catch (error) {
      renderStatus({ enabled: false, active_recipients: 0 }, error.message);
      stopUpdates();
    }
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && active) sendLocation();
  });
  window.addEventListener('location-sharing-updated', refreshStatus);

  refreshStatus();
  statusTimer = window.setInterval(refreshStatus, updateIntervalMs);
  window.addEventListener('pagehide', () => {
    stopUpdates();
    if (statusTimer !== null) window.clearInterval(statusTimer);
  });
})();
