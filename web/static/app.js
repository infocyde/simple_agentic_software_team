// Agentic Software Team - Frontend Application

class AgenticTeamApp {
    constructor() {
        this.currentProject = null;
        this.ws = null;
        this.pendingInputRequest = null;
        this.messageType = null;

        this.init();
    }

    init() {
        this.connectWebSocket();
        this.bindEvents();
    }

    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleActivity(data);
        };

        this.ws.onclose = () => {
            // Reconnect after 2 seconds
            setTimeout(() => this.connectWebSocket(), 2000);
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
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
        document.getElementById('continueBtn').addEventListener('click', () => this.continueWork());
        document.getElementById('cancelMessage').addEventListener('click', () => this.hideModals());
        document.getElementById('messageForm').addEventListener('submit', (e) => this.sendMessage(e));

        // Human input form
        document.getElementById('inputForm').addEventListener('submit', (e) => this.submitHumanInput(e));

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
    }

    async selectProject(name) {
        this.currentProject = name;

        // Update UI
        document.querySelectorAll('.project-item').forEach(item => {
            item.classList.toggle('active', item.dataset.name === name);
        });

        document.getElementById('noProjectSelected').style.display = 'none';
        document.getElementById('projectView').style.display = 'block';
        document.getElementById('projectTitle').textContent = name;

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

        } catch (error) {
            console.error('Error loading project data:', error);
        }
    }

    handleActivity(data) {
        // Check if this is a human input request
        if (data.type === 'human_input_needed') {
            this.showInputModal(data.question);
            return;
        }

        // Update agent status
        if (data.agent) {
            this.updateAgentStatus(data.agent, 'working');
            // Reset to idle after a delay
            setTimeout(() => this.updateAgentStatus(data.agent, 'idle'), 3000);
        }

        // Add to activity feed if for current project
        if (data.project === this.currentProject || !data.project) {
            this.addActivityItem(data);
        }

        // Refresh project data periodically
        if (data.action && (data.action.includes('Wrote file') || data.action.includes('complete'))) {
            setTimeout(() => this.loadProjectData(), 500);
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
            'orchestrator': 'Orchestrator'
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
    }

    // Modal methods
    showNewProjectModal() {
        document.getElementById('modalOverlay').style.display = 'flex';
        document.getElementById('newProjectModal').style.display = 'block';
        document.getElementById('projectName').focus();
    }

    showMessageModal(type) {
        this.messageType = type;
        const title = type === 'kickoff' ? 'Start Project Kickoff' : 'Add Feature Request';
        const placeholder = type === 'kickoff' ?
            'Describe what you want to build...' :
            'Describe the feature you want to add...';

        document.getElementById('messageModalTitle').textContent = title;
        document.getElementById('messageInput').placeholder = placeholder;
        document.getElementById('messageInput').value = '';

        document.getElementById('modalOverlay').style.display = 'flex';
        document.getElementById('messageModal').style.display = 'block';
        document.getElementById('messageInput').focus();
    }

    showInputModal(question) {
        this.pendingInputRequest = true;
        document.getElementById('inputQuestion').textContent = question;
        document.getElementById('humanInput').value = '';

        document.getElementById('modalOverlay').style.display = 'flex';
        document.getElementById('inputModal').style.display = 'block';
        document.getElementById('humanInput').focus();
    }

    hideModals() {
        document.getElementById('modalOverlay').style.display = 'none';
        document.getElementById('newProjectModal').style.display = 'none';
        document.getElementById('messageModal').style.display = 'none';
        document.getElementById('inputModal').style.display = 'none';
    }

    // API methods
    async createProject(e) {
        e.preventDefault();
        const name = document.getElementById('projectName').value.trim();
        if (!name) return;

        try {
            const res = await fetch('/api/projects', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name })
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

    async sendMessage(e) {
        e.preventDefault();
        const message = document.getElementById('messageInput').value.trim();
        if (!message || !this.currentProject) return;

        const endpoint = this.messageType === 'kickoff' ? 'kickoff' : 'feature';

        try {
            const res = await fetch(`/api/projects/${this.currentProject}/${endpoint}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project: this.currentProject, message })
            });

            const data = await res.json();
            this.hideModals();

            // Switch to activity tab to see progress
            this.switchTab('activity');

        } catch (error) {
            console.error('Error sending message:', error);
            alert('Error sending message');
        }
    }

    async continueWork() {
        if (!this.currentProject) return;

        try {
            const res = await fetch(`/api/projects/${this.currentProject}/continue`, {
                method: 'POST'
            });

            const data = await res.json();

            // Switch to activity tab to see progress
            this.switchTab('activity');

        } catch (error) {
            console.error('Error continuing work:', error);
            alert('Error continuing work');
        }
    }

    async submitHumanInput(e) {
        e.preventDefault();
        const response = document.getElementById('humanInput').value.trim();
        if (!response || !this.currentProject) return;

        try {
            await fetch(`/api/projects/${this.currentProject}/human-input`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project: this.currentProject, response })
            });

            this.pendingInputRequest = false;
            this.hideModals();

        } catch (error) {
            console.error('Error submitting input:', error);
            alert('Error submitting input');
        }
    }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.app = new AgenticTeamApp();
});
