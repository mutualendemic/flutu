self.addEventListener('push', event => {
  let message = {};
  try {
    message = event.data ? event.data.json() : {};
  } catch (_) {
    message = {body: event.data ? event.data.text() : ''};
  }
  const title = typeof message.title === 'string' && message.title.trim()
    ? message.title.slice(0, 80)
    : 'Flutu';
  const body = typeof message.body === 'string' ? message.body.slice(0, 180) : '';
  const url = typeof message.url === 'string' ? message.url : '/dashboard';
  event.waitUntil(self.registration.showNotification(title, {
    body,
    icon: '/static/logo.svg',
    badge: '/static/logo.svg',
    data: {url},
    tag: typeof message.tag === 'string' ? message.tag.slice(0, 100) : undefined,
    renotify: false,
  }));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil((async () => {
    let target;
    try {
      target = new URL(event.notification.data?.url || '/dashboard', self.location.origin);
    } catch (_) {
      target = new URL('/dashboard', self.location.origin);
    }
    if (target.origin !== self.location.origin) target = new URL('/dashboard', self.location.origin);
    const windows = await self.clients.matchAll({type: 'window', includeUncontrolled: true});
    for (const client of windows) {
      let clientOrigin = '';
      try { clientOrigin = new URL(client.url).origin; } catch (_) { /* Ignore malformed client URLs. */ }
      if (clientOrigin === self.location.origin && 'focus' in client) {
        if ('navigate' in client && client.url !== target.href) await client.navigate(target.href);
        return client.focus();
      }
    }
    return self.clients.openWindow(target.href);
  })());
});
