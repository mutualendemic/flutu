(() => {
  const root = document.querySelector('.conversation-page');
  const conversationId = root.dataset.conversationId;
  const csrf = root.dataset.csrf;
  const realtimeMode = root.dataset.realtimeMode || 'socketio';
  const api = '/chat/api';
  const graphElement = document.getElementById('graph');
  const status = document.getElementById('connection-status');
  const details = document.getElementById('details');
  const error = document.getElementById('chat-error');
  const optionsEditor = document.getElementById('option-editors');
  const answerDialog = document.getElementById('answer-dialog');
  const membersPanel = document.getElementById('members-panel');
  const nodes = new Map();
  const edges = new Map();
  let graph;
  let snapshot;
  let socket;
  let realtimeConnection;
  let pollingTimer;
  let polling = false;
  let selectedOption;
  let followUpOption;

  function el(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  function setError(message) { error.textContent = message || ''; }
  function position(data) { return {x: 90 + Number(data.lane || 0) * 145, y: 55 + Number(data.row || 0) * 58}; }
  function cyNode(data) {
    return {group: 'nodes', data: {...data}, position: position(data)};
  }
  function cyEdge(data) {
    return {group: 'edges', data: {...data, id: `${data.kind}:${data.from}:${data.to}`, source: data.from, target: data.to}};
  }

  function ensureGraph() {
    if (graph) return;
    graph = window.cytoscape({
      container: graphElement,
      elements: [],
      layout: {name: 'preset', fit: true, padding: 28},
      minZoom: 0.35, maxZoom: 2.5, wheelSensitivity: 0.18,
      style: [
        {selector: 'node[type="question"]', style: {label: 'data(label)', shape: 'round-rectangle', width: 145, height: 46, 'text-wrap': 'wrap', 'text-max-width': 132, 'font-size': 11, color: '#14213d', 'background-color': '#ffffff', 'border-width': 2, 'border-color': '#f79009', 'text-valign': 'center', 'text-halign': 'center'}},
        {selector: 'node[type="question"][status="closed"]', style: {'background-color': '#f2f4f7', 'border-color': '#98a2b3'}},
        {selector: 'node[type="option"]', style: {label: 'data(display)', shape: 'round-rectangle', width: 132, height: 40, 'font-size': 10, color: '#344054', 'background-color': '#fff7e6', 'border-width': 1, 'border-color': '#f79009', 'text-valign': 'center', 'text-halign': 'center'}},
        {selector: 'node[type="option"][is_winner]', style: {'border-width': 3, 'border-color': '#12b76a', 'background-color': '#ecfdf3'}},
        {selector: 'node[type="option"][is_tied]', style: {'border-width': 3, 'border-color': '#12b76a'}},
        {selector: 'node[type="end"]', style: {label: 'data(label)', shape: 'ellipse', width: 16, height: 16, 'font-size': 8, color: '#667085', 'background-color': '#98a2b3'}},
        {selector: 'edge[kind="main_thread"]', style: {width: 2, 'line-color': '#98a2b3', 'target-arrow-shape': 'triangle', 'target-arrow-color': '#98a2b3', 'curve-style': 'bezier'}},
        {selector: 'edge[kind="branch"]', style: {width: 2, 'line-color': '#f79009', 'target-arrow-shape': 'triangle', 'target-arrow-color': '#f79009', 'curve-style': 'taxi'}},
        {selector: 'edge[kind="follow_up"]', style: {width: 2, 'line-color': '#7f77dd', 'target-arrow-shape': 'triangle', 'target-arrow-color': '#7f77dd', 'curve-style': 'taxi'}},
        {selector: 'edge[kind="merge"]', style: {width: 2, 'line-color': '#667085', 'target-arrow-shape': 'triangle', 'target-arrow-color': '#667085', 'line-style': 'dashed', 'curve-style': 'taxi'}},
      ],
    });
    graph.on('tap', 'node', event => selectNode(event.target.data()));
  }

  function applyGraph(data) {
    if (!data || !Array.isArray(data.nodes)) return;
    snapshot = data;
    document.getElementById('conversation-title').textContent = data.title || 'Conversation';
    ensureGraph();
    const nextNodeIds = new Set();
    for (const node of data.nodes) {
      nextNodeIds.add(node.id);
      node.display = node.type === 'option' ? `${node.label} · ${node.count}${node.count === 1 ? ' vote' : ' votes'}` : node.label;
      nodes.set(node.id, node);
      const existing = graph.getElementById(node.id);
      if (existing.length) {
        existing.data(node);
        existing.animate({position: position(node)}, {duration: 250});
      } else graph.add(cyNode(node));
    }
    graph.nodes().forEach(node => { if (!nextNodeIds.has(node.id())) node.remove(); });
    const nextEdgeIds = new Set();
    for (const edge of data.edges || []) {
      const id = `${edge.kind}:${edge.from}:${edge.to}`;
      nextEdgeIds.add(id);
      edges.set(id, edge);
      if (!graph.getElementById(id).length) graph.add(cyEdge(edge));
    }
    graph.edges().forEach(edge => { if (!nextEdgeIds.has(edge.id())) edge.remove(); });
    graph.layout({name: 'preset', fit: false}).run();
    renderMembers(data.members || []);
  }

  async function resync() {
    const response = await fetch(`${api}/conversations/${encodeURIComponent(conversationId)}`);
    if (response.status === 401) window.location.assign('/');
    if (response.status === 403) window.location.assign('/chat/');
    if (!response.ok) throw new Error('Could not load this conversation.');
    applyGraph(await response.json());
  }

  function memberName(userId) {
    return snapshot?.members?.find(member => member.user_id === userId)?.name || 'Former member';
  }

  function renderDetailsQuestion(node) {
    details.replaceChildren();
    const title = el('h2', node.label);
    const author = el('p', `Asked by ${memberName(node.author_user_id)} · ${node.status}`);
    details.append(title, author);
    if (node.status === 'open') {
      const close = el('button', 'Close question', 'button button-secondary');
      close.type = 'button';
      close.addEventListener('click', async () => {
        try { await performAction('close_question', {question_id: node.id.slice(1)}); await resync(); }
        catch (err) { setError(err.message); }
      });
      details.append(close);
    }
    const opts = (snapshot.nodes || []).filter(item => item.type === 'option' && item.question_id === node.id.slice(1));
    for (const option of opts) {
      const names = option.voter_user_ids.map((id, index) => option.voter_names[index] || memberName(id));
      details.append(el('p', `${option.label}: ${option.count} ${option.count === 1 ? 'vote' : 'votes'}${names.length ? ` — ${names.join(', ')}` : ''}`));
    }
  }

  function selectNode(node) {
    const value = nodes.get(node.id) || node;
    if (value.type === 'question') {
      renderDetailsQuestion(value);
      return;
    }
    if (value.type !== 'option') return;
    selectedOption = value;
    details.replaceChildren();
    details.append(el('h2', value.label));
    details.append(el('p', `${value.count} ${value.count === 1 ? 'vote' : 'votes'}`));
    const question = nodes.get(`q${value.question_id}`);
    if (question?.status === 'open') {
      const answer = el('button', 'Choose this option', 'button');
      answer.type = 'button';
      answer.addEventListener('click', () => openAnswer(question, value));
      details.append(answer);
    }
    const follow = el('button', 'Follow up', 'button button-secondary');
    follow.type = 'button';
    follow.addEventListener('click', () => {
      followUpOption = value.option_id;
      document.getElementById('composer-title').textContent = `Follow up on “${value.label}”`;
      document.getElementById('question-text').focus();
      window.scrollTo({top: document.querySelector('.composer').offsetTop, behavior: 'smooth'});
    });
    details.append(follow);
    const names = value.voter_user_ids.map((id, index) => value.voter_names[index] || memberName(id));
    details.append(el('p', `Voters: ${names.length ? names.join(', ') : 'No votes yet'}`));
  }

  function openAnswer(question, selected) {
    document.getElementById('answer-title').textContent = question.label;
    answerDialog.dataset.questionId = question.id.slice(1);
    const options = document.getElementById('answer-options');
    options.replaceChildren();
    for (const option of (snapshot.nodes || []).filter(item => item.type === 'option' && item.question_id === question.id.slice(1))) {
      const label = el('label', undefined, 'answer-option');
      const radio = document.createElement('input');
      radio.type = 'radio'; radio.name = 'option_id'; radio.value = option.option_id; radio.required = true;
      radio.checked = option.option_id === selected.option_id || option.is_my_vote === true;
      label.append(radio, document.createTextNode(`${option.label} (${option.count})`));
      options.append(label);
    }
    document.getElementById('answer-error').textContent = '';
    answerDialog.showModal();
  }

  function handleAck(response) {
    if (!response?.ok) throw new Error(response?.error || 'The action could not be completed.');
    return response;
  }

  async function performAction(event, payload) {
    let path;
    let body = payload;
    if (event === 'create_question') {
      path = `${api}/conversations/${encodeURIComponent(payload.conversation_id)}/questions`;
      body = {...payload};
      delete body.conversation_id;
    } else if (event === 'submit_answer') {
      path = `${api}/questions/${encodeURIComponent(payload.question_id)}/answers`;
    } else if (event === 'close_question') {
      path = `${api}/questions/${encodeURIComponent(payload.question_id)}/close`;
    } else {
      throw new Error('Unsupported chat action.');
    }
    const response = await fetch(path, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
      body: JSON.stringify(body),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'The action could not be completed.');
    return result;
  }

  async function emitAck(event, payload) {
    setError('');
    try {
      await performAction(event, payload);
      if (event === 'create_question') {
        document.getElementById('question-text').value = '';
        followUpOption = undefined;
        document.getElementById('composer-title').textContent = 'Ask a question';
        createOptionEditors(['Yes', 'No']);
      }
      await resync();
    } catch (err) { setError(err.message); }
  }

  function createOptionEditors(labels) {
    optionsEditor.replaceChildren();
    labels.forEach((value, index) => {
      const row = el('div', undefined, 'option-editor');
      const input = document.createElement('input');
      input.type = 'text'; input.maxLength = 60; input.value = value; input.setAttribute('aria-label', `Option ${index + 1}`);
      const remove = el('button', 'Remove'); remove.type = 'button'; remove.disabled = labels.length <= 2;
      remove.addEventListener('click', () => {
        if (optionsEditor.children.length <= 2) return;
        row.remove();
        [...optionsEditor.querySelectorAll('input')].forEach((field, idx) => field.setAttribute('aria-label', `Option ${idx + 1}`));
        [...optionsEditor.querySelectorAll('button')].forEach(button => button.disabled = optionsEditor.children.length <= 2);
      });
      row.append(input, remove); optionsEditor.append(row);
    });
  }

  function renderMembers(members) {
    const list = document.getElementById('member-list');
    list.replaceChildren();
    for (const member of members) {
      const item = el('li', undefined, 'member-chip');
      const dot = document.createElement('span'); dot.className = 'member-dot'; dot.style.backgroundColor = member.active ? member.color : '#8a8f98'; dot.textContent = (member.name || '?').slice(0, 1).toUpperCase();
      item.append(dot, el('span', `${member.name}${member.active ? '' : ' (former member)'}`));
      if (member.active && member.role !== 'owner') {
        const remove = el('button', 'Remove'); remove.type = 'button';
        remove.addEventListener('click', () => changeMember(member.user_id, 'DELETE'));
        item.append(remove);
      }
      list.append(item);
    }
  }

  async function changeMember(userId, method) {
    const response = await fetch(`${api}/conversations/${encodeURIComponent(conversationId)}/members/${encodeURIComponent(userId)}`, {method, headers: {'X-CSRF-Token': csrf}});
    const body = response.status === 204 ? {} : await response.json();
    if (!response.ok) { setError(body.error || 'Could not update members.'); return; }
    await resync();
  }

  async function loadMemberPicker() {
    const host = document.getElementById('member-picker');
    const search = document.getElementById('member-search');
    const response = await fetch(`${api}/contacts/addable?conversation_id=${encodeURIComponent(conversationId)}`);
    if (!response.ok) return;
    const contacts = (await response.json()).contacts;
    const draw = () => {
      host.replaceChildren();
      const query = search.value.trim().toLowerCase();
      contacts.filter(contact => `${contact.name} ${contact.email}`.toLowerCase().includes(query)).forEach(contact => {
        const label = el('label');
        const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.value = contact.user_id || ''; checkbox.disabled = !contact.addable;
        const text = el('span'); text.append(el('strong', contact.name), el('small', contact.addable ? contact.email : 'Not on the app'));
        label.append(checkbox, text); host.append(label);
      });
    };
    search.addEventListener('input', draw); draw();
  }

  function eventRefresh() { resync().catch(err => setError(err.message)); }
  function startPolling() {
    if (polling) return;
    polling = true;
    if (socket) socket.disconnect();
    status.dataset.connected = 'true';
    status.textContent = 'Live updates · polling';
    const poll = async () => {
      try {
        await resync();
        status.dataset.connected = 'true';
        status.textContent = 'Live updates · polling';
      } catch (err) {
        status.dataset.connected = 'false';
        status.textContent = 'Reconnecting';
        setError(err.message);
      } finally {
        if (polling) pollingTimer = window.setTimeout(poll, 3000);
      }
    };
    pollingTimer = window.setTimeout(poll, 5000);
  }

  function setupSupabaseRealtime() {
    if (!window.FlutuChatRealtime?.connect) {
      startPolling();
      return;
    }
    window.FlutuChatRealtime.connect((topic, payload) => {
      if (topic === `chat-conversation:${conversationId}`) {
        eventRefresh();
        return;
      }
      if (payload.kind === 'conversation_removed' && payload.conversation_id === conversationId) {
        window.location.assign('/chat/');
        return;
      }
      if (realtimeConnection) realtimeConnection.refresh().catch(() => startPolling());
      eventRefresh();
    }, (state, detail) => {
      if (state === 'CONNECTED') {
        status.dataset.connected = 'true';
        status.textContent = 'Private channel authorized · Supabase Realtime';
        status.title = 'Supabase accepted the private channel subscription under its Realtime authorization policy.';
        if (polling) {
          polling = false;
          window.clearTimeout(pollingTimer);
        }
      } else if (state === 'AUTHORIZATION_FAILED' || state === 'CHANNEL_ERROR' || state === 'TIMED_OUT' || state === 'CLOSED' || state === 'ERROR') {
        status.dataset.connected = 'false';
        status.textContent = 'Supabase private-channel check failed · using polling';
        status.title = detail?.message || 'Review private-channel settings and the realtime.messages SELECT RLS policy.';
        setError(`${status.title} Chat is continuing with slower polling.`);
        startPolling();
      }
    }, {conversationId}).then(connection => { realtimeConnection = connection; })
      .catch(() => startPolling());
  }

  function setupSocket() {
    socket = window.io('/chat');
    socket.on('connect', () => {
      status.dataset.connected = 'true'; status.textContent = 'Connected';
      socket.emit('join', {conversation_id: conversationId}, response => {
        try { handleAck(response); applyGraph(response.graph); }
        catch (err) { setError(err.message); }
      });
    });
    socket.on('disconnect', () => {
      status.dataset.connected = 'false'; status.textContent = 'Switching to polling';
      startPolling();
    });
    socket.on('connect_error', () => {
      status.dataset.connected = 'false'; status.textContent = 'Switching to polling';
      startPolling();
    });
    socket.on('question_created', payload => {
      const additions = [...(payload.question ? [payload.question] : []), ...(payload.options || [])];
      const newNodes = new Map((snapshot?.nodes || []).map(node => [node.id, node]));
      additions.forEach(node => newNodes.set(node.id, node));
      const newEdges = new Map((snapshot?.edges || []).map(edge => [`${edge.kind}:${edge.from}:${edge.to}`, edge]));
      (payload.edges || []).forEach(edge => newEdges.set(`${edge.kind}:${edge.from}:${edge.to}`, edge));
      if (snapshot) applyGraph({...snapshot, nodes: [...newNodes.values()], edges: [...newEdges.values()]});
      else eventRefresh();
    });
    socket.on('answer_recorded', payload => {
      const questionId = String(payload.question_id);
      const changed = nodes.get(`o${payload.option_id}`);
      if (changed) {
        changed.voter_user_ids = changed.voter_user_ids.filter(id => id !== payload.user_id).concat(payload.user_id);
        if (!changed.voter_names.includes(memberName(payload.user_id))) changed.voter_names.push(memberName(payload.user_id));
      }
      if (payload.previous_option_id && payload.previous_option_id !== payload.option_id) {
        const previous = nodes.get(`o${payload.previous_option_id}`);
        if (previous) {
          previous.voter_user_ids = previous.voter_user_ids.filter(id => id !== payload.user_id);
          previous.voter_names = previous.voter_names.filter(name => name !== memberName(payload.user_id));
        }
      }
      const updateNodes = (snapshot?.nodes || []).map(node => {
        if (node.type !== 'option' || node.question_id !== questionId) return node;
        const target = nodes.get(node.id) || node;
        target.count = payload.counts[node.option_id] ?? target.count;
        return target;
      });
      if (snapshot) applyGraph({...snapshot, nodes: updateNodes});
      if (payload.closed) eventRefresh();
    });
    socket.on('question_closed', eventRefresh);
    socket.on('question_updated', eventRefresh);
    socket.on('question_deleted', eventRefresh);
    socket.on('member_added', eventRefresh);
    socket.on('member_removed', eventRefresh);
    socket.on('conversation_removed', () => { window.location.assign('/chat/'); });
  }

  document.getElementById('add-option').addEventListener('click', () => {
    if (optionsEditor.children.length >= 10) return;
    const labels = [...optionsEditor.querySelectorAll('input')].map(input => input.value).concat('');
    createOptionEditors(labels);
  });
  document.getElementById('send-question').addEventListener('click', () => {
    const options = [...optionsEditor.querySelectorAll('input')].map(input => input.value);
    emitAck('create_question', {conversation_id: conversationId, text: document.getElementById('question-text').value, options, ...(followUpOption ? {parent_option_id: followUpOption} : {})});
  });
  document.getElementById('answer-form').addEventListener('submit', event => {
    event.preventDefault();
    const optionId = new FormData(event.currentTarget).get('option_id');
    performAction('submit_answer', {question_id: answerDialog.dataset.questionId, option_id: optionId})
      .then(() => { answerDialog.close(); return resync(); })
      .catch(err => { document.getElementById('answer-error').textContent = err.message; });
  });
  document.getElementById('cancel-answer').addEventListener('click', () => answerDialog.close());
  document.getElementById('members-toggle').addEventListener('click', async () => {
    membersPanel.hidden = !membersPanel.hidden;
    if (!membersPanel.hidden) await loadMemberPicker();
  });
  document.getElementById('member-picker').addEventListener('change', async event => {
    if (!event.target.matches('input[type=checkbox]:checked')) return;
    const response = await fetch(`${api}/conversations/${encodeURIComponent(conversationId)}/members`, {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
      body: JSON.stringify({user_ids: [event.target.value]}),
    });
    const body = await response.json();
    if (!response.ok) setError(body.error || 'Could not add member.'); else await resync();
    event.target.checked = false;
  });

  createOptionEditors(['Yes', 'No']);
  resync().catch(err => setError(err.message));
  if (typeof window.cytoscape !== 'function') {
    setError('The chat graph could not load. Check the network connection and try again.');
  } else if (realtimeMode === 'supabase') {
    setupSupabaseRealtime();
  } else if (realtimeMode === 'polling') {
    startPolling();
  } else if (typeof window.io === 'function') {
    setupSocket();
  } else {
    startPolling();
  }
})();
