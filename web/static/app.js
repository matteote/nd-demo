/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/**
 * TransportGraph Console — Spanner Graph NL2GQL Web Client
 * Vanilla JS client for SSE streaming, GQL inspection, tabular export,
 * and interactive SVG topology visualization.
 */

(function () {
  'use strict';

  const state = {
    sessionId: null,
    executeQuery: true,
    showSamplePrompts: true,
    isStreaming: false,
    config: null,
    topology: null,
    selectedEntity: null,
    highlightedIds: new Set(),
  };

  // DOM References
  const elTogglePrompts = document.getElementById('toggle-sample-prompts');
  const elToggleExecute = document.getElementById('toggle-execute-query');
  const elToggleExecuteLabel = document.getElementById('toggle-execute-label');
  const elBtnToggleTopology = document.getElementById('btn-toggle-topology');
  const elBtnCollapseTopology = document.getElementById('btn-collapse-topology');
  const elBtnClearHighlights = document.getElementById('btn-clear-highlights');
  const elBtnNewSession = document.getElementById('btn-new-session');
  const elBtnToggleSidebar = document.getElementById('btn-toggle-sidebar');
  const elWorkspaceGrid = document.getElementById('workspace-grid');
  const elSidebar = document.getElementById('sidebar');
  const elPromptCategories = document.getElementById('prompt-categories');
  const elTopologyPanel = document.getElementById('topology-panel');
  const elTopologySvg = document.getElementById('topology-svg');
  const elEntityInspector = document.getElementById('entity-inspector');
  const elInspectorBadge = document.getElementById('inspector-badge');
  const elInspectorName = document.getElementById('inspector-name');
  const elInspectorMeta = document.getElementById('inspector-meta');
  const elBtnCloseInspector = document.getElementById('btn-close-inspector');
  const elBtnInspectQuery = document.getElementById('btn-inspect-query');
  const elBtnInspectOutage = document.getElementById('btn-inspect-outage');
  const elChatMessages = document.getElementById('chat-messages');
  const elChatForm = document.getElementById('chat-form');
  const elChatInput = document.getElementById('chat-input');
  const elBtnSend = document.getElementById('btn-send');
  const elSessionIndicator = document.getElementById('session-indicator');

  const CSRF_HEADERS = {
    'Content-Type': 'application/json',
    'X-Requested-With': 'spanner-graph-web-ui',
  };

  // =========================================================================
  // Initialization
  // =========================================================================
  async function init() {
    bindEvents();
    renderWelcomeState();

    try {
      const [cfgResp, topoResp] = await Promise.all([
        fetch('/api/config'),
        fetch('/api/topology'),
      ]);
      if (cfgResp.ok) {
        state.config = await cfgResp.json();
        applyConfigToUI(state.config);
      }
      if (topoResp.ok) {
        state.topology = await topoResp.json();
        renderTopologySvg(state.topology);
      }
      await createNewSession(false);
    } catch (err) {
      console.error('Initialization error:', err);
    }
  }

  function applyConfigToUI(cfg) {
    state.executeQuery =
      cfg.query_data_execute_query !== undefined
        ? Boolean(cfg.query_data_execute_query)
        : true;
    elToggleExecute.checked = state.executeQuery;
    updateExecuteToggleLabel();

    state.showSamplePrompts =
      cfg.show_sample_prompts !== undefined
        ? Boolean(cfg.show_sample_prompts)
        : true;
    if (elTogglePrompts) {
      elTogglePrompts.checked = state.showSamplePrompts;
    }

    renderSidebarPrompts(cfg.sample_prompts || []);
    renderWelcomeState(cfg.sample_prompts || []);
    applySamplePromptsVisibility();
  }

  function updateExecuteToggleLabel() {
    elToggleExecuteLabel.textContent = state.executeQuery
      ? 'QueryData Direct'
      : '2-Step (Query + Spanner)';
  }

  function applySamplePromptsVisibility() {
    if (elWorkspaceGrid) {
      elWorkspaceGrid.classList.toggle('prompts-hidden', !state.showSamplePrompts);
    }
    const starterGrid = document.getElementById('starter-grid');
    if (starterGrid) {
      starterGrid.hidden = !state.showSamplePrompts;
    }
  }

  // =========================================================================
  // Sidebar Sample Prompts & Welcome State
  // =========================================================================
  function renderSidebarPrompts(categories) {
    elPromptCategories.innerHTML = '';
    categories.forEach((cat) => {
      const group = document.createElement('div');
      group.className = 'prompt-category-group';

      const title = document.createElement('div');
      title.className = 'prompt-category-title';
      title.textContent = cat.category;
      group.appendChild(title);

      (cat.prompts || []).forEach((promptText) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'prompt-item-btn';
        btn.textContent = promptText;
        btn.addEventListener('click', () => {
          elSidebar.classList.remove('open');
          submitPrompt(promptText);
        });
        group.appendChild(btn);
      });

      elPromptCategories.appendChild(group);
    });
  }

  function renderWelcomeState(categories = []) {
    if (elChatMessages.querySelector('.msg-row')) {
      return;
    }
    elChatMessages.innerHTML = '';

    const card = document.createElement('div');
    card.className = 'welcome-card';
    card.id = 'welcome-card';

    const quickStarters = [];
    categories.forEach((cat) => {
      if (cat.prompts && cat.prompts.length > 0) {
        quickStarters.push({
          category: cat.category,
          prompt: cat.prompts[0],
        });
      }
    });

    if (quickStarters.length === 0) {
      quickStarters.push(
        {
          category: 'Graph Schema & Discovery',
          prompt: 'What node types and relationship types exist in the graph?',
        },
        {
          category: 'Entity Summary',
          prompt: 'Summarize the number of nodes for each label in the graph.',
        },
        {
          category: 'Connectivity Exploration',
          prompt: 'Show a sample of connected node pairs and the edges between them.',
        },
        {
          category: 'Multi-Hop Paths',
          prompt: 'Find multi-hop paths connecting nodes in the graph.',
        }
      );
    }

    card.innerHTML = `
      <div class="welcome-header">
        <h2 class="welcome-title">Explore the Property Graph in Natural Language</h2>
      </div>
      <p class="welcome-desc">
        Ask questions about graph entities, relationships, multi-hop paths, and connected subgraphs.
        The agent translates your prompt into a query using <code>QueryData</code> and executes it against Cloud Spanner Graph.
      </p>
      <div class="starter-grid" id="starter-grid"></div>
    `;

    const grid = card.querySelector('#starter-grid');
    grid.hidden = !state.showSamplePrompts;
    quickStarters.slice(0, 4).forEach((item) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'starter-card';
      btn.innerHTML = `
        <span class="starter-card-tag">${escapeHtml(item.category)}</span>
        <div class="starter-card-text">${escapeHtml(item.prompt)}</div>
      `;
      btn.addEventListener('click', () => submitPrompt(item.prompt));
      grid.appendChild(btn);
    });

    elChatMessages.appendChild(card);
  }

  // =========================================================================
  // Interactive SVG Graph Topology Diagram (Optional)
  // =========================================================================
  function renderTopologySvg(topo) {
    if (!topo || !elTopologySvg) return;
    elTopologySvg.innerHTML = '';

    const nodes = topo.nodes || [];
    if (nodes.length === 0) {
      if (elTopologyPanel) elTopologyPanel.classList.add('collapsed');
      if (elBtnToggleTopology) elBtnToggleTopology.hidden = true;
      return;
    }

    if (elBtnToggleTopology) elBtnToggleTopology.hidden = false;
    if (elTopologyPanel) elTopologyPanel.classList.remove('collapsed');

    const nodesById = {};
    nodes.forEach((n) => {
      nodesById[n.id] = n;
    });

    const ns = 'http://www.w3.org/2000/svg';

    // 1. Render Logical Trail (dashed cyan arc) if present
    const trail = (topo.trails || [])[0];
    if (trail) {
      const trailPath = document.createElementNS(ns, 'path');
      trailPath.setAttribute(
        'd',
        'M 90 155 Q 370 55 650 155'
      );
      trailPath.setAttribute('class', 'svg-trail-path');
      trailPath.setAttribute('data-entity-id', trail.id);
      trailPath.addEventListener('click', () => selectTopologyEntity(trail, 'LogicalLink'));
      elTopologySvg.appendChild(trailPath);

      const trailLabel = document.createElementNS(ns, 'text');
      trailLabel.setAttribute('x', '370');
      trailLabel.setAttribute('y', '90');
      trailLabel.setAttribute('class', 'svg-link-label');
      trailLabel.style.fill = 'var(--accent-cyan)';
      trailLabel.textContent = `${trail.name} (${trail.id})`;
      elTopologySvg.appendChild(trailLabel);
    }

    // 2. Render Physical Links
    (topo.links || []).forEach((link) => {
      const src = nodesById[link.source_ne];
      const dst = nodesById[link.target_ne];
      if (!src || !dst) return;

      const g = document.createElementNS(ns, 'g');
      g.setAttribute('class', 'svg-link-group');
      g.setAttribute('data-entity-id', link.id);
      g.addEventListener('click', () => selectTopologyEntity(link, 'PhysicalLink'));

      if (src.id === dst.id) {
        // Internal self-loop
        const loop = document.createElementNS(ns, 'path');
        loop.setAttribute(
          'd',
          `M ${src.x - 18} ${src.y + 18} C ${src.x - 68} ${src.y + 70}, ${src.x + 40} ${src.y + 75}, ${src.x + 12} ${src.y + 22}`
        );
        loop.setAttribute('fill', 'none');
        loop.setAttribute('class', 'svg-link-line');
        g.appendChild(loop);

        const lbl = document.createElementNS(ns, 'text');
        lbl.setAttribute('x', String(src.x - 10));
        lbl.setAttribute('y', String(src.y + 72));
        lbl.setAttribute('class', 'svg-link-label');
        lbl.textContent = link.id;
        g.appendChild(lbl);
      } else {
        const line = document.createElementNS(ns, 'line');
        line.setAttribute('x1', String(src.x));
        line.setAttribute('y1', String(src.y));
        line.setAttribute('x2', String(dst.x));
        line.setAttribute('y2', String(dst.y));
        line.setAttribute('class', 'svg-link-line');
        g.appendChild(line);

        const midX = (src.x + dst.x) / 2;
        const midY = (src.y + dst.y) / 2;
        const lbl = document.createElementNS(ns, 'text');
        lbl.setAttribute('x', String(midX + (src.x === dst.x ? 42 : 0)));
        lbl.setAttribute('y', String(midY + (src.x === dst.x ? 4 : -10)));
        lbl.setAttribute('class', 'svg-link-label');
        lbl.textContent = link.id;
        g.appendChild(lbl);
      }

      elTopologySvg.appendChild(g);
    });

    // 3. Render Graph Nodes
    nodes.forEach((node) => {
      const g = document.createElementNS(ns, 'g');
      g.setAttribute('class', 'svg-ne-group');
      g.setAttribute('data-entity-id', node.id);
      g.addEventListener('click', () => selectTopologyEntity(node, 'Node'));

      const circle = document.createElementNS(ns, 'circle');
      circle.setAttribute('cx', String(node.x));
      circle.setAttribute('cy', String(node.y));
      circle.setAttribute('r', '24');
      circle.setAttribute('class', 'svg-ne-circle');
      g.appendChild(circle);

      const title = document.createElementNS(ns, 'text');
      title.setAttribute('x', String(node.x));
      title.setAttribute('y', String(node.y + 4));
      title.setAttribute('class', 'svg-ne-title');
      title.textContent = node.short_name || node.name || node.id;
      g.appendChild(title);

      const sub = document.createElementNS(ns, 'text');
      sub.setAttribute('x', String(node.x));
      sub.setAttribute('y', String(node.y + 40));
      sub.setAttribute('class', 'svg-ne-id');
      sub.textContent = node.id;
      g.appendChild(sub);

      elTopologySvg.appendChild(g);
    });

    applyTopologyHighlights();
  }

  function selectTopologyEntity(entity, kind) {
    state.selectedEntity = { entity, kind };
    elEntityInspector.hidden = false;
    elInspectorBadge.textContent = kind;
    elInspectorName.textContent = entity.name || entity.id;

    const lines = [`<div><strong>ID:</strong> <code>${escapeHtml(entity.id)}</code></div>`];
    if (kind === 'Node') {
      const ports = (state.topology.ports || []).filter((p) => p.ne_id === entity.id);
      const tps = (state.topology.termination_points || []).filter((t) => t.ne_id === entity.id);
      if (entity.vendor || entity.type) {
        lines.push(`<div><strong>Type:</strong> ${escapeHtml(entity.vendor || '')} ${escapeHtml(entity.type || '')}</div>`);
      }
      if (ports.length || tps.length) {
        lines.push(`<div><strong>Endpoints:</strong> ${ports.length + tps.length} attached</div>`);
      }
    } else if (kind === 'PhysicalLink') {
      if (entity.ports && entity.ports.length) {
        lines.push(`<div><strong>Endpoints:</strong> <code>${escapeHtml(entity.ports.join(', '))}</code></div>`);
      }
      if (entity.carries_trail) {
        lines.push(`<div><strong>Carries:</strong> <code>${escapeHtml(entity.carries_trail)}</code></div>`);
      }
    } else if (kind === 'LogicalLink') {
      if (entity.sections && entity.sections.length) {
        lines.push(`<div><strong>Links:</strong> ${entity.sections.length} underlying links</div>`);
      }
      if (entity.termination_points && entity.termination_points.length) {
        lines.push(`<div><strong>Endpoints:</strong> <code>${escapeHtml(entity.termination_points.join(', '))}</code></div>`);
      }
    }
    elInspectorMeta.innerHTML = lines.join('');
  }

  function highlightEntities(entityIds) {
    if (!Array.isArray(entityIds) || entityIds.length === 0) return;

    entityIds.forEach((id) => state.highlightedIds.add(id));

    // Also map port/TP IDs to their parent Ne so the node lights up too
    if (state.topology) {
      (state.topology.ports || []).forEach((p) => {
        if (state.highlightedIds.has(p.id)) {
          state.highlightedIds.add(p.ne_id);
        }
      });
      (state.topology.termination_points || []).forEach((tp) => {
        if (state.highlightedIds.has(tp.id)) {
          state.highlightedIds.add(tp.ne_id);
        }
      });
    }

    applyTopologyHighlights();
  }

  function applyTopologyHighlights() {
    if (!elTopologySvg) return;
    const allItems = elTopologySvg.querySelectorAll('[data-entity-id]');
    allItems.forEach((el) => {
      const id = el.getAttribute('data-entity-id');
      if (state.highlightedIds.has(id)) {
        el.classList.add('highlighted');
      } else {
        el.classList.remove('highlighted');
      }
    });
    elBtnClearHighlights.hidden = state.highlightedIds.size === 0;
  }

  function clearTopologyHighlights() {
    state.highlightedIds.clear();
    applyTopologyHighlights();
  }

  // =========================================================================
  // Session & Chat Streaming (SSE)
  // =========================================================================
  async function createNewSession(resetUI = true) {
    try {
      const resp = await fetch('/api/sessions', {
        method: 'POST',
        headers: CSRF_HEADERS,
        body: JSON.stringify({ execute_query: state.executeQuery }),
      });
      if (resp.ok) {
        const data = await resp.json();
        state.sessionId = data.session_id;
        elSessionIndicator.textContent = `Session: ${state.sessionId.slice(0, 8)}`;
      }
    } catch (err) {
      console.error('Failed to create session:', err);
    }

    if (resetUI) {
      clearTopologyHighlights();
      elChatMessages.innerHTML = '';
      renderWelcomeState(state.config ? state.config.sample_prompts : []);
    }
  }

  async function submitPrompt(promptText) {
    const trimmed = (promptText || '').trim();
    if (!trimmed || state.isStreaming) return;

    const welcomeCard = document.getElementById('welcome-card');
    if (welcomeCard) {
      welcomeCard.remove();
    }

    clearTopologyHighlights();
    elChatInput.value = '';
    elChatInput.style.height = 'auto';

    appendUserMessage(trimmed);
    const assistantTurn = createAssistantTurnElement();
    scrollToBottom();

    state.isStreaming = true;
    elBtnSend.disabled = true;

    let accumulatedMarkdown = '';
    const toolPillsByCallId = {};

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: CSRF_HEADERS,
        body: JSON.stringify({
          session_id: state.sessionId,
          message: trimmed,
          execute_query: state.executeQuery,
        }),
      });

      if (!response.ok) {
        const errText = await response.text();
        throw new Error(`HTTP ${response.status}: ${errText}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const parts = buffer.split('\n\n');
        buffer = parts.pop() || '';

        for (const rawEvent of parts) {
          const line = rawEvent.trim();
          if (!line.startsWith('data:')) continue;
          const jsonStr = line.slice(5).trim();
          if (!jsonStr) continue;

          let evt;
          try {
            evt = JSON.parse(jsonStr);
          } catch (e) {
            continue;
          }

          handleStreamEvent(evt, assistantTurn, toolPillsByCallId, (newText, isPartial) => {
            if (isPartial) {
              accumulatedMarkdown += newText;
            } else if (!accumulatedMarkdown) {
              accumulatedMarkdown = newText;
            } else if (!accumulatedMarkdown.endsWith(newText)) {
              accumulatedMarkdown += newText;
            }
            assistantTurn.markdownEl.innerHTML = renderMarkdown(accumulatedMarkdown);
          });
          scrollToBottom();
        }
      }
    } catch (err) {
      renderErrorCard(
        assistantTurn.artifactsEl,
        err.message || 'Network request failed.',
        'Check that the server is running and run `uv run python scripts/doctor.py`.'
      );
    } finally {
      state.isStreaming = false;
      elBtnSend.disabled = false;
      elChatInput.focus();
    }
  }

  function handleStreamEvent(evt, assistantTurn, toolPillsByCallId, onText) {
    switch (evt.type) {
      case 'session':
        state.sessionId = evt.session_id;
        elSessionIndicator.textContent = `Session: ${evt.session_id.slice(0, 8)}`;
        break;

      case 'tool_call': {
        const pill = document.createElement('span');
        pill.className = 'tool-pill running';
        pill.innerHTML = `<span class="spinner"></span><span>${escapeHtml(evt.name)}</span>`;
        assistantTurn.toolsEl.appendChild(pill);
        toolPillsByCallId[evt.id || evt.name] = pill;
        break;
      }

      case 'tool_result': {
        const pill = toolPillsByCallId[evt.id || evt.name];
        const extracted = evt.extracted || {};
        if (pill) {
          const hasError = Boolean(extracted.error);
          pill.className = `tool-pill ${hasError ? 'error' : 'done'}`;
          pill.innerHTML = `<span>${hasError ? '✗' : '✓'}</span><span>${escapeHtml(evt.name)}</span>`;
        }

        if (extracted.gql || extracted.executed_sql) {
          renderGqlCard(
            assistantTurn.artifactsEl,
            extracted.gql || extracted.executed_sql,
            extracted.intent_explanation,
            'Generated query'
          );
        }

        if (extracted.disambiguation) {
          renderDisambiguationCard(assistantTurn.artifactsEl, extracted.disambiguation);
        }

        if (extracted.table) {
          renderResultTableCard(assistantTurn.artifactsEl, extracted.table);
        }

        if (extracted.error) {
          renderErrorCard(assistantTurn.artifactsEl, extracted.error);
        }

        if (extracted.highlighted_entities) {
          highlightEntities(extracted.highlighted_entities);
        }
        break;
      }

      case 'text':
        onText(evt.content || '', Boolean(evt.partial));
        break;

      case 'done':
        if (evt.duration_ms) {
          assistantTurn.latencyEl.textContent = `${(evt.duration_ms / 1000).toFixed(1)}s`;
        }
        break;

      case 'error':
        renderErrorCard(assistantTurn.artifactsEl, evt.message, evt.remediation);
        break;
    }
  }

  // =========================================================================
  // DOM Builders for Chat Cards (Generated Query, Result Tables, CSV Export)
  // =========================================================================
  function appendUserMessage(text) {
    const row = document.createElement('div');
    row.className = 'msg-row';
    const bubble = document.createElement('div');
    bubble.className = 'msg-user';
    bubble.textContent = text;
    row.appendChild(bubble);
    elChatMessages.appendChild(row);
  }

  function createAssistantTurnElement() {
    const row = document.createElement('div');
    row.className = 'msg-row';

    const card = document.createElement('div');
    card.className = 'msg-assistant';

    const metaBar = document.createElement('div');
    metaBar.className = 'msg-meta-bar';
    metaBar.innerHTML = `
      <span class="msg-author">
        <span class="msg-author-dot"></span>
        <span>Spanner Graph Agent</span>
      </span>
      <span class="msg-latency"></span>
    `;

    const toolsEl = document.createElement('div');
    toolsEl.className = 'tool-steps';

    const artifactsEl = document.createElement('div');
    artifactsEl.style.display = 'flex';
    artifactsEl.style.flexDirection = 'column';
    artifactsEl.style.gap = '10px';

    const markdownEl = document.createElement('div');
    markdownEl.className = 'msg-markdown';

    card.appendChild(metaBar);
    card.appendChild(toolsEl);
    card.appendChild(artifactsEl);
    card.appendChild(markdownEl);
    row.appendChild(card);
    elChatMessages.appendChild(row);

    return {
      row,
      card,
      toolsEl,
      artifactsEl,
      markdownEl,
      latencyEl: metaBar.querySelector('.msg-latency'),
    };
  }

  function renderGqlCard(container, gqlQuery, intentExplanation, label) {
    // Avoid duplicating identical query card in the same turn
    const existing = container.querySelector('[data-gql-code]');
    if (existing && existing.getAttribute('data-gql-code') === gqlQuery.trim()) {
      return;
    }

    const card = document.createElement('div');
    card.className = 'gql-card';
    card.setAttribute('data-gql-code', gqlQuery.trim());

    const header = document.createElement('div');
    header.className = 'gql-card-header';

    const title = document.createElement('span');
    title.className = 'gql-card-title';
    title.textContent = label || 'Generated query';

    const copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.className = 'btn-xs';
    copyBtn.textContent = 'Copy query';
    copyBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(gqlQuery);
      copyBtn.textContent = 'Copied!';
      setTimeout(() => {
        copyBtn.textContent = 'Copy query';
      }, 1600);
    });

    header.appendChild(title);
    header.appendChild(copyBtn);
    card.appendChild(header);

    const pre = document.createElement('pre');
    pre.className = 'gql-code-pre';
    pre.textContent = gqlQuery.trim();
    card.appendChild(pre);

    if (intentExplanation) {
      const intent = document.createElement('div');
      intent.className = 'gql-intent';
      intent.innerHTML = `<strong>Query Intent:</strong> ${escapeHtml(intentExplanation)}`;
      card.appendChild(intent);
    }

    container.appendChild(card);
  }

  function renderResultTableCard(container, tableData) {
    const cols = tableData.columns || [];
    const rows = tableData.rows || [];
    if (cols.length === 0 && rows.length === 0) return;

    const card = document.createElement('div');
    card.className = 'result-table-card';

    const header = document.createElement('div');
    header.className = 'result-table-header';
    header.innerHTML = `<span>Spanner Graph Query Results · <strong>${rows.length}</strong> row(s)</span>`;

    const csvBtn = document.createElement('button');
    csvBtn.type = 'button';
    csvBtn.className = 'btn-xs';
    csvBtn.textContent = 'Export CSV';
    csvBtn.addEventListener('click', () => exportTableToCsv(cols, rows));
    header.appendChild(csvBtn);
    card.appendChild(header);

    const scrollWrap = document.createElement('div');
    scrollWrap.className = 'result-table-scroll';

    const table = document.createElement('table');
    table.className = 'result-table';

    if (cols.length > 0) {
      const thead = document.createElement('thead');
      const tr = document.createElement('tr');
      cols.forEach((c) => {
        const th = document.createElement('th');
        th.textContent = c;
        tr.appendChild(th);
      });
      thead.appendChild(tr);
      table.appendChild(thead);
    }

    const tbody = document.createElement('tbody');
    rows.forEach((r) => {
      const tr = document.createElement('tr');
      (Array.isArray(r) ? r : [r]).forEach((cell) => {
        const td = document.createElement('td');
        td.textContent = cell === null || cell === undefined ? '' : String(cell);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);

    scrollWrap.appendChild(table);
    card.appendChild(scrollWrap);
    container.appendChild(card);
  }

  function renderDisambiguationCard(container, disambiguationText) {
    const box = document.createElement('div');
    box.className = 'disambiguation-box';
    box.innerHTML = `<strong>Clarification Suggested:</strong> ${escapeHtml(disambiguationText)}`;
    container.appendChild(box);
  }

  function renderErrorCard(container, message, remediation) {
    const box = document.createElement('div');
    box.className = 'msg-error';
    box.innerHTML = `
      <div><strong>Error:</strong> ${escapeHtml(message)}</div>
      ${remediation ? `<div style="margin-top:4px;opacity:0.85">${escapeHtml(remediation)}</div>` : ''}
    `;
    container.appendChild(box);
  }

  function exportTableToCsv(cols, rows) {
    const escapeCsv = (val) => {
      const s = val === null || val === undefined ? '' : String(val);
      return `"${s.replace(/"/g, '""')}"`;
    };
    const lines = [];
    if (cols.length > 0) {
      lines.push(cols.map(escapeCsv).join(','));
    }
    rows.forEach((r) => {
      lines.push((Array.isArray(r) ? r : [r]).map(escapeCsv).join(','));
    });
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `transport_graph_results_${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  // =========================================================================
  // Lightweight XSS-Safe Markdown Formatter
  // =========================================================================
  function escapeHtml(str) {
    return String(str ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function renderInlineMarkdown(escapedLine) {
    return escapedLine
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/`([^`]+)`/g, '<code>$1</code>');
  }

  function renderMarkdown(rawText) {
    if (!rawText) return '';
    const segments = rawText.split(/(```[\s\S]*?```)/g);
    let html = '';

    for (const seg of segments) {
      if (seg.startsWith('```') && seg.endsWith('```')) {
        const firstNewline = seg.indexOf('\n');
        const codeBody =
          firstNewline !== -1 ? seg.slice(firstNewline + 1, -3) : seg.slice(3, -3);
        html += `<pre><code>${escapeHtml(codeBody.trim())}</code></pre>`;
        continue;
      }

      const lines = seg.split('\n');
      let inList = false;
      let inTable = false;

      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const trimmed = line.trim();

        // Markdown table detection
        if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
          if (/^\|[\s\-:|]+\|$/.test(trimmed)) {
            continue; // separator row
          }
          if (inList) {
            html += '</ul>';
            inList = false;
          }
          const cells = trimmed
            .slice(1, -1)
            .split('|')
            .map((c) => renderInlineMarkdown(escapeHtml(c.trim())));
          if (!inTable) {
            html += '<table><thead><tr>';
            cells.forEach((c) => {
              html += `<th>${c}</th>`;
            });
            html += '</tr></thead><tbody>';
            inTable = true;
          } else {
            html += '<tr>';
            cells.forEach((c) => {
              html += `<td>${c}</td>`;
            });
            html += '</tr>';
          }
          continue;
        } else if (inTable) {
          html += '</tbody></table>';
          inTable = false;
        }

        // Bullet list detection
        if (/^[-*]\s+/.test(trimmed)) {
          if (!inList) {
            html += '<ul>';
            inList = true;
          }
          const itemText = trimmed.replace(/^[-*]\s+/, '');
          html += `<li>${renderInlineMarkdown(escapeHtml(itemText))}</li>`;
          continue;
        } else if (inList) {
          html += '</ul>';
          inList = false;
        }

        // Headings
        if (/^###\s+/.test(trimmed)) {
          html += `<h4>${renderInlineMarkdown(escapeHtml(trimmed.slice(4)))}</h4>`;
        } else if (/^##\s+/.test(trimmed)) {
          html += `<h3>${renderInlineMarkdown(escapeHtml(trimmed.slice(3)))}</h3>`;
        } else if (trimmed.length > 0) {
          html += `<p>${renderInlineMarkdown(escapeHtml(trimmed))}</p>`;
        }
      }

      if (inList) html += '</ul>';
      if (inTable) html += '</tbody></table>';
    }

    return html;
  }

  function scrollToBottom() {
    elChatMessages.scrollTop = elChatMessages.scrollHeight;
  }

  // =========================================================================
  // Event Listeners
  // =========================================================================
  function bindEvents() {
    elChatForm.addEventListener('submit', (e) => {
      e.preventDefault();
      submitPrompt(elChatInput.value);
    });

    elChatInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        submitPrompt(elChatInput.value);
      }
    });

    elChatInput.addEventListener('input', () => {
      elChatInput.style.height = 'auto';
      elChatInput.style.height = `${Math.min(elChatInput.scrollHeight, 130)}px`;
    });

    if (elTogglePrompts) {
      elTogglePrompts.addEventListener('change', () => {
        state.showSamplePrompts = elTogglePrompts.checked;
        applySamplePromptsVisibility();
      });
    }

    elToggleExecute.addEventListener('change', () => {
      state.executeQuery = elToggleExecute.checked;
      updateExecuteToggleLabel();
    });

    elBtnNewSession.addEventListener('click', () => {
      createNewSession(true);
    });

    elBtnToggleTopology.addEventListener('click', () => {
      elTopologyPanel.classList.toggle('collapsed');
    });

    elBtnCollapseTopology.addEventListener('click', () => {
      elTopologyPanel.classList.add('collapsed');
    });

    elBtnClearHighlights.addEventListener('click', () => {
      clearTopologyHighlights();
    });

    elBtnCloseInspector.addEventListener('click', () => {
      elEntityInspector.hidden = true;
    });

    elBtnInspectQuery.addEventListener('click', () => {
      if (!state.selectedEntity) return;
      const { entity } = state.selectedEntity;
      elEntityInspector.hidden = true;
      submitPrompt(
        `Show all properties and connected neighbors for ${entity.name || entity.id} (${entity.id}).`
      );
    });

    elBtnInspectOutage.addEventListener('click', () => {
      if (!state.selectedEntity) return;
      const { entity } = state.selectedEntity;
      elEntityInspector.hidden = true;
      submitPrompt(
        `Which connected nodes and links are affected if ${entity.name || entity.id} (${entity.id}) is unavailable?`
      );
    });

    if (elBtnToggleSidebar) {
      elBtnToggleSidebar.addEventListener('click', () => {
        elSidebar.classList.toggle('open');
      });
    }
  }

  document.addEventListener('DOMContentLoaded', init);
})();
