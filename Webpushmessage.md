# Implementation Plan: Web Push Notifications (Flask on Vercel)

## Goal
Let visitors opt in to browser notifications on our website. When we send a push, it appears on their Android phone (Chrome) even if the site is closed. Tapping it opens our website. No native app. Everything must use free tiers.

## Context
- Existing backend: Flask app, already deployed on Vercel.
- Delivery: standard Web Push with VAPID keys, sent from Flask using `pywebpush`.
- Site is served over HTTPS (Vercel does this automatically).

## Important Vercel constraints
- Serverless: there is **no persistent filesystem**. Do not store subscriptions or keys in local files. Use a free external database and environment variables.
- The service worker must be served from the **site root** (`/sw.js`) so its scope covers the whole site. On Vercel, put it in `public/sw.js`.
- Functions have execution time limits. Send in small batches and handle failures per subscription (see Step 6).

## Architecture
1. Browser asks permission, registers `sw.js`, subscribes with the VAPID public key.
2. Browser POSTs the subscription JSON to `POST /api/subscribe`.
3. Flask stores it in the database.
4. To notify, Flask calls `webpush()` for each stored subscription.
5. Push service delivers it, `sw.js` shows it, a tap opens the URL.

## Step 1: Generate VAPID keys (once, locally)
Never regenerate later, or all existing subscriptions break.

```python
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
import base64

k = ec.generate_private_key(ec.SECP256R1())
priv = k.private_numbers().private_value.to_bytes(32, "big")
pub = k.public_key().public_bytes(
    serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
)
b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
print("VAPID_PRIVATE_KEY=" + b64(priv))
print("VAPID_PUBLIC_KEY=" + b64(pub))
```

Add to Vercel (Project Settings, Environment Variables):
- `VAPID_PRIVATE_KEY` (secret, never commit)
- `VAPID_PUBLIC_KEY`
- `VAPID_CONTACT` = `mailto:you@example.com`
- `ADMIN_SEND_TOKEN` = a long random string (protects the send endpoint)
- `DATABASE_URL` (from Step 2)

## Step 2: Free database for subscriptions
Use a free Postgres (for example Neon via the Vercel Marketplace). Any free option is fine (Supabase, Upstash Redis).

```sql
CREATE TABLE push_subscriptions (
  id SERIAL PRIMARY KEY,
  endpoint TEXT UNIQUE NOT NULL,
  p256dh TEXT NOT NULL,
  auth TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);
```

## Step 3: Dependencies
Add to `requirements.txt`:
```
flask
pywebpush
psycopg[binary]
```

## Step 4: Flask routes
- `GET /api/vapid-public-key` returns `{ "key": VAPID_PUBLIC_KEY }`.
- `POST /api/subscribe` receives the subscription JSON (`endpoint`, `keys.p256dh`, `keys.auth`). Upsert by `endpoint`.
- `POST /api/unsubscribe` deletes by `endpoint`.
- `POST /api/send` requires header `Authorization: Bearer <ADMIN_SEND_TOKEN>`. Body: `{ "title", "body", "url" }`. Sends to all subscriptions.

## Step 5: Service worker, `public/sw.js`
```javascript
self.addEventListener("push", (e) => {
  const d = e.data ? e.data.json() : {};
  e.waitUntil(
    self.registration.showNotification(d.title || "Update", {
      body: d.body || "",
      data: d.url || "/",
    })
  );
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil(clients.openWindow(e.notification.data));
});
```

## Step 6: Sending logic (Flask)
```python
import json, os
from pywebpush import webpush, WebPushException

def send_to(sub, payload):
    try:
        webpush(
            subscription_info={
                "endpoint": sub["endpoint"],
                "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
            },
            data=json.dumps(payload),
            vapid_private_key=os.environ["VAPID_PRIVATE_KEY"],
            vapid_claims={"sub": os.environ["VAPID_CONTACT"]},
        )
        return True
    except WebPushException as e:
        if e.response is not None and e.response.status_code in (404, 410):
            return "gone"  # delete this subscription from the DB
        return False
```
Delete any subscription that returns 404 or 410 (user unsubscribed or token expired).

## Step 7: Frontend subscribe code
Add a button such as "Enable notifications". Do not prompt on page load. Ask only after a user click.

```javascript
async function enablePush() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;
  const perm = await Notification.requestPermission();
  if (perm !== "granted") return;

  const reg = await navigator.serviceWorker.register("/sw.js");
  const { key } = await (await fetch("/api/vapid-public-key")).json();

  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(key),
  });

  await fetch("/api/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(sub),
  });
}

function urlBase64ToUint8Array(s) {
  const p = "=".repeat((4 - (s.length % 4)) % 4);
  const b = atob((s + p).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...b].map((c) => c.charCodeAt(0)));
}
```

## Step 8: Test
1. Open the deployed site on Android Chrome and tap "Enable notifications". Allow.
2. Confirm a row appears in `push_subscriptions`.
3. Send a test:
```
curl -X POST https://YOUR-SITE.vercel.app/api/send \
  -H "Authorization: Bearer $ADMIN_SEND_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Hello","body":"Test push","url":"https://YOUR-SITE.vercel.app"}'
```
4. Close Chrome and send again. The notification should still arrive.
5. Tap it and confirm the site opens.

## Acceptance criteria
- User can opt in via a button and the subscription is stored.
- Push arrives with the site closed on Android Chrome.
- Tapping the notification opens the target URL.
- The `/api/send` endpoint rejects requests without the token.
- Dead subscriptions (404/410) are removed automatically.
- No secrets in the repo; keys live only in Vercel env vars.

## Notes for the agent
- Do not store anything on the local filesystem at runtime.
- Keep the same VAPID keys forever.
- Check current free-tier limits for the database before choosing.
- iPhone only supports web push when the site is added to the home screen; Android Chrome works directly.
