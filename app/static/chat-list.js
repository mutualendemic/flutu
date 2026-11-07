(() => {
  const t = key => window.FlutuI18n?.[key] || key;
  const csrf = document.getElementById('chat-config')?.dataset.csrf || '';
  const realtimeMode = document.getElementById('chat-config')?.dataset.realtimeMode || 'socketio';
  const api = '/chat/api';
  const list = document.getElementById('conversation-list');
  const error = document.getElementById('list-error');
  const realtimeStatus = document.getElementById('realtime-status');
  const dialog = document.getElementById('create-dialog');
  const picker = document.getElementById('contact-picker');
  const search = document.getElementById('contact-search');
  let contacts = [];
  let socket;
  let realtimeConnection;
  let listPollingTimer;

  function initials(value) {
    return (value || '?').trim().split(/\s+/).slice(0, 2).map(part => part[0] || '').join('').toUpperCase();
  }

  function renderConversations(conversations) {
    list.replaceChildren();
    if (!conversations.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      const title = document.createElement('h2');
      title.textContent = t('No conversations yet');
      const copy = document.createElement('p');
      copy.textContent = t('Create a conversation and invite people from your Contacts.');
      empty.append(title, copy);
      list.append(empty);
      return;
    }
    for (const conversation of conversations) {
      const card = document.createElement('article');
      card.className = 'conversation-card';
      const link = document.createElement('a');
      link.className = 'conversation-link';
      link.href = `/chat/${encodeURIComponent(conversation.id)}`;
      card.addEventListener('click', event => {
        if (event.target.closest('button')) return;
        if (event.target.closest('a')) return;
        window.location.assign(link.href);
      });
      const title = document.createElement('h2');
      title.textContent = conversation.title;
      const meta = document.createElement('p');
      meta.className = 'chat-meta';
      const activeCount = conversation.members.filter(member => member.active).length;
      const questionCount = conversation.question_count ?? 0;
      meta.textContent = `${activeCount} ${t(activeCount === 1 ? 'member' : 'members')} · ${questionCount} ${t(questionCount === 1 ? 'question' : 'questions')}`;
      const identities = document.createElement('div');
      identities.className = 'member-identities';
      window.FlutuContactList.sortByName(conversation.members).forEach(member => identities.append(
        window.FlutuContactList.createEntry(member, {
          tagName: 'div',
          className: 'chat-member-identity',
          subtitle: member.active ? '' : t('former member'),
        })
      ));
      link.append(title, meta, identities);
      card.append(link);
      if (conversation.is_owner) {
        const deleteButton = document.createElement('button');
        deleteButton.className = 'button button-danger small-button conversation-delete';
        deleteButton.type = 'button';
        deleteButton.textContent = t('Delete');
        deleteButton.setAttribute('aria-label', `${t('Delete')}: ${conversation.title}`);
        deleteButton.addEventListener('click', () => deleteConversation(conversation, deleteButton));
        card.append(deleteButton);
      }
      list.append(card);
    }
  }

  async function deleteConversation(conversation, button) {
    const confirmed = window.confirm(
      t('Permanently delete “{title}” for all members? Its questions and answers will also be deleted.').replace('{title}', conversation.title)
    );
    if (!confirmed) return;
    await window.FlutuAction.run(button, async () => {
      try {
        const response = await fetch(`${api}/conversations/${encodeURIComponent(conversation.id)}`, {
          method: 'DELETE', headers: {'X-CSRF-Token': csrf},
        });
        const body = await response.json();
        if (!response.ok) throw new Error(body.error || t('Could not delete conversation.'));
        await loadConversations();
      } catch (err) {
        error.textContent = err.message;
      }
    });
  }

  async function loadConversations() {
    const response = await fetch(`${api}/conversations`);
    if (!response.ok) throw new Error(t('Could not load conversations.'));
    renderConversations((await response.json()).conversations);
  }

  function startListPolling() {
    if (listPollingTimer) return;
    if (socket) socket.disconnect();
    realtimeStatus.textContent = t('Using slower polling.');
    listPollingTimer = window.setInterval(() => loadConversations().catch(() => {}), 5000);
  }

  function setupSupabaseRealtime() {
    realtimeStatus.textContent = t('Checking private channel access with Supabase…');
    if (!window.FlutuChatRealtime?.connect) {
      realtimeStatus.textContent = t('Supabase client is unavailable. Using slower polling.');
      startListPolling();
      return;
    }
    window.FlutuChatRealtime.connect((topic, payload) => {
      if (!topic.startsWith('chat-user:')) return;
      loadConversations().catch(() => {});
      if (realtimeConnection) realtimeConnection.refresh().catch(() => startListPolling());
    }, state => {
      if (state === 'CONNECTED') {
        window.clearInterval(listPollingTimer);
        listPollingTimer = undefined;
        realtimeStatus.textContent = t('Supabase accepted the private channel subscription.');
        realtimeStatus.classList.remove('error');
      } else if (state === 'AUTHORIZATION_FAILED' || state === 'CHANNEL_ERROR' || state === 'TIMED_OUT' || state === 'CLOSED' || state === 'ERROR') {
        startListPolling();
      }
    }, {userOnly: true}).then(connection => { realtimeConnection = connection; })
      .catch(() => startListPolling());
  }

  function renderContacts() {
    const query = search.value.trim().toLowerCase();
    picker.replaceChildren();
    for (const contact of window.FlutuContactList.sortByName(
      contacts.filter(item => `${item.name} ${item.email}`.toLowerCase().includes(query))
    )) {
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.value = contact.user_id || '';
      checkbox.disabled = !contact.addable;
      picker.append(window.FlutuContactList.createEntry(contact, {
        tagName: 'label',
        className: 'picker-contact',
        control: checkbox,
      }));
    }
    if (!picker.children.length) {
      const empty = document.createElement('p');
      empty.textContent = t('No contacts match your search.');
      picker.append(empty);
    }
  }

  async function openCreateDialog() {
    document.getElementById('create-error').textContent = '';
    document.getElementById('conversation-title').value = '';
    try {
      const response = await fetch(`${api}/contacts/addable`);
      if (!response.ok) throw new Error(t('Could not load Contacts.'));
      contacts = (await response.json()).contacts;
      renderContacts();
      dialog.showModal();
    } catch (err) {
      document.getElementById('create-error').textContent = err.message;
    }
  }

  document.getElementById('new-conversation').addEventListener('click', openCreateDialog);
  document.getElementById('cancel-create').addEventListener('click', () => dialog.close());
  search.addEventListener('input', renderContacts);
  document.getElementById('create-form').addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    await window.FlutuAction.run(event.submitter || form.querySelector('[type="submit"]'), async () => {
      try {
        const member_user_ids = [...picker.querySelectorAll('input:checked')].map(input => input.value);
        const response = await fetch(`${api}/conversations`, {
          method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
          body: JSON.stringify({title: document.getElementById('conversation-title').value, member_user_ids}),
        });
        const body = await response.json();
        if (!response.ok) throw new Error(body.error || t('Could not create conversation.'));
        window.location.assign(`/chat/${encodeURIComponent(body.conversation_id)}`);
      } catch (err) {
        document.getElementById('create-error').textContent = err.message;
      }
    });
  });

  loadConversations().catch(err => { error.textContent = err.message; });
  if (realtimeMode === 'supabase') {
    setupSupabaseRealtime();
  } else if (realtimeMode === 'polling') {
    startListPolling();
  } else if (typeof window.io === 'function') {
    socket = window.io('/chat');
    socket.on('conversation_added', () => loadConversations().catch(() => {}));
    socket.on('conversation_updated', () => loadConversations().catch(() => {}));
    socket.on('conversation_removed', () => loadConversations().catch(() => {}));
    socket.on('connect_error', startListPolling);
  } else startListPolling();
})();
