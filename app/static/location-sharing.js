(() => {
  const t = key => window.FlutuI18n?.[key] || key;
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
  let lastLocationError = '';

  async function api(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }
    });
    const data = await response.json();
    if (!response.ok) throw new Error(t(data.error || 'Location sharing is unavailable.'));
    return data;
  }

  function renderStatus(status, error = '') {
    if (!indicator) return;
    indicator.hidden = false;
    indicator.classList.toggle('is-sharing', Boolean(status?.enabled));
    indicator.classList.toggle('is-paused', Boolean(status?.active_recipients && !status?.enabled));
    if (error) {
      indicator.textContent = t('Location sharing status unavailable');
      indicator.title = error;
    } else if (status.enabled && !locationSupported) {
      indicator.textContent = t('Location access unavailable in this browser');
      indicator.title = t('This browser does not support geolocation.');
    } else if (status.enabled && !window.isSecureContext) {
      indicator.textContent = t('Location requires a secure connection');
      indicator.title = t('Open ux9.eu using HTTPS to share device location.');
    } else if (status.enabled && lastLocationError) {
      indicator.textContent = t('Location sharing needs attention');
      indicator.title = lastLocationError;
    } else if (status.enabled) {
      indicator.textContent = t(status.active_recipients === 1 ? 'Sharing location with {count} contact' : 'Sharing location with {count} contacts').replace('{count}', status.active_recipients);
      indicator.title = t('Your latest location is shared while you are using ux9.eu.');
    } else if (status.active_recipients) {
      indicator.textContent = t('Location sharing paused');
      indicator.title = t('You have active permissions, but location updates are paused.');
    } else {
      indicator.textContent = t('Location sharing off');
      indicator.title = t('No active location-sharing permissions.');
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
        lastLocationError = '';
        window.dispatchEvent(new CustomEvent('location-sharing-error', { detail: { message: '' } }));
      } catch (error) {
        lastLocationError = error.message;
        window.dispatchEvent(new CustomEvent('location-sharing-error', { detail: { message: error.message } }));
        if (error.message.includes('Accept a sharing request')) stopUpdates();
      } finally {
        updatePending = false;
      }
    }, error => {
      if (error.code === 1) lastLocationError = t('Location permission was denied. Allow access in your browser settings.');
      else if (error.code === 2) lastLocationError = t('Your device could not determine its location. Check that Location is enabled.');
      else if (error.code === 3) lastLocationError = t('Getting your location timed out. Check your device Location setting.');
      else lastLocationError = error.message || t('Could not get your device location.');
      window.dispatchEvent(new CustomEvent('location-sharing-error', { detail: { message: lastLocationError } }));
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

  window.addEventListener('location-sharing-error', event => {
    if (event.detail?.message) lastLocationError = event.detail.message;
    else lastLocationError = '';
    refreshStatus();
  });

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
