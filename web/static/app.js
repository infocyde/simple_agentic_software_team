// Agentic Software Team - Frontend Application

class AgenticTeamApp {
    constructor() {
        this.currentProject = null;
        this.ws = null;
        this.messageType = null;
        this.conversationActive = false;
        this.waitingForInput = false;
        this.workInProgress = false;
        this.activeAgents = new Set();
        this.uatActive = false;
        this.launchWindows = {};

        this.init();
    }

    init() {
        this.connectWebSocket();
        this.bindEvents();
        this.initSplash();
        this.initDebugMode();
    }

    async initDebugMode() {
        try {
            const res = await fetch('/api/config');
            const config = await res.json();
            const enabled = config.debug?.enabled || false;

            const toggle = document.getElementById('debugToggle');
            if (toggle) toggle.checked = enabled;

            const debugTabBtn = document.getElementById('debugTabBtn');
            if (debugTabBtn) {
                debugTabBtn.style.display = enabled ? 'inline-block' : 'none';
            }

            const output = document.getElementById('debugOutput');
            if (output && enabled) {
                output.innerHTML = '<p style="color: #666;">Debug mode enabled. Waiting for work to start...</p>';
            }
        } catch (error) {
            console.error('Error initializing debug mode:', error);
        }
    }

    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleWebSocketMessage(data);
        };

        this.ws.onclose = () => {
            // Reconnect after 2 seconds
            setTimeout(() => this.connectWebSocket(), 2000);
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }

    handleWebSocketMessage(data) {
        console.log('WS message:', data);

        // Handle different message types
        switch (data.type) {
            case 'agent_message':
                this.addChatMessage(data.agent, data.message, 'agent');
                this.setWaitingForInput(true, data.agent);
                break;

            case 'agent_thinking':
                this.showThinkingIndicator(data.agent);
                break;

            case 'conversation_complete':
                this.addChatMessage('system', data.message || 'Conversation complete. Documents have been updated.', 'system');
                this.setWaitingForInput(false);
                this.conversationActive = false;
                document.getElementById('writeSpecBtn').style.display = 'none';
                this.updateWorkButtons();
                this.loadProjectData(); // Refresh spec and todo
                break;

            case 'work_complete':
                this.workInProgress = false;
                this.clearActiveAgents();
                this.updateWorkButtons();
                this.addActivityItem({
                    agent: 'system',
                    action: data.message || 'Work completed',
                    timestamp: new Date().toISOString()
                });
                this.loadProjectData();
                this.showCompletionToast(data.message || 'All tasks completed!');
                this.showBrowserNotification('Project Complete', data.message || 'All tasks have been completed.');
                this.loadAndShowSummary();
                break;

            case 'work_paused':
                this.workInProgress = false;
                this.clearActiveAgents();
                this.updateWorkButtons();
                this.addActivityItem({
                    agent: 'system',
                    action: data.message || 'Work paused - ready to resume',
                    timestamp: new Date().toISOString()
                });
                break;

            case 'work_stopped':
                this.workInProgress = false;
                this.conversationActive = false;
                this.uatActive = false;
                this.clearActiveAgents();
                this.updateWorkButtons();
                this.addActivityItem({
                    agent: 'system',
                    action: data.message || 'Work force-stopped',
                    timestamp: new Date().toISOString()
                });
                break;

            case 'critical_error':
                this.workInProgress = false;
                this.clearActiveAgents();
                this.updateWorkButtons();
                this.showErrorModal(data.message || 'An unexpected error occurred');
                break;

            case 'info':
                this.addActivityItem({
                    agent: 'system',
                    action: data.message,
                    timestamp: new Date().toISOString()
                });
                break;

            case 'project_deleted':
                // Remove from sidebar and reset view if it was selected
                const deletedItem = document.querySelector(`.project-item[data-name="${data.project}"]`);
                if (deletedItem) deletedItem.remove();
                if (this.currentProject === data.project) {
                    this.currentProject = null;
                    document.getElementById('projectView').style.display = 'none';
                    document.getElementById('noProjectSelected').style.display = 'block';
                }
                break;

            case 'agent_start':
                this.addActiveAgent(data.agent);
                break;

            case 'agent_complete':
                this.removeActiveAgent(data.agent);
                break;

            case 'work_started':
                this.workInProgress = true;
                this.updateWorkButtons();
                this.updateActivityIndicator();
                break;

            case 'activity':
                this.handleActivity(data);
                break;

            case 'error':
                this.addChatMessage('system', `Error: ${data.message}`, 'system');
                this.setWaitingForInput(false);
                break;

            case 'user_escalation':
                this.handleTaskEscalation(data);
                break;

            case 'status_change':
                this.handleStatusChange(data);
                break;

            case 'uat_ready':
                this.handleUatReady(data);
                break;

            case 'uat_complete':
                this.handleUatComplete(data);
                break;

            case 'debug_output':
                this.appendDebugLine(data.agent, data.line);
                break;

            default:
                // Legacy activity format
                if (data.agent && data.action) {
                    this.handleActivity(data);
                }
        }
    }

    handleActivity(data) {
        // Update agent status
        if (data.agent) {
            this.updateAgentStatus(data.agent, 'working');
            setTimeout(() => this.updateAgentStatus(data.agent, 'idle'), 3000);
        }

        // Add to activity feed if for current project
        if (data.project === this.currentProject || !data.project) {
            this.addActivityItem(data);
        }

        // Refresh project data on file writes (slight delay to batch rapid updates)
        if (data.action && data.action.includes('Wrote file')) {
            setTimeout(() => this.loadProjectData(), 150);
        }
        // Refresh immediately on task completion
        if (data.action && data.action.includes('Task completed')) {
            this.loadProjectData();
        }
    }

    bindEvents() {
        // Project selection
        document.querySelectorAll('.project-item').forEach(item => {
            item.addEventListener('click', () => this.selectProject(item.dataset.name));
        });

        // New project button
        document.getElementById('newProjectBtn').addEventListener('click', () => this.showNewProjectModal());
        document.getElementById('cancelNewProject').addEventListener('click', () => this.hideModals());
        document.getElementById('newProjectForm').addEventListener('submit', (e) => this.createProject(e));

        // Project actions
        document.getElementById('kickoffBtn').addEventListener('click', () => this.showMessageModal('kickoff'));
        document.getElementById('featureBtn').addEventListener('click', () => this.showMessageModal('feature'));
        document.getElementById('startWorkBtn').addEventListener('click', () => this.startWork());
        document.getElementById('pauseBtn').addEventListener('click', () => this.pauseWork());
        document.getElementById('forceStopBtn').addEventListener('click', () => this.forceStopWork());
        document.getElementById('changeStatusBtn').addEventListener('click', () => this.showChangeStatusModal());
        document.getElementById('writeSpecBtn').addEventListener('click', () => this.writeSpec());
        document.getElementById('startUatBtn').addEventListener('click', () => this.startUat());
        document.getElementById('completeUatBtn').addEventListener('click', () => this.completeUat());
        document.getElementById('launchProjectBtn').addEventListener('click', () => this.launchProject());
        document.getElementById('stopLaunchBtn').addEventListener('click', () => this.stopLaunch());
        document.getElementById('launchLogBtn').addEventListener('click', () => this.showLaunchLogModal());
        document.getElementById('zipProjectBtn').addEventListener('click', () => this.zipProject());
        document.getElementById('deleteProjectBtn').addEventListener('click', () => this.deleteProject());
        document.getElementById('openRunitBtn').addEventListener('click', () => this.showRunitModal());
        document.getElementById('closeRunitModal').addEventListener('click', () => {
            this.hideModals();
            this.clearRunitWarning();
        });
        document.getElementById('closeLaunchLogModal').addEventListener('click', () => this.hideModals());
        document.getElementById('cancelMessage').addEventListener('click', () => this.hideModals());
        document.getElementById('messageForm').addEventListener('submit', (e) => this.startConversation(e));
        document.getElementById('saveGatesBtn').addEventListener('click', () => this.saveQualityGates());
        document.getElementById('debugToggle').addEventListener('change', (e) => this.toggleDebugMode(e.target.checked));
        document.getElementById('cancelChangeStatus').addEventListener('click', () => this.hideModals());
        document.getElementById('changeStatusForm').addEventListener('submit', (e) => this.changeProjectStatus(e));

        // Chat form
        document.getElementById('chatForm').addEventListener('submit', (e) => this.sendChatMessage(e));

        // Tabs
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', () => this.switchTab(tab.dataset.tab));
        });

        // Close modals on overlay click
        document.getElementById('modalOverlay').addEventListener('click', (e) => {
            if (e.target.id === 'modalOverlay') {
                this.hideModals();
            }
        });

        // Error modal dismiss
        document.getElementById('dismissError').addEventListener('click', () => this.hideModals());

        // Enter key in chat
        document.getElementById('chatInput').addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                document.getElementById('chatForm').dispatchEvent(new Event('submit'));
            }
        });
    }

    async selectProject(name) {
        this.currentProject = name;

        // Update UI
        document.querySelectorAll('.project-item').forEach(item => {
            item.classList.toggle('active', item.dataset.name === name);
        });

        this.clearRunitWarning();
        document.getElementById('noProjectSelected').style.display = 'none';
        document.getElementById('projectView').style.display = 'block';
        document.getElementById('projectTitle').textContent = name;

        // Reset chat
        this.clearChat();
        this.conversationActive = false;
        this.setWaitingForInput(false);
        this.updateWorkButtons();

        // Load project data
        await this.loadProjectData();
    }

    async loadProjectData() {
        if (!this.currentProject) return;

        try {
            // Load spec
            const specRes = await fetch(`/api/projects/${this.currentProject}/spec`);
            const specData = await specRes.json();
            document.getElementById('specContent').textContent = specData.spec || 'No specification yet.';

            // Load TODO
            const todoRes = await fetch(`/api/projects/${this.currentProject}/todo`);
            const todoData = await todoRes.json();
            document.getElementById('todoContent').textContent = todoData.todo || 'No tasks yet.';

            // Load activity
            const activityRes = await fetch(`/api/projects/${this.currentProject}/activity`);
            const activityData = await activityRes.json();
            this.renderActivityFeed(activityData.activity);

            // Load project status
            const statusRes = await fetch(`/api/projects/${this.currentProject}/status`);
            const statusData = await statusRes.json();
            if (statusData.status) {
                this.updateStatusDisplay(statusData.status.current_status);
            }

            // Load quality gates (per project)
            const gatesRes = await fetch(`/api/projects/${this.currentProject}/quality-gates`);
            const gatesData = await gatesRes.json();
            this.updateQualityGatesUI(gatesData.quality_gates || {});

        } catch (error) {
            console.error('Error loading project data:', error);
        }
    }

    handleStatusChange(data) {
        // Update status display
        if (data.new_status) {
            this.updateStatusDisplay(data.new_status);
        }

        // Add to activity feed
        this.addActivityItem({
            agent: 'orchestrator',
            action: `Status changed to ${data.new_status?.toUpperCase() || 'unknown'}`,
            details: data.reason || '',
            timestamp: new Date().toISOString()
        });

        // Update project list badge
        if (this.currentProject) {
            const projectItem = document.querySelector(`.project-item[data-name="${this.currentProject}"]`);
            if (projectItem) {
                projectItem.dataset.status = data.new_status;
                this.updateProjectListBadge(projectItem, data.new_status);
            }
        }
    }

    updateStatusDisplay(status) {
        // Update status badge
        const statusValue = document.getElementById('projectStatusValue');
            if (statusValue) {
                const statusLabels = {
                    'initialized': 'Initialized',
                    'wip': 'Work In Progress',
                    'testing': 'Testing',
                    'security_review': 'Security Review',
                    'qa': 'QA Testing',
                    'uat': 'User Acceptance Testing',
                    'done': 'Done'
                };
                const badgeClasses = {
                    'initialized': 'badge-new',
                    'wip': 'badge-wip',
                    'testing': 'badge-testing',
                    'security_review': 'badge-security',
                    'qa': 'badge-qa',
                    'uat': 'badge-uat',
                    'done': 'badge-done'
                };

            statusValue.textContent = statusLabels[status] || status;
            statusValue.className = `status-value badge ${badgeClasses[status] || 'badge-new'}`;
        }

        // Update timeline
        this.updateStatusTimeline(status);

        // Show/hide UAT buttons based on status
        this.updateUatButtons(status);

        // Show QA prep hint
        this.updateQaRunHint(status);

        this.clearRunitWarning();
    }

    updateStatusTimeline(currentStatus) {
        const statusOrder = ['initialized', 'wip', 'testing', 'security_review', 'qa', 'uat', 'done'];
        const currentIndex = statusOrder.indexOf(currentStatus);

        document.querySelectorAll('.status-step').forEach(step => {
            const stepStatus = step.dataset.status;
            const stepIndex = statusOrder.indexOf(stepStatus);

            step.classList.remove('active', 'completed');

            if (stepIndex < currentIndex) {
                step.classList.add('completed');
            } else if (stepIndex === currentIndex) {
                step.classList.add('active');
            }
        });
    }

    updateProjectListBadge(projectItem, status) {
        const statusSpan = projectItem.querySelector('.project-status');
        if (!statusSpan) return;

        const badges = {
            'initialized': '<span class="badge badge-new">New</span>',
            'wip': '<span class="badge badge-wip">WIP</span>',
            'testing': '<span class="badge badge-testing">Testing</span>',
            'security_review': '<span class="badge badge-security">Security</span>',
            'qa': '<span class="badge badge-qa">QA</span>',
            'uat': '<span class="badge badge-uat">UAT</span>',
            'done': '<span class="badge badge-done">Done</span>'
        };

        statusSpan.innerHTML = badges[status] || badges['initialized'];
    }

    updateUatButtons(status) {
        const startUatBtn = document.getElementById('startUatBtn');
        const completeUatBtn = document.getElementById('completeUatBtn');
        const startWorkBtn = document.getElementById('startWorkBtn');

        if (status === 'uat') {
            // Show UAT button when in UAT status
            startUatBtn.style.display = this.uatActive ? 'none' : 'inline-block';
            completeUatBtn.style.display = this.uatActive ? 'inline-block' : 'none';
            startWorkBtn.style.display = 'none';
            completeUatBtn.textContent = 'Done';
        } else {
            startUatBtn.style.display = 'none';
            completeUatBtn.style.display = 'none';
        }
    }

    updateQaRunHint(status) {
        const qaHint = document.getElementById('qaRunHint');
        if (!qaHint) return;
        qaHint.style.display = (status === 'qa' || status === 'uat') ? 'block' : 'none';
    }

    handleUatReady(data) {
        // Show notification
        this.addActivityItem({
            agent: 'system',
            action: 'Ready for User Acceptance Testing',
            details: data.message || 'Click "Start UAT" to begin your review',
            timestamp: new Date().toISOString()
        });

        // Update status display
        this.updateStatusDisplay('uat');

        // Show browser notification
        this.showBrowserNotification('UAT Ready', 'Project is ready for your acceptance testing');
    }

    handleUatComplete(data) {
        this.uatActive = false;
        this.conversationActive = false;
        this.setWaitingForInput(false);
        this.updateWorkButtons();

        // Update buttons
        document.getElementById('completeUatBtn').style.display = 'none';
        document.getElementById('completeUatBtn').textContent = 'Done';
        document.getElementById('uatHelper').style.display = 'none';

        if (data.approved) {
            this.updateStatusDisplay('done');
            this.showCompletionToast('Project approved and marked as Done!');
        } else {
            this.updateStatusDisplay('wip');
            this.addActivityItem({
                agent: 'system',
                action: 'Changes requested - returning to WIP',
                details: 'New tasks added to TODO',
                timestamp: new Date().toISOString()
            });
        }

        this.loadProjectData();
    }

    async startUat() {
        if (!this.currentProject) return;

        this.uatActive = true;
        this.conversationActive = true;
        this.updateWorkButtons();
        document.getElementById('uatHelper').style.display = 'block';

        // Switch to chat tab
        this.clearChat();
        this.switchTab('chat');

        // Update buttons
        document.getElementById('startUatBtn').style.display = 'none';
        const doneBtn = document.getElementById('completeUatBtn');
        doneBtn.style.display = 'inline-block';
        doneBtn.textContent = 'Done';

        // Show thinking indicator
        this.showThinkingIndicator('project_manager');

        try {
            const res = await fetch(`/api/projects/${this.currentProject}/uat`, {
                method: 'POST'
            });

            const data = await res.json();
            if (data.status === 'error') {
                this.addChatMessage('system', `Error: ${data.message}`, 'system');
                this.uatActive = false;
                this.updateWorkButtons();
            }
        } catch (error) {
            console.error('Error starting UAT:', error);
            this.addChatMessage('system', 'Error starting UAT conversation', 'system');
            this.uatActive = false;
            this.updateWorkButtons();
        }
    }

    async completeUat() {
        if (!this.currentProject || !this.uatActive) return;

        document.getElementById('completeUatBtn').disabled = true;
        document.getElementById('completeUatBtn').textContent = 'Completing...';

        try {
            const res = await fetch(`/api/projects/${this.currentProject}/complete-uat`, {
                method: 'POST'
            });

            const data = await res.json();
            if (data.status === 'error') {
                this.addChatMessage('system', `Error: ${data.message}`, 'system');
            }
        } catch (error) {
            console.error('Error completing UAT:', error);
            this.addChatMessage('system', 'Error completing UAT', 'system');
        } finally {
            document.getElementById('completeUatBtn').disabled = false;
            document.getElementById('completeUatBtn').textContent = 'Done';
        }
    }

    updateAgentStatus(agentName, status) {
        const agentItem = document.querySelector(`.agent-item[data-agent="${agentName}"]`);
        if (agentItem) {
            const statusEl = agentItem.querySelector('.agent-status');
            statusEl.className = `agent-status ${status}`;
            statusEl.textContent = status === 'working' ? 'Working' : 'Idle';
        }
    }

    renderActivityFeed(activities) {
        const feed = document.getElementById('activityFeed');

        if (!activities || activities.length === 0) {
            feed.innerHTML = '<p class="empty-message">No activity yet. Start a kickoff or continue work.</p>';
            return;
        }

        feed.innerHTML = activities.map(a => this.createActivityHTML(a)).join('');
        feed.scrollTop = feed.scrollHeight;
    }

    addActivityItem(activity) {
        const feed = document.getElementById('activityFeed');

        // Remove empty message if present
        const emptyMsg = feed.querySelector('.empty-message');
        if (emptyMsg) emptyMsg.remove();

        const html = this.createActivityHTML(activity);
        feed.insertAdjacentHTML('beforeend', html);
        feed.scrollTop = feed.scrollHeight;
    }

    createActivityHTML(activity) {
        const time = activity.timestamp ?
            new Date(activity.timestamp).toLocaleTimeString() :
            '';

        const agent = activity.agent || 'system';
        const details = activity.details ?
            `<div class="activity-details">${this.escapeHtml(activity.details)}</div>` :
            '';

        return `
            <div class="activity-item ${agent}">
                <div class="activity-header">
                    <span class="activity-agent">${this.formatAgentName(agent)}</span>
                    <span class="activity-time">${time}</span>
                </div>
                <div class="activity-action">${this.escapeHtml(activity.action || '')}</div>
                ${details}
            </div>
        `;
    }

    formatAgentName(name) {
        const names = {
            'project_manager': 'Project Manager',
            'software_engineer': 'Software Engineer',
            'ui_ux_engineer': 'UI/UX Engineer',
            'database_admin': 'Database Admin',
            'security_reviewer': 'Security Reviewer',
            'testing_agent': 'Testing Agent',
            'qa_tester': 'QA Tester',
            'orchestrator': 'Orchestrator',
            'system': 'System'
        };
        return names[name] || name;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    switchTab(tabName) {
        // Update tab buttons
        document.querySelectorAll('.tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.tab === tabName);
        });

        // Update tab content
        document.querySelectorAll('.tab-pane').forEach(pane => {
            pane.style.display = 'none';
        });
        document.getElementById(`${tabName}Tab`).style.display = 'block';

        this.clearRunitWarning();

        // Load log content when switching to log tab
        if (tabName === 'log') {
            this.loadLog();
        }
    }

    // Chat methods
    clearChat() {
        const messages = document.getElementById('chatMessages');
        messages.innerHTML = '<p class="empty-message">Start a kickoff or add a feature to begin chatting with the team.</p>';
    }

    addChatMessage(sender, text, type = 'agent') {
        const messages = document.getElementById('chatMessages');

        // Remove empty message if present
        const emptyMsg = messages.querySelector('.empty-message');
        if (emptyMsg) emptyMsg.remove();

        // Remove thinking indicator if present
        const thinking = messages.querySelector('.thinking-indicator');
        if (thinking) thinking.remove();

        const messageDiv = document.createElement('div');
        messageDiv.className = `chat-message ${type}`;

        if (type !== 'system') {
            messageDiv.innerHTML = `
                <div class="chat-sender">${this.formatAgentName(sender)}</div>
                <div class="chat-text">${this.escapeHtml(text)}</div>
            `;
        } else {
            messageDiv.innerHTML = `<div class="chat-text">${this.escapeHtml(text)}</div>`;
        }

        messages.appendChild(messageDiv);
        messages.scrollTop = messages.scrollHeight;
    }

    showThinkingIndicator(agent) {
        const messages = document.getElementById('chatMessages');

        // Remove existing thinking indicator
        const existing = messages.querySelector('.thinking-indicator');
        if (existing) existing.remove();

        const indicator = document.createElement('div');
        indicator.className = 'thinking-indicator';
        indicator.innerHTML = `
            <span>${this.formatAgentName(agent)} is thinking</span>
            <div class="thinking-dots">
                <span></span><span></span><span></span>
            </div>
        `;

        messages.appendChild(indicator);
        messages.scrollTop = messages.scrollHeight;
    }

    setWaitingForInput(waiting, agent = null) {
        this.waitingForInput = waiting;
        const input = document.getElementById('chatInput');
        const sendBtn = document.getElementById('chatSendBtn');
        const writeSpecBtn = document.getElementById('writeSpecBtn');
        const status = document.getElementById('chatStatus');

        input.disabled = !waiting;
        sendBtn.disabled = !waiting;

        // Show Write Spec button when conversation is active and waiting for input
        if (waiting && this.conversationActive) {
            writeSpecBtn.style.display = 'inline-block';
            writeSpecBtn.textContent = this.uatActive ? 'Update Reqs' : 'Write Spec';
        } else {
            writeSpecBtn.style.display = 'none';
        }

        if (waiting) {
            status.textContent = `Waiting for your response... (or click "Write Spec" when ready)`;
            status.className = 'chat-status waiting';
            input.focus();
        } else {
            status.textContent = '';
            status.className = 'chat-status';
        }
    }

    async sendChatMessage(e) {
        e.preventDefault();
        if (!this.waitingForInput || !this.currentProject) return;

        const input = document.getElementById('chatInput');
        const message = input.value.trim();
        if (!message) return;

        // Add user message to chat
        this.addChatMessage('You', message, 'user');
        input.value = '';
        this.setWaitingForInput(false);

        // Show thinking indicator
        this.showThinkingIndicator('project_manager');

        // Send to backend
        try {
            await fetch(`/api/projects/${this.currentProject}/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message })
            });
        } catch (error) {
            console.error('Error sending message:', error);
            this.addChatMessage('system', 'Error sending message. Please try again.', 'system');
            this.setWaitingForInput(true);
        }
    }

    // Modal methods
    showNewProjectModal() {
        document.getElementById('modalOverlay').style.display = 'flex';
        document.getElementById('newProjectModal').style.display = 'block';
        document.getElementById('fastProject').checked = false;
        document.getElementById('projectName').focus();
    }

    showMessageModal(type) {
        this.messageType = type;
        const title = type === 'kickoff' ? 'Start Project Kickoff' : 'Add Feature Request';
        const placeholder = type === 'kickoff' ?
            'Briefly describe what you want to build...' :
            'Briefly describe the feature you want to add...';

        document.getElementById('messageModalTitle').textContent = title;
        document.getElementById('messageInput').placeholder = placeholder;
        document.getElementById('messageInput').value = '';

        document.getElementById('modalOverlay').style.display = 'flex';
        document.getElementById('messageModal').style.display = 'block';
        document.getElementById('messageInput').focus();
    }

    showChangeStatusModal() {
        if (!this.currentProject) return;
        const select = document.getElementById('projectStatusSelect');
        if (select) {
            const current = document.getElementById('projectStatusValue');
            const statusLabels = {
                'Initialized': 'initialized',
                'Work In Progress': 'wip',
                'Testing': 'testing',
                'Security Review': 'security_review',
                'QA Testing': 'qa',
                'User Acceptance Testing': 'uat',
                'Done': 'done'
            };
            if (current) {
                select.value = statusLabels[current.textContent] || select.value;
            }
        }
        document.getElementById('modalOverlay').style.display = 'flex';
        document.getElementById('changeStatusModal').style.display = 'block';
        document.getElementById('projectStatusSelect').focus();
    }

    hideModals() {
        document.getElementById('modalOverlay').style.display = 'none';
        document.getElementById('newProjectModal').style.display = 'none';
        document.getElementById('messageModal').style.display = 'none';
        document.getElementById('errorModal').style.display = 'none';
        document.getElementById('changeStatusModal').style.display = 'none';
        const runitModal = document.getElementById('runitModal');
        if (runitModal) runitModal.style.display = 'none';
    }

    showErrorModal(message) {
        document.getElementById('errorMessage').textContent = message;
        document.getElementById('modalOverlay').style.display = 'flex';
        document.getElementById('errorModal').style.display = 'block';

        // Also add to activity feed
        this.addActivityItem({
            agent: 'system',
            action: 'Critical Error',
            details: message,
            timestamp: new Date().toISOString()
        });
    }

    updateActivityIndicator() {
        const indicator = document.getElementById('activityIndicator');
        const text = document.getElementById('activityText');
        const agents = document.getElementById('activityAgents');

        if (this.activeAgents.size > 0 || this.workInProgress) {
            indicator.style.display = 'flex';

            if (this.activeAgents.size > 0) {
                const agentNames = Array.from(this.activeAgents).map(a => this.formatAgentName(a));
                text.textContent = `Working... (${this.activeAgents.size} instance${this.activeAgents.size !== 1 ? 's' : ''} running)`;
                agents.textContent = agentNames.join(', ');
            } else {
                text.textContent = 'Working...';
                agents.textContent = '';
            }
        } else {
            indicator.style.display = 'none';
        }
    }

    addActiveAgent(agentName) {
        this.activeAgents.add(agentName);
        this.updateActivityIndicator();
    }

    removeActiveAgent(agentName) {
        this.activeAgents.delete(agentName);
        this.updateActivityIndicator();
    }

    clearActiveAgents() {
        this.activeAgents.clear();
        this.updateActivityIndicator();
    }

    // API methods
    async createProject(e) {
        e.preventDefault();
        const name = document.getElementById('projectName').value.trim();
        const fastProject = document.getElementById('fastProject').checked;
        if (!name) return;

        try {
            const res = await fetch('/api/projects', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, fast_project: fastProject })
            });

            const data = await res.json();

            if (data.status === 'success') {
                // Add to project list
                const list = document.getElementById('projectList');
                const li = document.createElement('li');
                li.className = 'project-item';
                li.dataset.name = data.name;
                li.innerHTML = `
                    <span class="project-name">${data.name}</span>
                    <span class="project-status">
                        <span class="badge badge-new">New</span>
                    </span>
                `;
                li.addEventListener('click', () => this.selectProject(data.name));
                list.appendChild(li);

                this.hideModals();
                this.selectProject(data.name);
            } else {
                alert(data.message || 'Error creating project');
            }
        } catch (error) {
            console.error('Error creating project:', error);
            alert('Error creating project');
        }
    }

    async startConversation(e) {
        e.preventDefault();
        const message = document.getElementById('messageInput').value.trim();
        if (!message || !this.currentProject) return;

        const endpoint = this.messageType === 'kickoff' ? 'kickoff' : 'feature';

        // Clear chat and switch to chat tab
        this.clearChat();
        this.switchTab('chat');
        this.conversationActive = true;
        this.updateWorkButtons();

        // Add initial user message
        this.addChatMessage('You', message, 'user');
        this.showThinkingIndicator('project_manager');

        this.hideModals();

        try {
            const res = await fetch(`/api/projects/${this.currentProject}/${endpoint}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message })
            });

            const data = await res.json();
            if (data.status === 'error') {
                this.addChatMessage('system', `Error: ${data.message}`, 'system');
            }

        } catch (error) {
            console.error('Error starting conversation:', error);
            this.addChatMessage('system', 'Error starting conversation', 'system');
        }
    }

    async writeSpec() {
        if (!this.currentProject || !this.conversationActive) return;

        // Disable the button and show thinking
        document.getElementById('writeSpecBtn').disabled = true;
        document.getElementById('writeSpecBtn').textContent = this.uatActive ? 'Updating...' : 'Creating...';
        this.setWaitingForInput(false);
        this.showThinkingIndicator('project_manager');

        try {
            const endpoint = this.uatActive ? 'update-reqs' : 'write-spec';
            const res = await fetch(`/api/projects/${this.currentProject}/${endpoint}`, {
                method: 'POST'
            });

            const data = await res.json();
            if (data.status === 'error') {
                this.addChatMessage('system', `Error: ${data.message}`, 'system');
            }
        } catch (error) {
            console.error('Error writing spec:', error);
            this.addChatMessage('system', 'Error creating spec. Please try again.', 'system');
        } finally {
            document.getElementById('writeSpecBtn').disabled = false;
            document.getElementById('writeSpecBtn').textContent = this.uatActive ? 'Update Reqs' : 'Write Spec';
        }
    }

    async startWork() {
        if (!this.currentProject) return;

        // Switch to activity tab to see progress
        this.switchTab('activity');
        this.workInProgress = true;
        this.updateWorkButtons();

        try {
            const res = await fetch(`/api/projects/${this.currentProject}/start-work`, {
                method: 'POST'
            });

            const data = await res.json();
            if (data.status === 'error') {
                alert(data.message || 'Error starting work');
                this.workInProgress = false;
                this.updateWorkButtons();
            }
        } catch (error) {
            console.error('Error starting work:', error);
            alert('Error starting work');
            this.workInProgress = false;
            this.updateWorkButtons();
        }
    }

    async launchProject() {
        if (!this.currentProject) return;

        const runitWarning = document.getElementById('runitWarning');
        if (runitWarning) runitWarning.style.display = 'none';

        try {
            const res = await fetch(`/api/projects/${this.currentProject}/launch`, {
                method: 'POST'
            });

            if (!res.ok) {
                const err = await res.json();
                const message = err.detail || 'Launch failed';
                if (message.toLowerCase().includes('runit.md')) {
                    if (runitWarning) {
                        runitWarning.textContent = 'Launch needs a clear run command in runit.md. Please update it and try again.';
                        runitWarning.style.display = 'block';
                    }
                    await this.showRunitModal();
                }
                throw new Error(message);
            }

            const data = await res.json();
            const statusText = data.status === 'running' ? 'Project already running' : 'Launch started';
            const details = data.command ? `Command: ${data.command}` : '';

            if (runitWarning) runitWarning.style.display = 'none';

            this.addActivityItem({
                agent: 'system',
                action: statusText,
                details: details,
                timestamp: new Date().toISOString()
            });

            if (data.launch_url) {
                const opened = window.open(data.launch_url, '_blank', 'noopener');
                if (opened) {
                    this.launchWindows[this.currentProject] = opened;
                }
            }
        } catch (error) {
            console.error('Error launching project:', error);
            alert(error.message || 'Error launching project');
        }
    }

    async stopLaunch() {
        if (!this.currentProject) return;

        try {
            const res = await fetch(`/api/projects/${this.currentProject}/stop-launch`, {
                method: 'POST'
            });
            const data = await res.json();

            this.addActivityItem({
                agent: 'system',
                action: data.message || 'Launch stopped',
                timestamp: new Date().toISOString()
            });

            const opened = this.launchWindows[this.currentProject];
            if (opened && !opened.closed) {
                opened.close();
            }
            delete this.launchWindows[this.currentProject];
        } catch (error) {
            console.error('Error stopping launch:', error);
            alert(error.message || 'Error stopping launch');
        }
    }

    async showLaunchLogModal() {
        if (!this.currentProject) return;

        const overlay = document.getElementById('modalOverlay');
        const modal = document.getElementById('launchLogModal');
        const content = document.getElementById('launchLogContent');
        if (!overlay || !modal || !content) return;

        content.textContent = 'Loading launch log...';

        try {
            const res = await fetch(`/api/projects/${this.currentProject}/launch-log`);
            const data = await res.json();
            content.textContent = data.log || 'No launch log found yet.';
        } catch (error) {
            console.error('Error loading launch log:', error);
            content.textContent = 'Error loading launch log.';
        }

        overlay.style.display = 'flex';
        modal.style.display = 'block';
    }

    async pauseWork() {
        if (!this.currentProject || !this.workInProgress) return;

        try {
            const res = await fetch(`/api/projects/${this.currentProject}/pause`, {
                method: 'POST'
            });

            const data = await res.json();
            this.addActivityItem({
                agent: 'system',
                action: 'Pause requested - will stop after current task completes',
                timestamp: new Date().toISOString()
            });
        } catch (error) {
            console.error('Error pausing work:', error);
            alert('Error pausing work');
        }
    }

    async forceStopWork() {
        if (!this.currentProject) return;

        const confirmStop = confirm('Force stop will cancel all current activity for this project. Continue?');
        if (!confirmStop) return;

        try {
            const res = await fetch(`/api/projects/${this.currentProject}/force-stop`, {
                method: 'POST'
            });

            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Force stop failed');
            }

            this.workInProgress = false;
            this.uatActive = false;
            this.conversationActive = false;
            this.setWaitingForInput(false);
            this.updateWorkButtons();

            this.addActivityItem({
                agent: 'system',
                action: 'Force stop requested',
                details: 'All activity cancelled',
                timestamp: new Date().toISOString()
            });
        } catch (error) {
            console.error('Error force stopping work:', error);
            alert('Error force stopping work');
        }
    }

    async changeProjectStatus(e) {
        e.preventDefault();
        if (!this.currentProject) return;

        const select = document.getElementById('projectStatusSelect');
        const confirmBtn = document.getElementById('confirmChangeStatus');
        const newStatus = select.value;

        confirmBtn.disabled = true;
        confirmBtn.textContent = 'Changing...';

        try {
            const stopRes = await fetch(`/api/projects/${this.currentProject}/force-stop`, {
                method: 'POST'
            });

            if (!stopRes.ok && stopRes.status !== 404) {
                const data = await stopRes.json();
                throw new Error(data.detail || 'Force stop failed');
            }

            this.workInProgress = false;
            this.uatActive = false;
            this.conversationActive = false;
            this.setWaitingForInput(false);
            this.updateWorkButtons();

            const statusRes = await fetch(`/api/projects/${this.currentProject}/status`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status: newStatus, reason: 'Manual status update' })
            });
            const data = await statusRes.json();

            if (!statusRes.ok) {
                throw new Error(data.detail || data.message || 'Status update failed');
            }

            this.updateStatusDisplay(data.new_status || newStatus);
            this.hideModals();
        } catch (error) {
            console.error('Error changing status:', error);
            alert(error.message || 'Error changing status');
        } finally {
            confirmBtn.disabled = false;
            confirmBtn.textContent = 'Change Status';
        }
    }

    updateWorkButtons() {
        const startBtn = document.getElementById('startWorkBtn');
        const pauseBtn = document.getElementById('pauseBtn');
        const forceStopBtn = document.getElementById('forceStopBtn');

        if (this.workInProgress) {
            startBtn.style.display = 'none';
            pauseBtn.style.display = 'inline-block';
        } else {
            startBtn.style.display = 'inline-block';
            pauseBtn.style.display = 'none';
        }

        if (this.workInProgress || this.conversationActive || this.uatActive) {
            forceStopBtn.style.display = 'inline-block';
        } else {
            forceStopBtn.style.display = 'none';
        }
    }

    updateQualityGatesUI(qualityGates) {
        const security = document.getElementById('gateSecurity');
        const qa = document.getElementById('gateQa');
        const tests = document.getElementById('gateTests');
        if (!security || !qa || !tests) return;

        security.checked = qualityGates.run_security_review !== false;
        qa.checked = qualityGates.run_qa_review !== false;
        tests.checked = qualityGates.run_tests !== false;
    }

    async saveQualityGates() {
        const status = document.getElementById('gatesStatus');
        const security = document.getElementById('gateSecurity').checked;
        const qa = document.getElementById('gateQa').checked;
        const tests = document.getElementById('gateTests').checked;

        try {
            const res = await fetch(`/api/projects/${this.currentProject}/quality-gates`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    run_security_review: security,
                    run_qa_review: qa,
                    run_tests: tests
                })
            });
            const data = await res.json();
            if (data.status === 'success') {
                status.textContent = 'Saved';
                setTimeout(() => { status.textContent = ''; }, 1500);
            } else {
                status.textContent = 'Error';
            }
        } catch (error) {
            console.error('Error saving gates:', error);
            status.textContent = 'Error';
        }
    }

    // Completion notification methods
    showCompletionToast(message) {
        // Remove existing toast if any
        const existingToast = document.getElementById('completionToast');
        if (existingToast) existingToast.remove();

        const toast = document.createElement('div');
        toast.id = 'completionToast';
        toast.className = 'completion-toast';
        toast.innerHTML = `
            <div class="toast-icon">&#10003;</div>
            <div class="toast-content">
                <div class="toast-title">Project Complete!</div>
                <div class="toast-message">${this.escapeHtml(message)}</div>
            </div>
            <button class="toast-close" onclick="this.parentElement.remove()">&times;</button>
        `;

        document.body.appendChild(toast);

        // Trigger animation
        setTimeout(() => toast.classList.add('show'), 10);

        // Auto-remove after 10 seconds
        setTimeout(() => {
            if (toast.parentElement) {
                toast.classList.remove('show');
                setTimeout(() => toast.remove(), 300);
            }
        }, 10000);
    }

    showBrowserNotification(title, body) {
        // Check if notifications are supported and permitted
        if (!('Notification' in window)) return;

        if (Notification.permission === 'granted') {
            new Notification(title, {
                body: body,
                icon: '/static/favicon.png',
                tag: 'project-complete'
            });
        } else if (Notification.permission !== 'denied') {
            Notification.requestPermission().then(permission => {
                if (permission === 'granted') {
                    new Notification(title, {
                        body: body,
                        icon: '/static/favicon.png',
                        tag: 'project-complete'
                    });
                }
            });
        }
    }

    initSplash() {
        const overlay = document.getElementById('splashOverlay');
        if (!overlay) return;

        const storageKey = 'nightRoninSplashShown';
        if (sessionStorage.getItem(storageKey)) {
            overlay.style.display = 'none';
            return;
        }

        overlay.style.display = 'flex';

        setTimeout(() => {
            overlay.classList.add('fade-out');
        }, 1500);

        setTimeout(() => {
            overlay.style.display = 'none';
            sessionStorage.setItem(storageKey, '1');
        }, 2300);
    }

    async loadAndShowSummary() {
        if (!this.currentProject) return;

        try {
            const res = await fetch(`/api/projects/${this.currentProject}/summary`);
            const data = await res.json();

            if (data.summary) {
                // Switch to spec tab and show summary
                this.switchTab('spec');
                document.getElementById('specContent').textContent = data.summary;
            }
        } catch (error) {
            console.log('No summary available yet');
        }
    }

    handleTaskEscalation(data) {
        // Show escalation modal
        this.showEscalationModal(data.task, data.error, data.message);

        // Also add to activity feed
        this.addActivityItem({
            agent: 'system',
            action: 'Task failed - awaiting your decision',
            details: data.task,
            timestamp: new Date().toISOString()
        });
    }

    showEscalationModal(task, error, message) {
        // Create escalation modal if it doesn't exist
        let modal = document.getElementById('escalationModal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'escalationModal';
            modal.className = 'modal escalation-modal';
            modal.innerHTML = `
                <h3 class="escalation-title">Task Failed - Your Input Needed</h3>
                <div class="escalation-content">
                    <div class="escalation-task">
                        <strong>Task:</strong>
                        <p id="escalationTask"></p>
                    </div>
                    <div class="escalation-error">
                        <strong>Error:</strong>
                        <p id="escalationError"></p>
                    </div>
                </div>
                <div class="escalation-options">
                    <button class="btn escalation-btn" data-action="retry">Retry</button>
                    <button class="btn escalation-btn" data-action="skip">Skip</button>
                    <button class="btn escalation-btn" data-action="modify">Modify Task</button>
                    <button class="btn escalation-btn" data-action="remove">Remove Task</button>
                    <button class="btn escalation-btn btn-danger" data-action="stop">Stop Work</button>
                </div>
            `;

            // Add click handlers
            modal.querySelectorAll('.escalation-btn').forEach(btn => {
                btn.addEventListener('click', () => this.sendTaskDecision(btn.dataset.action));
            });

            document.getElementById('modalOverlay').appendChild(modal);
        }

        // Update content
        document.getElementById('escalationTask').textContent = task || 'Unknown task';
        document.getElementById('escalationError').textContent = error || 'Unknown error';

        // Show modal
        document.getElementById('modalOverlay').style.display = 'flex';
        modal.style.display = 'block';
    }

    async sendTaskDecision(decision) {
        if (!this.currentProject) return;

        try {
            await fetch(`/api/projects/${this.currentProject}/task-decision`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: decision })
            });

            // Hide modal
            this.hideModals();

            // Add to activity
            this.addActivityItem({
                agent: 'system',
                action: `User decision: ${decision}`,
                timestamp: new Date().toISOString()
            });

        } catch (error) {
            console.error('Error sending decision:', error);
        }
    }

    async loadLog() {
        if (!this.currentProject) return;

        try {
            const res = await fetch(`/api/projects/${this.currentProject}/log`);
            const data = await res.json();
            document.getElementById('logContent').textContent = data.log || 'No CLI call log yet. Log entries appear when agents invoke Claude Code.';
        } catch (error) {
            console.error('Error loading log:', error);
            document.getElementById('logContent').textContent = 'Error loading log.';
        }
    }

    async showRunitModal() {
        if (!this.currentProject) return;

        const overlay = document.getElementById('modalOverlay');
        const modal = document.getElementById('runitModal');
        const content = document.getElementById('runitContent');
        if (!overlay || !modal || !content) return;

        content.textContent = 'Loading runit.md...';

        try {
            const res = await fetch(`/api/projects/${this.currentProject}/runit`);
            const data = await res.json();
            content.textContent = data.runit || 'No runit.md found yet.';
        } catch (error) {
            console.error('Error loading runit.md:', error);
            content.textContent = 'Error loading runit.md.';
        }

        overlay.style.display = 'flex';
        modal.style.display = 'block';
        this.clearRunitWarning();
    }

    clearRunitWarning() {
        const runitWarning = document.getElementById('runitWarning');
        if (runitWarning) {
            runitWarning.style.display = 'none';
        }
    }

    appendDebugLine(agent, line) {
        const output = document.getElementById('debugOutput');
        if (!output) return;

        // Remove placeholder message if present
        const placeholder = output.querySelector('p');
        if (placeholder) placeholder.remove();

        const el = document.createElement('div');
        el.style.marginBottom = '1px';
        el.innerHTML = `<span style="color: #0ff; font-weight: bold;">[${this.formatAgentName(agent)}]</span> ${this.escapeHtml(line)}`;
        output.appendChild(el);

        // Auto-scroll to bottom
        output.scrollTop = output.scrollHeight;

        // Limit DOM nodes to prevent memory issues
        while (output.children.length > 5000) {
            output.removeChild(output.firstChild);
        }
    }

    async toggleDebugMode(enabled) {
        try {
            await fetch('/api/config/debug', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled })
            });

            // Show/hide debug tab
            const debugTabBtn = document.getElementById('debugTabBtn');
            if (debugTabBtn) {
                debugTabBtn.style.display = enabled ? 'inline-block' : 'none';
            }

            // Clear debug output when disabling
            if (!enabled) {
                const output = document.getElementById('debugOutput');
                if (output) {
                    output.innerHTML = '<p style="color: #666;">Debug mode disabled. Enable debug mode and start work to see output here.</p>';
                }
            }
        } catch (error) {
            console.error('Error toggling debug mode:', error);
        }
    }

    async deleteProject() {
        if (!this.currentProject) return;
        if (!confirm(`Are you sure you want to permanently delete "${this.currentProject}"? This cannot be undone.`)) return;

        try {
            const res = await fetch(`/api/projects/${this.currentProject}`, { method: 'DELETE' });
            if (!res.ok) {
                let msg = `Server error (${res.status})`;
                try { const data = await res.json(); msg = data.detail || msg; } catch (_) {}
                this.showErrorModal(msg);
            }
        } catch (error) {
            this.showErrorModal('Failed to delete project: ' + error.message);
        }
    }

    async zipProject() {
        if (!this.currentProject) return;
        if (!confirm(`Zip and archive "${this.currentProject}"? The project will be moved to zip_projects/ and removed from the dashboard.`)) return;

        try {
            const res = await fetch(`/api/projects/${this.currentProject}/zip`, { method: 'POST' });
            if (res.ok) {
                let msg = 'Project archived successfully';
                try { const data = await res.json(); msg = data.message || msg; } catch (_) {}
                this.showCompletionToast(msg);
            } else {
                let msg = `Server error (${res.status})`;
                try { const data = await res.json(); msg = data.detail || msg; } catch (_) {}
                this.showErrorModal(msg);
            }
        } catch (error) {
            this.showErrorModal('Failed to zip project: ' + error.message);
        }
    }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.app = new AgenticTeamApp();
});
