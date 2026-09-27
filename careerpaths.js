// interaction.js supplies the student selected by test_id and its alumni CSV fetch.
const CareerPaths = (() => {
    // Quoted CSV fields can contain commas, escaped quotes, and newlines.
    function parseCSV(text) {
        const rows = [];
        let row = [];
        let field = "";
        let quoted = false;
        for (let i = 0; i < text.length; i++) {
            const char = text[i];
            if (char === '"') {
                if (quoted && text[i + 1] === '"') {
                    field += '"';
                    i++;
                } else {
                    quoted = !quoted;
                }
            } else if (char === "," && !quoted) {
                row.push(field.trim());
                field = "";
            } else if ((char === "\n" || char === "\r") && !quoted) {
                row.push(field.trim());
                if (row.some(value => value !== "")) rows.push(row);
                row = [];
                field = "";
                if (char === "\r" && text[i + 1] === "\n") i++;
            } else {
                field += char;
            }
        }
        if (quoted) throw new Error("The alumni CSV contains an unclosed quoted field.");
        row.push(field.trim());
        if (row.some(value => value !== "")) rows.push(row);
        const headers = rows.shift() || [];
        for (const name of ["major", "degree_level", "first_job_title", "first_employer"]) {
            if (!headers.includes(name)) throw new Error("The alumni CSV is missing " + name + ".");
        }
        return rows.map(values => Object.fromEntries(headers.map((name, i) => [name, values[i] || ""])));
    }

    function fillList(id, alumni, column, major) {
        const list = document.getElementById(id);
        list.replaceChildren();
        const groups = new Map();
        for (const alum of alumni) {
            const name = alum[column];
            if (!name || name === "Not Applicable") continue;
            if (!groups.has(name)) groups.set(name, { count: 0, degrees: new Set() });
            const group = groups.get(name);
            group.count++;
            if (alum.degree_level && alum.degree_level !== "Not Applicable") group.degrees.add(alum.degree_level);
        }
        const sorted = [...groups].sort((a, b) => b[1].count - a[1].count || a[0].localeCompare(b[0]));
        for (const [name, group] of sorted) {
            const item = document.createElement("li");
            const title = document.createElement("strong");
            title.textContent = name;
            const detail = document.createElement("span");
            detail.textContent = `${major} · ${[...group.degrees].sort().join(" / ")} · ${group.count} ${group.count === 1 ? "alum" : "alumni"}`;
            item.append(title, detail);
            list.appendChild(item);
        }
        if (!sorted.length) {
            const item = document.createElement("li");
            item.textContent = "No reported outcomes for this major.";
            list.appendChild(item);
        }
    }

    function render(csv, student) {
        // Current students has a major, but no degree_level: show and label all
        // alumni degree levels for that major instead of assuming a degree.
        const alumni = parseCSV(csv).filter(alum => alum.major === student.major);
        document.getElementById("career-paths-summary").textContent =
            `${student.major} · Based on ${alumni.length} alumni with your major, across all tracks and degree levels.`;
        fillList("career-paths-list", alumni, "first_job_title", student.major);
        fillList("career-companies-list", alumni, "first_employer", student.major);
    }

    function showError(message) {
        document.getElementById("career-paths-summary").textContent = "Career paths unavailable. " + message;
        document.getElementById("career-paths-list").replaceChildren();
        document.getElementById("career-companies-list").replaceChildren();
    }

    return { render, showError };
})();
