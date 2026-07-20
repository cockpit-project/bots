import { html, LitElement, nothing, repeat } from "https://cdn.jsdelivr.net/gh/lit/dist@3/all/lit-all.min.js";

/**
 * @typedef {{
 *   url: string,
 *   icon: string,
 *   label: string,
 *   color: string,
 * }} LinkMatch
 */
const link_patterns = [
    {
        label: "changed pixels",
        pattern: /Pixel test ([A-Za-z0-9_\-.]+) failed:/gm,
        url: "pixeldiff.html#$1",
    },
    {
        label: "screenshot",
        pattern: /Wrote screenshot to ([A-Za-z0-9\-.]+\.png)$/gm,
        icon: "fas fa-fw fa-image",
        color: "pf-m-teal",
    },
    {
        label: "html",
        pattern: /Wrote HTML dump to ([A-Za-z0-9\-.]+\.html)$/gm,
        icon: "fas fa-fw fa-file",
        color: "pf-m-yellow",
    },
    {
        label: "new pixels",
        pattern: /New pixel test reference ([A-Za-z0-9\-.]+\.png)$/gm,
    },
    {
        label: "journal",
        pattern: /Journal extracted to ([A-Za-z0-9\-.]+\.log(?:\.[gx]z)?)$/gm,
        icon: "fas fa-fw fa-pencil-alt",
        color: "pf-m-yellow",
    },
    {
        label: "coverage",
        pattern: /Code coverage report in ([A-Za-z0-9\-./]+)$/gm,
        color: "pf-m-yellow",
    },
];

/**
 * @param {string} segment
 * @returns {LinkMatch[][]}
 */
function find_patterns(segment) {
    /**
     * @param {string} tmpl
     * @param {RegExpExecArray} match
     * @returns {string}
     */
    function fmt(tmpl, match) {
        return tmpl.replace(/\$([0-9]+)/g, (_m, x) => match[Number(x)]);
    }

    const links = [];
    for (const p of link_patterns) {
        const matches = [];
        for (const m of segment.matchAll(p.pattern)) {
            const url = fmt(p.url || "$1", m);
            const icon = p.icon || "fas fa-fw fa-external-link-alt";
            const label = fmt(p.label || "file", m);
            const color = p.color || "pf-m-custom";
            matches.push({ url, icon, label, color });
        }
        if (matches.length) {
            links.push(matches);
        }
    }
    return links;
}

// --- TAP parsing ---

/**
 * @typedef {{
 *   status: 'prologue' | 'pass' | 'fail' | 'skip' | 'todo' | 'epilogue'
 *   idx: number,
 *   id: string,
 *   title?: string,
 *   retry: number | null,
 *   text: string,
 *   reason?: string,
 * }} TapEntry
 *
 * @typedef {{
 *   title: string,
 *   entries: TapEntry[],
 *   total: number,
 *   total_test_time: number | null,
 *   counts: {
 *     passed: number,
 *     failed: number,
 *     skipped: number,
 *     retried_fail: number,
 *     retried_pass: number,
 *   },
 * }} TapResult
 */

/**
 * @param {string} text
 * @returns {TapResult | null}
 */
