// @ts-check

/**
 * @typedef {{
 *   state: string,
 *   ip: string | null,
 *   launch_time: string,
 * }} Instance
 *
 * @typedef {{
 *   observed_instances?: string[],
 *   launched_instance?: string,
 *   human?: string,
 *   logs_visible?: boolean,
 * }} Job
 *
 * @typedef {{
 *   jobs: Record<string, Job>,
 *   instances: Record<string, Instance>,
 * }} DashboardData
 */

import { css, html, LitElement } from "https://cdn.jsdelivr.net/gh/lit/dist@3/all/lit-all.min.js";

class CiDashboard extends LitElement {
    /** @override */
    static properties = {
        data: { state: true },
        error: { state: true },
        _now: { state: true },
        _showTerminated: { state: true },
    };

    /** @override */
    static styles = css`
        :host { display: block; }
        table { border-collapse: collapse; width: 100%; max-width: 900px; }
        th, td { padding: 0.4rem 0.8rem; text-align: left; }
        th { color: var(--cyan); font-weight: bold; font-size: 0.85rem; text-transform: uppercase; border-bottom: 2px solid var(--border); }

        .job-row td { border-top: 1px solid var(--border); }
        .slug { font-weight: bold; }
        .slug a { text-decoration: none; }
        .slug a:hover { text-decoration: underline; }
        .state-queued { color: var(--dim); font-style: italic; }

        .instance-row td { font-size: 0.85rem; color: var(--dim); background: var(--instance-bg); }
        .instance-row td:first-child { padding-left: 2rem; }
        .instance-row.ours td:first-child { border-left: 2px solid var(--blue); padding-left: calc(2rem - 2px); }
        .instance-id { font-size: 0.8rem; }
        .ip { color: var(--cyan); }
        .age { text-align: right; }
        .state-running { color: var(--green); }
        .state-pending { color: var(--yellow); }
        .state-terminated, .state-shutting-down { color: var(--red); }

        .error { color: var(--red); }
        h1 { color: var(--fg); font-size: 1.1rem; margin-bottom: 1rem; }
        .controls { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 1rem; font-size: 0.85rem; color: var(--dim); }
        .controls label { cursor: pointer; display: flex; align-items: center; gap: 0.4rem; }
        .meta { color: var(--dim); font-size: 0.8rem; margin-top: 1rem; }
    `;

    constructor() {
        super();
        /** @type {DashboardData | null} */
        this.data = null;
        /** @type {string | null} */
        this.error = null;
        /** @type {number} */
        this._now = Date.now();
        /** @type {boolean} */
        this._showTerminated = false;
        /** @type {number | undefined} */
        this._fetchInterval = undefined;
        /** @type {number | undefined} */
        this._tickInterval = undefined;
    }

    /** @override @returns {void} */
    connectedCallback() {
        super.connectedCallback();
        this._fetch();
        this._fetchInterval = setInterval(() => this._fetch(), 5000);
        this._tickInterval = setInterval(() => {
            this._now = Date.now();
        }, 1000);
    }

    /** @override @returns {void} */
    disconnectedCallback() {
        super.disconnectedCallback();
        clearInterval(this._fetchInterval);
        clearInterval(this._tickInterval);
    }

    /** @returns {Promise<void>} */
    async _fetch() {
        try {
            const resp = await fetch("summary.json");
            if (!resp.ok) {
                throw new Error(`${resp.status}`);
            }
            this.data = await resp.json();
            this.error = null;
        } catch (e) {
            this.error = /** @type {Error} */ (e).message;
        }
    }

    /** @override */
    render() {
        if (!this.data) {
            return this.error ? html`<p class="error">${this.error}</p>` : html`<p>loading...</p>`;
        }
        const data = this.data;
        const now = this._now;

        /**
         * @param {string} iso_string
         * @returns {string}
         */
        function format_age(iso_string) {
            const ms = now - new Date(iso_string).getTime();
            const mins = Math.floor(ms / 60000);
            if (mins < 60) {
                return `${mins}m`;
            }
            return `${Math.floor(mins / 60)}h${mins % 60}m`;
        }

        /** @param {Job} job */
        function job_instances(job) {
            return (job.observed_instances || []).filter((iid) => data.instances[iid]);
        }

        /**
         * @param {string} slug
         * @param {Job} job
         */
        function render_job(slug, job) {
            const instances = job_instances(job).sort((a, b) =>
                data.instances[a].launch_time.localeCompare(data.instances[b].launch_time),
            );

            const label = job.human || slug;
            const slugCell = job.logs_visible ? html`<a href="${slug}/log.html">${label}</a>` : label;

            return html`
                <tr class="job-row">
                    <td class="slug" colspan="4">${slugCell}</td>
                </tr>
                ${
                    instances.length
                        ? instances.map((iid) => {
                              const inst = data.instances[iid];
                              return html`
                                  <tr class="instance-row ${iid === job.launched_instance ? "ours" : ""}">
                                      <td class="instance-id">${iid}</td>
                                      <td class="state-${inst.state}">${inst.state}</td>
                                      <td class="ip">${inst.ip || ""}</td>
                                      <td class="age">${format_age(inst.launch_time)}</td>
                                  </tr>
                              `;
                          })
                        : html`
                              <tr class="instance-row">
                                  <td></td>
                                  <td class="state-queued">queued</td>
                                  <td></td>
                                  <td></td>
                              </tr>
                          `
                }
            `;
        }

        /** @param {Job} job */
        function is_job_terminated(job) {
            const iids = job_instances(job);
            return (
                iids.length > 0 &&
                iids.every((iid) => ["terminated", "shutting-down"].includes(data.instances[iid].state))
            );
        }

        /** @param {Job} job */
        function newest_launch(job) {
            const iids = job_instances(job);
            if (!iids.length) {
                return Infinity;
            }
            return Math.max(...iids.map((iid) => new Date(data.instances[iid].launch_time).getTime()));
        }

        return html`
            <h1>cockpit CI</h1>
            ${this.error ? html`<p class="error">fetch error: ${this.error}</p>` : ""}
            <div class="controls">
                <label>
                    <input type="checkbox" .checked=${this._showTerminated}
                        @change=${(/** @type {Event} */ e) => {
                            this._showTerminated = /** @type {HTMLInputElement} */ (e.target).checked;
                        }}>
                    show terminated
                </label>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>job</th>
                        <th>state</th>
                        <th>ip</th>
                        <th class="age">age</th>
                    </tr>
                </thead>
                <tbody>
                    ${Object.entries(data.jobs)
                        .filter(([, job]) => this._showTerminated || !is_job_terminated(job))
                        .sort(([, a], [, b]) => newest_launch(b) - newest_launch(a))
                        .map(([slug, job]) => render_job(slug, job))}
                </tbody>
            </table>
        `;
    }
}

customElements.define("ci-dashboard", CiDashboard);
