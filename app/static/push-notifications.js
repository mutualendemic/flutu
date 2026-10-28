(() => {
  const panel = document.getElementById('push-notifications');
  if (!panel) return;
  const button = document.getElementById('push-toggle');
  const status = document.getElementById('push-status');
  const csrf = panel.dataset.csrf;
  const api = '/api/push';

  function setStatus(message, isError = false) {
    status.textContent = message;
    status.classList.toggle('error', isError);
  }

  function supportsPush() {
    return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  }

  function decodeApplicationKey(value) {
    const padding = '='.repeat((4 - value.length % 4) % 4);
    const binary = atob((value + padding).replace(/-/g, '+').replace(/_/g, '/'));
    return Uint8Array.from(binary, character => character.charCodeAt(0));
  }

  async function sendSubscription(subscription) {
    const response = await fetch(`${api}/subscribe`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
      body: JSON.stringify(subscription.toJSON()),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not save this device subscription.');
  }

  async function syncExistingSubscription() {
    if (!supportsPush() || Notification.permission !== 'granted') return false;
    const registration = await navigator.serviceWorker.getRegistration('/')
      || await navigator.serviceWorker.register('/sw.js');
    const subscription = await registration.pushManager.getSubscription();
    if (!subscription) return false;
    await sendSubscription(subscription);
    return true;
  }

  async function enablePush() {
    if (!supportsPush()) throw new Error('Push notifications are not supported by this browser.');
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') throw new Error('Notification permission was not granted.');
    const registration = await navigator.serviceWorker.register('/sw.js');
    let subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      const response = await fetch(`${api}/vapid-public-key`, {credentials: 'same-origin'});
      const config = await response.json();
      if (!response.ok || !config.key) throw new Error(config.error || 'Push notifications are not configured.');
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: decodeApplicationKey(config.key),
      });
    }
    await sendSubscription(subscription);
    button.dataset.enabled = 'true';
    button.textContent = 'Disable notifications on this device';
    setStatus('Notifications are enabled on this device.');
  }

  async function disablePush() {
    const registration = await navigator.serviceWorker.getRegistration('/');
    const subscription = await registration?.pushManager.getSubscription();
    if (!subscription) {
      button.dataset.enabled = 'false';
      button.textContent = 'Enable notifications';
      setStatus('No active subscription on this device.');
      return;
    }
    const response = await fetch(`${api}/unsubscribe`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
      body: JSON.stringify({endpoint: subscription.endpoint}),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not remove this device subscription.');
    await subscription.unsubscribe();
    button.dataset.enabled = 'false';
    button.textContent = 'Enable notifications';
    setStatus('Notifications are disabled on this device.');
  }

  button.addEventListener('click', async () => {
    if (button.disabled) return;
    button.disabled = true;
    setStatus('Updating notification settings…');
    try {
      if (button.dataset.enabled === 'true') await disablePush();
      else await enablePush();
    } catch (error) {
      setStatus(error.message || 'Could not update notification settings.', true);
    } finally {
      button.disabled = false;
    }
  });

  (async () => {
    if (!supportsPush()) {
      button.disabled = true;
      setStatus('This browser does not support Web Push notifications.');
      return;
    }
    try {
      if (await syncExistingSubscription()) {
        button.dataset.enabled = 'true';
        button.textContent = 'Disable notifications on this device';
        setStatus('Notifications are enabled on this device.');
      } else if (Notification.permission === 'denied') {
        setStatus('Notifications are blocked in this browser’s site settings.');
      } else {
        setStatus('Notifications are off. Enable them to receive friend requests and chat updates.');
      }
    } catch (error) {
      setStatus(error.message || 'Notification settings are unavailable.', true);
    }
  })();
})();
