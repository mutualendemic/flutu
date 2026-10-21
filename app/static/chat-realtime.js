(() => {
  const api = '/chat/api';

  async function loadConfig(options) {
    const query = options.conversationId
      ? `?conversation_id=${encodeURIComponent(options.conversationId)}`
      : '';
    const response = await fetch(`${api}/realtime-token${query}`, {credentials: 'same-origin'});
    const config = await response.json();
    if (!response.ok) throw new Error(config.error || 'Supabase Realtime is unavailable.');
    if (!window.supabase?.createClient) throw new Error('Supabase Realtime client did not load.');
    return config;
  }

  function verifyTopicProtection(client) {
    const random = new Uint8Array(12);
    window.crypto.getRandomValues(random);
    const nonce = [...random].map(byte => byte.toString(16).padStart(2, '0')).join('');
    const probe = client.channel(`chat-protection-probe:${nonce}`, {config: {private: true}});

    return new Promise((resolve, reject) => {
      let settled = false;
      const timeout = window.setTimeout(() => finish(
        new Error('Could not verify that Supabase blocks unauthorized private topics. Check the realtime.messages SELECT RLS policy.'),
      ), 8000);
      const finish = async error => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timeout);
        try { await client.removeChannel(probe); } catch (_) { /* probe already closed */ }
        if (error) reject(error);
        else resolve(true);
      };

      probe.subscribe(status => {
        if (status === 'SUBSCRIBED') {
          finish(new Error(
            'Supabase accepted an unauthorized private test topic. Realtime RLS is disabled or another SELECT policy is too broad.'
          ));
        } else if (status === 'CHANNEL_ERROR') {
          finish();
        } else if (status === 'TIMED_OUT' || status === 'CLOSED') {
          finish(new Error(
            'Supabase could not confirm denial of an unauthorized private topic. Check private-channel settings and the realtime.messages SELECT RLS policy.'
          ));
        }
      });
    });
  }

  async function connect(onEvent, onStatus, options = {}) {
    let stopped = false;
    let client;
    let channels = [];
    let renewalTimer;
    let authorizationTimer;
    let reconnecting = false;

    async function subscribe() {
      if (stopped || reconnecting) return;
      reconnecting = true;
      onStatus('CONNECTING');
      try {
        const config = await loadConfig(options);
        if (!client) {
          client = window.supabase.createClient(config.url, config.anon_key, {
            auth: {persistSession: false, autoRefreshToken: false, detectSessionInUrl: false},
          });
        }
        client.realtime.setAuth(config.access_token);
        const topics = [config.user_topic];
        if (options.conversationId && config.conversation_topics[options.conversationId]) {
          topics.push(config.conversation_topics[options.conversationId]);
        } else if (!options.userOnly) {
          topics.push(...Object.values(config.conversation_topics));
        }
        let subscribed = 0;
        window.clearTimeout(authorizationTimer);
        authorizationTimer = window.setTimeout(() => {
          onStatus('AUTHORIZATION_FAILED', new Error(
            'Private channel authorization timed out. Check that private Realtime channels are enabled and the realtime.messages SELECT RLS policy is installed.'
          ));
        }, 10000);
        let protectionProbeStarted = false;
        for (const topic of topics) {
          const channel = client.channel(topic, {config: {private: true}});
          channel.on('broadcast', {event: 'chat_update'}, message => onEvent(topic, message.payload || {}));
          channels.push(channel);
          channel.subscribe(status => {
            if (stopped) return;
            onStatus(status);
            if (status === 'SUBSCRIBED') {
              subscribed += 1;
              if (subscribed === topics.length && !protectionProbeStarted) {
                protectionProbeStarted = true;
                window.clearTimeout(authorizationTimer);
                verifyTopicProtection(client)
                  .then(() => onStatus('CONNECTED'))
                  .catch(async error => {
                    for (const activeChannel of channels) {
                      try { await client.removeChannel(activeChannel); } catch (_) { /* already closed */ }
                    }
                    channels = [];
                    onStatus('AUTHORIZATION_FAILED', error);
                  });
              }
            } else if (status === 'CHANNEL_ERROR' || status === 'TIMED_OUT' || status === 'CLOSED') {
              window.clearTimeout(authorizationTimer);
              onStatus('AUTHORIZATION_FAILED', new Error(
                'Supabase rejected or could not authorize a private chat topic. Check Realtime private-channel settings, the JWT secret, and the realtime.messages SELECT RLS policy.'
              ));
            }
          });
        }
        window.clearTimeout(renewalTimer);
        renewalTimer = window.setTimeout(async () => {
          for (const channel of channels) {
            try { await client.removeChannel(channel); } catch (_) { /* already closed */ }
          }
          channels = [];
          subscribe();
        }, Math.max(30_000, (config.expires_in - 45) * 1000));
      } catch (error) {
        window.clearTimeout(authorizationTimer);
        for (const channel of channels) {
          try { await client?.removeChannel(channel); } catch (_) { /* already closed */ }
        }
        channels = [];
        onStatus('ERROR', error);
      } finally {
        reconnecting = false;
      }
    }

    await subscribe();
    return {
      refresh: async () => {
        if (stopped) return;
        for (const channel of channels) {
          try { await client.removeChannel(channel); } catch (_) { /* already closed */ }
        }
        channels = [];
        await subscribe();
      },
      close: async () => {
        stopped = true;
        window.clearTimeout(renewalTimer);
        window.clearTimeout(authorizationTimer);
        if (client) await client.removeAllChannels();
        channels = [];
      },
    };
  }

  window.FlutuChatRealtime = {connect};
})();