function parse_tap(text) {
    const range = text.match(/^(?<prologue>.*?^1\.\.(?<n_tests>\d+)\n)(?<body>.*)$/ms);
    if (!range?.groups) {
        return null;
    }

    /** @type {TapEntry[]} */
    const entries = [
        {
            status: "prologue",
            idx: 0,
            id: "prologue",
            retry: null,
            text: range.groups.prologue,
        },
    ];

    let passed = 0;
    let failed = 0;
    let skipped = 0;
    let retried_fail = 0;
    let retried_pass = 0;

    const tap_result = /^(?<ok>ok|not ok) (?<num>\d+) (?<name>.*?)(?: *# (?<comment>.*))?\n/gm;
    const body = range.groups.body;
    let body_offset = 0;
    for (const m of body.matchAll(tap_result)) {
        /* Cut the total text area corresponding to the test in question */
        const end = m.index + m[0].length;
        const section = body.slice(body_offset, end);
        body_offset = end;

        /* Categorize */
        const ok = m.groups?.ok === "ok";
        const skip = m.groups?.comment?.match(/^SKIP (.*)$/);
        const todo = m.groups?.comment?.match(/^TODO (.*)$/);
        const retry = m.groups?.comment?.match(/^RETRY (\d+)/);

        if (retry) {
            if (ok) {
                retried_pass++;
            } else {
                retried_fail++;
            }
        } else if (skip || todo) {
            skipped++;
        } else if (ok) {
            passed++;
        } else {
            failed++;
        }

        /* Create the TestEntry */
        entries.push({
            status: skip ? "skip" : todo ? "todo" : ok ? "pass" : "fail",
            idx: parseInt(m.groups?.num ?? "0", 10),
            id: retry ? `${m.groups?.num}-${retry[1]}` : (m.groups?.num ?? "0"),
            title: m.groups?.name ?? "",
            retry: retry ? parseInt(retry[1], 10) : null,
            text: section,
            ...(skip ? { reason: skip[1] } : todo ? { reason: todo[1] } : {}),
        });
    }

    const epilogue = body.slice(body_offset);
    if (epilogue) {
        entries.push({
            status: "epilogue",
            idx: Infinity,
            id: "epilogue",
            retry: null,
            text: epilogue,
        });
    }

    const timing = text.match(/^# (\d+ TESTS FAILED|TESTS PASSED) \[(\d+)s on .*\]$/m);
    return {
        title: text.slice(0, text.indexOf("\n")),
        entries,
        total_test_time: timing ? Math.ceil(parseInt(timing[2], 10) / 60) : null,
        total: parseInt(range.groups.n_tests, 10),
        counts: { passed, failed, skipped, retried_fail, retried_pass },
    };
}

// --- UI components ---

class TestEntry extends LitElement {
    /** @override */ static properties = {
        entry: { type: Object },
        expanded: { state: true },
    };

    /** @override */ createRenderRoot() {
        return this;
    }

    constructor() {
        super();
        /** @type {TapEntry} */
        this.entry;
        /** @type {boolean} */
        this.expanded = false;
    }

    /** @override */ connectedCallback() {
        super.connectedCallback();
        this.expanded = this.entry?.status === "fail" && this.entry?.retry === null;
    }

    toggle() {
        this.expanded = !this.expanded;
    }

    /** @param {LinkMatch[]} links */
    open_all_links(links) {
        for (const link of links) {
            window.open(`./${link.url}`);
        }
    }

    /** @param {LinkMatch[]} group */
    render_link_group(group) {
        return html`
            <div class="pf-v6-c-label-group pf-m-category">
                <div class="pf-v6-c-label-group__main">
                    <span class="pf-v6-c-label-group__label" aria-hidden="true">
                        <span class="pf-v6-c-label pf-m-filled pf-m-clickable pf-m-info">
                            <button class="pf-v6-c-label__content pf-m-clickable" type="button"
                                @click=${() => this.open_all_links(group)}>
                                <span class="pf-v6-c-label__icon">
                                    <i class="fas fa-fw fa-external-link-alt" aria-hidden="true"></i>
                                </span>
                                <span class="pf-v6-c-label__text">Open all</span>
                            </button>
                        </span>
                    </span>
                    <ul class="pf-v6-c-label-group__list" role="list">
                        ${group.map(
                            (link) => html`
                            <li class="pf-v6-c-label-group__list-item">
                                <span class="pf-v6-c-label pf-m-filled ${link.color} pf-m-clickable">
                                    <a class="pf-v6-c-label__content pf-m-clickable"
                                       href="./${link.url}" target="_blank">
                                        <span class="pf-v6-c-label__icon">
                                            <i class="${link.icon}" aria-hidden="true"></i>
                                        </span>
                                        <span class="pf-v6-c-label__text">${link.label}</span>
                                    </a>
                                </span>
                            </li>
                        `,
                        )}
                    </ul>
                </div>
            </div>
            <br>`;
    }

    render_title() {
        const { title, retry } = this.entry;
        if (retry !== null) {
            return html`${title} <mark>RETRY ${retry}</mark>`;
        }
        return title;
    }

    /** @override */ render() {
        const entry = this.entry;
        const classes = [
            "test-entry",
            entry.status === "fail" ? "failed" : "",
            entry.retry !== null ? "retried" : "",
            entry.status === "skip" || entry.status === "todo" ? "skipped" : "",
        ]
            .filter(Boolean)
            .join(" ");

        return html`
            <li class="pf-v6-c-data-list__item ${classes} ${this.expanded ? "pf-m-expanded" : ""}" id="${entry.id}">
                <div class="pf-v6-c-data-list__item-row">
                    <div class="pf-v6-c-data-list__item-control">
                        <div class="pf-v6-c-data-list__toggle test-entry-toggle">
                            <button class="pf-v6-c-button pf-m-plain" type="button"
                                aria-expanded="${this.expanded}" @click=${() => this.toggle()}>
                                <span class="pf-v6-c-button__icon pf-m-start">
                                    <div class="pf-v6-c-data-list__toggle-icon">
                                        <i class="fas fa-angle-right" aria-hidden="true"></i>
                                    </div>
                                </span>
                            </button>
                        </div>
                    </div>
                    <div class="pf-v6-c-data-list__item-content">
                        <div class="pf-v6-c-data-list__cell">
                            <a href="#${entry.id}" class="pf-v6-c-button pf-m-inline pf-m-link">
                                <span class="pf-v6-c-button__text">${entry.id}</span>
                            </a>${entry.title ? html`:&nbsp;<span>${this.render_title()}</span>` : nothing}
                            ${entry.reason ? html`<span>-- <mark>skipped:</mark> ${entry.reason}</span>` : nothing}
                            <div>
                                ${find_patterns(entry.text).map((group) => this.render_link_group(group))}
                            </div>
                        </div>
                    </div>
                </div>
                <div class="pf-v6-c-data-list__expandable-content" ?hidden=${!this.expanded}>
                    <div class="pf-v6-c-data-list__expandable-content-body">
                        <div class="pf-v6-c-code-block">
                            <div class="pf-v6-c-code-block__content">
                                <pre class="pf-v6-c-code-block__pre"><code class="pf-v6-c-code-block__code">${entry.text}</code></pre>
                            </div>
                        </div>
                    </div>
                </div>
            </li>`;
    }
}

customElements.define("test-entry", TestEntry);

class LogViewer extends LitElement {
    /** @override */ static properties = {
        href: { type: String },
        content: { state: true },
        raw: { state: true },
        show_only_failed: { state: true },
    };

    /** @override */ createRenderRoot() {
        return this;
    }

    constructor() {
        super();
        /** @type {string} */
        this.href = "log";
        /** @type {string} */
        this.content = "";
        /** @type {boolean} */
        this.raw = false;
        /** @type {boolean} */
        this.show_only_failed = true;
    }

    /** @override */ connectedCallback() {
        super.connectedCallback();
        fetch_content(this.href, (text) => {
            this.content += text;
        });
    }

    /**
     * @param {number} total
     * @param {number} finished
     */
    render_progress(total, finished) {
        const pct = Math.floor((finished / total) * 100);

        return html`
            <div class="pf-v6-c-progress pf-m-sm">
                <div class="pf-v6-c-progress__description">Test progress</div>
                <div class="pf-v6-c-progress__status" aria-hidden="true">
                    <span class="pf-v6-c-progress__measure">${finished}/${total} (${pct}%)</span>
                </div>
                <div class="pf-v6-c-progress__bar" role="progressbar"
                     aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}">
                    <div class="pf-v6-c-progress__indicator" style="width:${pct}%"></div>
                </div>
            </div>`;
    }

    /** @param {TapResult} tap */
    render_stats(tap) {
        const left = tap.total - tap.counts.passed - tap.counts.failed - tap.counts.skipped;

        return html`
            <div class="pf-v6-u-mt-m">
                ${
                    tap.total_test_time
                        ? html`
                    <span class="pf-v6-c-timestamp">
                        <time class="pf-v6-c-timestamp__text" datetime="${tap.total_test_time}m">
                            took ${tap.total_test_time} minutes to run
                        </time>
                    </span>
                    <br>`
                        : nothing
                }
                <div class="pf-v6-c-label-group pf-m-category">
                    <div class="pf-v6-c-label-group__main">
                        <span class="pf-v6-c-label-group__label" aria-hidden="true">
                            ${tap.total} tests${left ? `, ${left} left` : ""}
                        </span>
                        <ul class="pf-v6-c-label-group__list" role="list">
                            <li class="pf-v6-c-label-group__list-item">
                                <span class="pf-v6-c-label pf-m-filled pf-m-success">
                                    <span class="pf-v6-c-label__content">
                                        <span class="pf-v6-c-label__icon">
                                            <i class="fas fa-fw fa-check-circle" aria-hidden="true"></i>
                                        </span>
                                        <span class="pf-v6-c-label__text">${tap.counts.passed} passed</span>
                                    </span>
                                </span>
                            </li>
                            <li class="pf-v6-c-label-group__list-item">
                                <span class="pf-v6-c-label pf-m-filled ${tap.counts.skipped ? "pf-m-yellow" : ""}">
                                    <span class="pf-v6-c-label__content">
                                        <span class="pf-v6-c-label__icon">
                                            <i class="fas fa-fw fa-exclamation-triangle" aria-hidden="true"></i>
                                        </span>
                                        <span class="pf-v6-c-label__text">${tap.counts.skipped} skipped</span>
                                    </span>
                                </span>
                            </li>
                            <li class="pf-v6-c-label-group__list-item">
                                <span class="pf-v6-c-label pf-m-filled ${tap.counts.failed ? "pf-m-danger" : ""}">
                                    <span class="pf-v6-c-label__content">
                                        <span class="pf-v6-c-label__icon">
                                            <i class="fas fa-fw fa-exclamation-circle" aria-hidden="true"></i>
                                        </span>
                                        <span class="pf-v6-c-label__text">${tap.counts.failed} failed</span>
                                    </span>
                                </span>
                            </li>
                            ${
                                tap.counts.retried_fail
                                    ? html`
                                <li class="pf-v6-c-label-group__list-item">
                                    <span class="pf-v6-c-label pf-m-filled pf-m-info">
                                        <span class="pf-v6-c-label__content">
                                            <span class="pf-v6-c-label__icon">
                                                <i class="fas fa-fw fa-info-circle" aria-hidden="true"></i>
                                            </span>
                                            <span class="pf-v6-c-label__text">${tap.counts.retried_fail} retries of failures</span>
                                        </span>
                                    </span>
                                </li>`
                                    : nothing
                            }
                            ${
                                tap.counts.retried_pass
                                    ? html`
                                <li class="pf-v6-c-label-group__list-item">
                                    <span class="pf-v6-c-label pf-m-filled pf-m-info">
                                        <span class="pf-v6-c-label__content">
                                            <span class="pf-v6-c-label__icon">
                                                <i class="fas fa-fw fa-info-circle" aria-hidden="true"></i>
                                            </span>
                                            <span class="pf-v6-c-label__text">${tap.counts.retried_pass} retries of successes</span>
                                        </span>
                                    </span>
                                </li>`
                                    : nothing
                            }
                        </ul>
                    </div>
                </div>
            </div>`;
    }

    render_toolbar() {
        return html`
            <div class="pf-v6-c-toolbar pf-m-no-padding">
                <div class="pf-v6-c-toolbar__content">
                    <div class="pf-v6-c-toolbar__content-section">
                        <div class="pf-v6-c-toolbar__item">
                            <a class="pf-v6-c-button pf-m-small pf-m-link" href="./index.html">
                                <span class="pf-v6-c-button__icon pf-m-start">
                                    <i class="fas fa-folder" aria-hidden="true"></i>
                                </span>
                                <span class="pf-v6-c-button__text">Result directory</span>
                            </a>
                        </div>
                        <div class="pf-v6-c-toolbar__item">
                            <button class="pf-v6-c-button pf-m-small pf-m-link"
                                @click=${() => {
                                    this.raw = !this.raw;
                                }}>
                                <span class="pf-v6-c-button__icon pf-m-start">
                                    <i class="fas ${this.raw ? "fa-clipboard-check" : "fa-file-alt"}" aria-hidden="true"></i>
                                </span>
                                <span class="pf-v6-c-button__text">${this.raw ? "Parsed view" : "Raw log"}</span>
                            </button>
                        </div>
                    </div>
                </div>
            </div>`;
    }

    /** @param {boolean} has_failed */
    render_filter_toggle(has_failed) {
        return html`
            <div>
                <label class="pf-v6-c-switch">
                    <input class="pf-v6-c-switch__input" type="checkbox" role="switch"
                           .checked=${has_failed ? this.show_only_failed : false}
                           @change=${(/** @type {Event & { target: HTMLInputElement }} */ e) => {
                               this.show_only_failed = e.target.checked;
                           }}>
                    <span class="pf-v6-c-switch__toggle"></span>
                    <span class="pf-v6-c-switch__label" aria-hidden="true">Show only failed</span>
                </label>
            </div>`;
    }

    render_raw() {
        return html`
            <div class="pf-v6-c-code-block">
                <div class="pf-v6-c-code-block__content">
                    <pre class="pf-v6-c-code-block__pre"><code class="pf-v6-c-code-block__code">${this.content}</code></pre>
                </div>
            </div>`;
    }

    /** @param {TapResult} tap */
    render_parsed(tap) {
        const finished = tap.counts.passed + tap.counts.failed + tap.counts.skipped;
        const sorted_entries = [...tap.entries].sort((a, b) => {
            return a.idx - b.idx || (a.retry ?? Infinity) - (b.retry ?? Infinity);
        });
        const has_failed = tap.counts.failed > 0;
        const visible_entries =
            this.show_only_failed && has_failed
                ? sorted_entries.filter((e) => e.status === "fail" || e.retry !== null)
                : sorted_entries;

        return html`
            ${this.render_progress(tap.total, finished)}
            ${this.render_stats(tap)}
            ${this.render_filter_toggle(has_failed)}
            <ul class="pf-v6-c-data-list pf-m-compact">
                ${repeat(
                    visible_entries,
                    (e) => e.id,
                    (entry) => html`<test-entry .entry=${entry}></test-entry>`,
                )}
            </ul>`;
    }

    /** @override */ render() {
        const tap = !this.raw ? parse_tap(this.content) : null;
        const title = tap ? tap.title : "Logs";

        return html`
            <h1 class="pf-v6-c-title pf-m-2xl">${title}</h1>
            ${this.render_toolbar()}
            ${tap ? this.render_parsed(tap) : this.render_raw()}`;
    }
}

customElements.define("log-viewer", LogViewer);

// --- s3streamer client ---

/** @param {number} seconds */
function sleep(seconds) {
    return new Promise((resolve) => setTimeout(resolve, 1000 * seconds));
}

class NotFoundError extends Error {}
class RetriableError extends Error {}

/**
 * @param {string} url
 * @param {number} offset
 * @returns {Promise<string>}
 */
async function fetch_once(url, offset = 0) {
    /** @type {Response} */
    let response;
    try {
        response = await fetch(url, { headers: { Range: `bytes=${offset}-` } });
    } catch (exc) {
        // The fetch() API throws TypeError for network errors
        if (exc instanceof TypeError) {
            throw new RetriableError(exc.message);
        } else {
            throw exc;
        }
    }

    // The fetch() API doesn't throw on non-success responses, so we
    // need to check the status ourselves and throw accordingly.
    if (response.status === 206) {
        return await response.text();
    }
    // Accept 200 for servers that don't support Range (e.g. python -m http.server)
    if (response.status === 200) {
        const buffer = await response.arrayBuffer();
        return new TextDecoder().decode(buffer.slice(offset));
    }

    // S3 returns 403 instead of 404 when s3:ListBucket is not granted
    if (response.status === 403 || response.status === 404) {
        throw new NotFoundError();
    } else if (response.status >= 500) {
        throw new RetriableError(`Server error ${response.status}`);
    } else {
        throw new Error(`Unexpected status ${response.status}`);
    }
}

/**
 * @param {string} url
 * @param {number} offset
 * @returns {Promise<string>}
 */
async function fetch_from(url, offset = 0) {
    for (let attempts = 0; attempts < 10; attempts++) {
        try {
            return await fetch_once(url, offset);
        } catch (error) {
            if (error instanceof RetriableError) {
                const delay = 2 ** attempts;
                console.log(`Failed to fetch ${url}: ${error}.  Waiting ${delay}.`);
                await sleep(delay);
            } else {
                throw error;
            }
        }
    }

    return await fetch_once(url, offset);
}

/**
 * @param {string} filename
 * @param {(text: string) => void} on_data
 */
async function fetch_content(filename, on_data) {
    /* Content is unicode text, but we need to know how many bytes we have in
     * order to perform chunk calculations.  Track that separately.
     */
    let bytes = 0;

    try {
        while (true) {
            /** @type {number[]} */
            const chunks = JSON.parse(await fetch_from(`${filename}.chunks`));
            let chunk_start = 0;

            for (const chunk_size of chunks) {
                const chunk_end = chunk_start + chunk_size;

                if (bytes < chunk_end) {
                    on_data(await fetch_from(`${filename}.${chunk_start}-${chunk_end}`, bytes - chunk_start));
                    bytes = chunk_end;
                }

                chunk_start = chunk_end;
            }

            await sleep(30);
        }
    } catch (e) {
        // If any of the chunk files are not found, the complete file is expected to be present.
        if (!(e instanceof NotFoundError)) {
            throw e;
        }
    }

    on_data(await fetch_from(filename, bytes));
}
